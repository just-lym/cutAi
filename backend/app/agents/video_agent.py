from typing import Any

from app.agents.base import toolbox, trace
from app.agents.runtime import create_tool_agent, rendered_files_from_tool_trace, run_agent
from app.agents.state import AgentState
from app.config import settings

VIDEO_AGENT_PROMPT = """
你是 AICut 的 Video Agent。
你通过 FFmpeg 工具自主完成明确的视频剪切、截取、删除区间和导出任务。
需要判断时长或选择素材时先调用 get_project_timeline、get_project_assets 或 ffmpeg_probe_asset。
需要自主粗剪、预览当前时间线或验证渲染思路时，优先调用 build_packed_transcript、build_timeline_edl、validate_edl、summarize_edl_sources。
需要实际合成一版预览时，调用 render_edl_preview；它会按分段抽取、切点短淡化、concat、字幕最后应用的规则工作。
用户要求“截取 10 秒到 20 秒”“剪出前 5 秒”时，调用 ffmpeg_cut_segment。
用户要求删除多个区间或删除静音后输出文件时，调用 ffmpeg_remove_ranges。
用户要求快速预览、压缩或浏览器可播放文件时，调用 ffmpeg_transcode_preview。
用户要求封面、检查画面或某个时间点截图时，调用 ffmpeg_extract_frame。
用户要求横转竖、方形画幅、裁剪、补边或平台比例时，调用 ffmpeg_crop_scale。
用户要求找镜头变化、自动粗剪参考点或节奏分析时，调用 ffmpeg_detect_scene_changes 或 ffmpeg_extract_thumbnails。
需要确认某个剪点前后画面时，调用 render_timeline_view，而不是只根据文字猜测。
用户要求拼接多个素材时，调用 ffmpeg_concat_assets。
用户要求硬字幕预览或导出时，调用 ffmpeg_burn_timeline_subtitles。
所有输出文件必须来自 FFmpeg 工具返回的 output_path。
最终只输出 JSON：
{"summary":string,"operations":[],"rendered_files":[string]}
""".strip()


def create_video_agent(tools: Any) -> Any:
    return create_tool_agent(
        "video_agent",
        VIDEO_AGENT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )


def _fallback_response(error: Exception) -> dict[str, Any]:
    return {
        "summary": f"Video Agent 执行失败：{type(error).__name__}: {error}",
        "operations": [],
        "rendered_files": [],
    }


async def run_video_node(state: AgentState) -> AgentState:
    tools = toolbox(state)
    try:
        response, usage_records, tool_calls = await run_agent(
            state, "video_agent", create_video_agent(tools), tools
        )
    except Exception as exc:  # noqa: BLE001 - agent failures fall back to a structured response.
        response, usage_records, tool_calls = _fallback_response(exc), [], []

    summary = str(response.get("summary") or "Video Agent 完成。")
    rendered_files = rendered_files_from_tool_trace(tool_calls)
    outputs = dict(state.get("agent_outputs", {}))
    outputs["video_agent"] = {
        "summary": summary,
        "operations": [],
        "rendered_files": rendered_files,
        "tool_calls": tool_calls,
    }
    return {
        "agent_outputs": outputs,
        "usage_records": [*state.get("usage_records", []), *usage_records],
        "trace": trace(
            state,
            "Video Agent(create_agent) 执行完成",
            summary,
            {
                "available_tools": tools.names_for("video_agent"),
                "rendered_files": rendered_files,
                "tool_calls": tool_calls,
            },
        ),
    }
