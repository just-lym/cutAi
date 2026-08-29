from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import MediaToolError, render_timeline_contact_sheet


def _edit_dir(context: AgentToolContext) -> Path:
    path = Path(context.project_dir) / "edit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _nearby_cues(context: AgentToolContext, start_ms: int, end_ms: int, limit: int = 20) -> list[dict[str, Any]]:
    cues = []
    for cue in context.subtitle_cues():
        cue_start = int(cue.get("start_ms") or 0)
        cue_end = int(cue.get("end_ms") or 0)
        if cue_start < end_ms and start_ms < cue_end:
            cues.append(
                {
                    "id": cue.get("id"),
                    "start_ms": cue_start,
                    "end_ms": cue_end,
                    "text": str(cue.get("text") or "")[:240],
                    "speaker": cue.get("speaker"),
                }
            )
    return cues[:limit]


def build_inspection_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("render_timeline_view")
    async def render_timeline_view(
        start_ms: int,
        end_ms: int,
        asset_id: str | None = None,
        frames: int = 8,
        frame_width: int = 180,
        output_name: str | None = None,
    ) -> dict:
        """生成某段素材的轻量视觉巡检图，并返回该时间段字幕上下文。适合 Agent 在关键剪点前后确认画面。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        if end_ms <= start_ms:
            return {"ok": False, "error": "end_ms must be greater than start_ms"}
        output_name = output_name or f"timeline_view_{asset.get('id')}_{start_ms}_{end_ms}.jpg"
        output_path = _edit_dir(context) / Path(output_name).name
        try:
            result_path = await render_timeline_contact_sheet(
                context.asset_path(asset),
                output_path,
                start_ms=start_ms,
                end_ms=end_ms,
                frames=max(1, min(24, int(frames))),
                frame_width=max(16, min(640, int(frame_width))),
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "artifact_type": "timeline_view",
            "asset": asset_summary(context, asset),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "contact_sheet_path": str(result_path),
            "output_path": str(result_path),
            "nearby_cues": _nearby_cues(context, start_ms, end_ms),
            "note": "This is a visual drilldown artifact; use transcript and ffmpeg analysis for audio decisions.",
        }

    return [render_timeline_view]
