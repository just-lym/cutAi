from typing import Any

from app.agents.base import normalize_operations, toolbox, trace
from app.agents.runtime import create_tool_agent, run_agent
from app.agents.state import AgentState
from app.config import settings

SUBTITLE_AGENT_PROMPT = """
你是 AICut 的 Subtitle Agent。
你通过工具自主读取字幕、时间线和素材，然后完成字幕相关任务。
可用操作只有 UPDATE_SUBTITLE。
如果需要查看字幕，调用 get_project_subtitles。
如果需要确认媒体或时间线，调用 get_project_timeline、get_project_assets 或 ffmpeg_probe_asset。
不要编造字幕、cue_id 或时间码。
最终只输出 JSON：
{"summary":string,"operations":[{"type":"UPDATE_SUBTITLE","cue_id":string,"text":string,"start_ms":int,"end_ms":int}]}
""".strip()


def create_subtitle_agent(tools: Any) -> Any:
    return create_tool_agent(
        "subtitle_agent",
        SUBTITLE_AGENT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )


def _fallback_response(error: Exception) -> dict[str, Any]:
    return {"summary": f"Subtitle Agent 执行失败：{type(error).__name__}: {error}", "operations": []}


async def run_subtitle_node(state: AgentState) -> AgentState:
    tools = toolbox(state)
    try:
        response, usage_records, tool_calls = await run_agent(
            state, "subtitle_agent", create_subtitle_agent(tools), tools
        )
    except Exception as exc:  # noqa: BLE001 - agent failures fall back to a structured response.
        response, usage_records, tool_calls = _fallback_response(exc), [], []

    summary = str(response.get("summary") or "Subtitle Agent 完成。")
    operations = normalize_operations(response.get("operations"))
    outputs = dict(state.get("agent_outputs", {}))
    outputs["subtitle_agent"] = {
        "summary": summary,
        "operations": operations,
        "tool_calls": tool_calls,
    }
    return {
        "agent_outputs": outputs,
        "usage_records": [*state.get("usage_records", []), *usage_records],
        "trace": trace(
            state,
            "Subtitle Agent(create_agent) 执行完成",
            summary,
            {
                "available_tools": tools.names_for("subtitle_agent"),
                "operation_count": len(operations),
                "tool_calls": tool_calls,
            },
        ),
    }
