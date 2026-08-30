import json
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.base import toolbox, user_request
from app.agents.modes.schema import AgentMode
from app.agents.runtime import final_ai_json, message_tool_trace, message_usage_records
from app.agents.state import AgentState
from app.agents.tools.delegation import DelegationCollector, build_delegation_tools


def _fallback_response(mode: AgentMode, error: Exception) -> dict[str, Any]:
    return {
        "summary": f"{mode.label}导演 Agent 执行失败：{type(error).__name__}: {error}",
        "creative_direction": "当前没有生成可应用的剪辑计划。",
        "needs_review": False,
    }


async def run_mode_coordinator(state: AgentState, mode: AgentMode) -> AgentState:
    tools = toolbox(state)
    collector = DelegationCollector()
    coordinator_tools = [
        *[tools.get(tool_name) for tool_name in tools.names_for(mode.coordinator_name)],
        *build_delegation_tools(
            state,
            tools,
            collector,
            mode.delegates,
            mode.coordinator_name,
        ),
    ]
    request = user_request(state)
    payload = {
        "user_request": request,
        "project_id": state.get("project_id"),
        "video_type": mode.video_type,
        "creative_mode": mode.label,
        "team": list(mode.team),
        "available_tools": [agent_tool.name for agent_tool in coordinator_tools],
        "tool_policy": "先自主检查项目；需要实施时调用当前创作模式提供的专业 Agent。",
        "required_final_output": "JSON object only",
    }
    try:
        result = await mode.coordinator_factory(coordinator_tools).ainvoke(
            {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
        )
        messages = list(result.get("messages") or [])
        response = final_ai_json(messages)
        usage_records = message_usage_records(mode.coordinator_name, messages)
        tool_calls = message_tool_trace(messages)
    except Exception as exc:  # noqa: BLE001 - coordinator failures return a usable response.
        response, usage_records, tool_calls = _fallback_response(mode, exc), [], []

    summary = str(response.get("summary") or f"{mode.label}导演 Agent 已完成。")
    creative_direction = str(response.get("creative_direction") or "")
    detail = summary if not creative_direction else f"{summary} {creative_direction}"
    outputs = {**state.get("agent_outputs", {}), **collector.outputs}
    return {
        "agent_outputs": outputs,
        "reply": detail,
        "coordinator_name": mode.coordinator_name,
        "usage_records": [
            *state.get("usage_records", []),
            *usage_records,
            *collector.usage_records,
        ],
        "route_history": [*state.get("route_history", []), mode.coordinator_name],
        "trace": [
            *state.get("trace", []),
            *collector.trace,
            {
                "title": f"{mode.label}导演 Agent(create_agent) 执行完成",
                "detail": detail,
                "data": {
                    "agent": mode.coordinator_name,
                    "video_type": mode.video_type,
                    "team": list(mode.team),
                    "available_tools": [agent_tool.name for agent_tool in coordinator_tools],
                    "delegated_agents": list(collector.outputs.keys()),
                    "tool_calls": tool_calls,
                },
            },
        ],
    }


def route_after_coordinator(state: AgentState) -> str:
    return "review" if state.get("agent_outputs") else "end"
