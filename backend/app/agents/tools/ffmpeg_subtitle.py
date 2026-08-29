from pathlib import Path

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import MediaToolError, burn_subtitles
from app.tools.subtitle_tools import cues_to_srt


def build_ffmpeg_subtitle_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("ffmpeg_burn_timeline_subtitles")
    async def ffmpeg_burn_timeline_subtitles(
        asset_id: str | None = None,
        output_name: str | None = None,
        font_size: int = 24,
    ) -> dict:
        """把当前时间线字幕轨烧录到视频文件，适合生成带硬字幕预览或交付文件。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        cues = context.subtitle_cues()
        if not cues:
            return {"ok": False, "error": "No timeline subtitles are available"}

        subtitle_path = context.output_dir / "timeline_subtitles.srt"
        subtitle_path.write_text(cues_to_srt(cues), encoding="utf-8")
        output_name = output_name or f"burn_subtitles_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await burn_subtitles(
                context.asset_path(asset),
                subtitle_path,
                output_path,
                font_size=font_size,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "subtitle_count": len(cues),
            "subtitle_path": str(subtitle_path),
            "output_path": str(result_path),
        }

    return [ffmpeg_burn_timeline_subtitles]
