from typing import Any

from app.agents.base import normalize_operations, toolbox, trace
from app.agents.runtime import create_tool_agent, rendered_files_from_tool_trace, run_agent
from app.agents.state import AgentState
from app.config import settings

BROLL_AGENT_PROMPT = """
你是 AICut 的 B-roll Agent。
你通过工具自主读取时间线、字幕和素材，判断哪里适合插入覆盖素材。
需要素材信息时调用 get_project_assets 或 search_project_assets；需要上下文时调用 get_project_timeline、get_project_subtitles 或 build_packed_transcript。
如使用现有素材，输出 INSERT_BROLL_OVERLAY；不能编造 asset_id。
需要验证覆盖效果或生成预览时调用 ffmpeg_overlay_asset；需要检查素材画面或插入点前后时调用 ffmpeg_extract_frame 或 render_timeline_view。
每段 B-roll 通常 3-6 秒，避免与已有 B-roll 明显重叠。
最终只输出 JSON：
{"summary":string,"operations":[...],"insertions":[...]}
""".strip()


def create_broll_agent(tools: Any) -> Any:
    return create_tool_agent(
        "broll_agent",
        BROLL_AGENT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )


def _fallback_response(error: Exception) -> dict[str, Any]:
    return {"summary": f"B-roll Agent 执行失败：{type(error).__name__}: {error}", "operations": [], "insertions": []}


async def run_broll_node(state: AgentState) -> AgentState:
    tools = toolbox(state)
    try:
        response, usage_records, tool_calls = await run_agent(
            state, "broll_agent", create_broll_agent(tools), tools
        )
    except Exception as exc:  # noqa: BLE001 - agent failures fall back to a structured response.
        response, usage_records, tool_calls = _fallback_response(exc), [], []

    summary = str(response.get("summary") or "B-roll Agent 完成。")
    operations = normalize_operations(response.get("operations"))
    rendered_files = rendered_files_from_tool_trace(tool_calls)
    outputs = dict(state.get("agent_outputs", {}))
    outputs["broll_agent"] = {
        "summary": summary,
        "operations": operations,
        "insertions": response.get("insertions") if isinstance(response.get("insertions"), list) else [],
        "rendered_files": rendered_files,
        "tool_calls": tool_calls,
    }
    return {
        "agent_outputs": outputs,
        "usage_records": [*state.get("usage_records", []), *usage_records],
        "trace": trace(
            state,
            "B-roll Agent(create_agent) 执行完成",
            summary,
            {
                "available_tools": tools.names_for("broll_agent"),
                "operation_count": len(operations),
                "rendered_files": rendered_files,
                "tool_calls": tool_calls,
            },
        ),
    }
