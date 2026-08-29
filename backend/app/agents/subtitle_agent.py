from typing import Any

from app.agents.base import normalize_operations, toolbox, trace
from app.agents.runtime import create_tool_agent, rendered_files_from_tool_trace, run_agent
from app.agents.state import AgentState
from app.config import settings

SUBTITLE_AGENT_PROMPT = """
你是 AICut 的 Subtitle Agent。
你通过工具自主读取字幕、时间线和素材，然后完成字幕相关任务。
可用操作只有 UPDATE_SUBTITLE 和 CREATE_SUBTITLE。
如果需要查看字幕，调用 get_project_subtitles。
需要把字幕上下文整理给 Main Agent 或确认已有字幕覆盖范围时，调用 build_packed_transcript。
如果需要确认媒体或时间线，调用 get_project_timeline、get_project_assets 或 ffmpeg_probe_asset。
用户要求修正、翻译已有字幕时，优先输出 UPDATE_SUBTITLE 并保留原始 start_ms/end_ms。
用户要求新增一条或多条字幕，或“添加英文字幕”而不是替换原字幕时，输出 CREATE_SUBTITLE。
如果已有 cue 覆盖用户指定时间段，按原 cue 的 start_ms/end_ms 逐条生成 CREATE_SUBTITLE，并把 text 写成目标语言。
用户要求调整字幕位置、把英文放到中文下面、双语上下排列时，输出 UPDATE_SUBTITLE，不改 text，只更新 style。
英文在下方推荐 style: {"position":"lower","layer":1}；中文在上方推荐 style: {"position":"upper","layer":0}。
如果用户要求“应用到视频/看得到字幕/硬字幕预览”，在输出字幕操作后说明时间线操作需要审批应用；已有字幕可调用 render_edl_preview 或 ffmpeg_burn_timeline_subtitles 生成硬字幕文件。
不要把“已生成字幕操作”说成“已烧录到视频”，除非工具返回 output_path 和 subtitle_path。
如果用户要求 0-60 秒字幕，先调用 get_project_subtitles(start_ms=0,end_ms=60000)，不要只看摘要。
不要编造已有 cue_id；CREATE_SUBTITLE 可以不提供 cue_id，由系统应用时生成。
不要编造无法从请求、字幕或时间线推断的时间码。
最终只输出 JSON：
{"summary":string,"operations":[{"type":"UPDATE_SUBTITLE|CREATE_SUBTITLE","cue_id":string,"text":string,"start_ms":int,"end_ms":int,"style":object}]}
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
    rendered_files = rendered_files_from_tool_trace(tool_calls)
    outputs = dict(state.get("agent_outputs", {}))
    outputs["subtitle_agent"] = {
        "summary": summary,
        "operations": operations,
        "rendered_files": rendered_files,
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
                "rendered_files": rendered_files,
                "tool_calls": tool_calls,
            },
        ),
    }
