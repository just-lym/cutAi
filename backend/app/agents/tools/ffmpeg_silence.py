from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import MediaToolError, detect_silence


def build_ffmpeg_silence_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("ffmpeg_detect_silence")
    async def ffmpeg_detect_silence(
        asset_id: str | None = None,
        threshold_db: float = -40,
        min_duration_ms: int = 500,
    ) -> dict:
        """用 ffmpeg silencedetect 检测媒体素材中的静音段。DELETE_RANGE 必须基于本工具结果。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "No completed VIDEO/AUDIO asset is available"}
        try:
            segments = await detect_silence(context.asset_path(asset), threshold_db, min_duration_ms)
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset, include_path=True),
            "threshold_db": threshold_db,
            "min_duration_ms": min_duration_ms,
            "segments": segments,
        }

    return [ffmpeg_detect_silence]
