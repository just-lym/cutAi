import json
import re
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.base import compact_history, user_request
from app.agents.state import AgentState
from app.agents.tools import AgentToolbox
from app.cloud_api.langchain_chat_model import ChatDashScope


def json_from_text(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise TypeError("Agent returned non-object JSON")
    return parsed


def usage_records(agent_name: str, messages: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        metadata = dict(message.response_metadata or {})
        usage = dict(metadata.get("usage") or {})
        if not usage:
            continue
        records.append(
            {
                "agent": agent_name,
                "provider": "dashscope",
                "model": metadata.get("model"),
                "request_id": metadata.get("request_id"),
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            }
        )
    return records


def message_usage_records(agent_name: str, messages: list[Any]) -> list[dict[str, Any]]:
    return usage_records(agent_name, messages)


def tool_trace(messages: list[Any]) -> list[dict[str, Any]]:
    trace = []
    for message in messages:
        if isinstance(message, ToolMessage):
            ok = None
            try:
                payload = json.loads(str(message.content))
                ok = payload.get("ok")
            except json.JSONDecodeError:
                payload = {}
            trace.append(
                {
                    "name": message.name,
                    "ok": bool(ok),
                    "data": {
                        "result_keys": list(payload.keys()),
                        "artifact_type": payload.get("artifact_type"),
                        "count": payload.get("count"),
                        "error": payload.get("error"),
                        "output_path": payload.get("output_path"),
                        "output_paths": payload.get("output_paths"),
                        "preview_path": payload.get("preview_path"),
                        "artifact_path": payload.get("artifact_path"),
                        "edl_path": payload.get("edl_path"),
                        "contact_sheet_path": payload.get("contact_sheet_path"),
                        "subtitle_path": payload.get("subtitle_path"),
                    },
                }
            )
    return trace


def rendered_files_from_tool_trace(tool_calls: list[dict[str, Any]]) -> list[str]:
    files: list[str] = []
    media_suffixes = {".mp4", ".mov", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".flac"}

    def append_media_path(path: Any) -> None:
        if path and Path(str(path)).suffix.lower() in media_suffixes:
            files.append(str(path))

    for call in tool_calls:
        data = call.get("data") if isinstance(call, dict) else {}
        if not isinstance(data, dict):
            continue
        append_media_path(data.get("output_path"))
        append_media_path(data.get("preview_path"))
        for path in data.get("output_paths") or []:
            append_media_path(path)
    return list(dict.fromkeys(files))


def message_tool_trace(messages: list[Any]) -> list[dict[str, Any]]:
    return tool_trace(messages)


def final_ai_json(messages: list[Any]) -> dict[str, Any]:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return json_from_text(str(message.content or ""))
    raise ValueError("Agent did not produce a final JSON message")


def create_tool_agent(
    agent_name: str,
    system_prompt: str,
    toolbox: AgentToolbox,
    model: str,
) -> Any:
    return create_agent(
        model=ChatDashScope(model=model, temperature=0.2),
        tools=[toolbox.get(tool_name) for tool_name in toolbox.names_for(agent_name)],
        system_prompt=system_prompt,
        name=agent_name,
    )


async def run_agent(
    state: AgentState,
    agent_name: str,
    agent: Any,
    toolbox: AgentToolbox,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = {
        "user_request": user_request(state),
        "delegated_task": state.get("delegated_task"),
        "project_id": state.get("project_id"),
        "agent_outputs": state.get("agent_outputs", {}),
        "history": compact_history(state.get("history", []), limit=20),
        "preferences": state.get("preferences", {}),
        "selection": state.get("selection"),
        "evidence": state.get("evidence", {}),
        "available_tools": toolbox.names_for(agent_name),
        "required_final_output": "JSON object only",
    }
    result = await agent.ainvoke({"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]})
    messages = list(result.get("messages") or [])
    return final_ai_json(messages), usage_records(agent_name, messages), tool_trace(messages)
