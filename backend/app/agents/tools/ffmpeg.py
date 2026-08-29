from pathlib import Path

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import (
    cut_media_segment,
    detect_silence,
    probe_media,
    remove_media_ranges,
)


def build_ffmpeg_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("ffmpeg_probe_asset")
    async def ffmpeg_probe_asset(asset_id: str | None = None) -> dict:
        """用 ffprobe 获取某个媒体素材的真实音视频流信息。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        probe = await probe_media(context.asset_path(asset))
        return {"ok": True, "asset": asset_summary(context, asset, include_path=True), "probe": probe}

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
        segments = await detect_silence(context.asset_path(asset), threshold_db, min_duration_ms)
        return {
            "ok": True,
            "asset": asset_summary(context, asset, include_path=True),
            "threshold_db": threshold_db,
            "min_duration_ms": min_duration_ms,
            "segments": segments,
        }

    @tool("ffmpeg_cut_segment")
    async def ffmpeg_cut_segment(
        start_ms: int,
        end_ms: int,
        asset_id: str | None = None,
        output_name: str | None = None,
    ) -> dict:
        """用 ffmpeg 截取素材片段并输出文件。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"cut_{asset.get('id')}_{start_ms}_{end_ms}.mp4"
        output_path = context.output_dir / Path(output_name).name
        result_path = await cut_media_segment(context.asset_path(asset), output_path, start_ms, end_ms)
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_remove_ranges")
    async def ffmpeg_remove_ranges(
        ranges: list[dict],
        asset_id: str | None = None,
        output_name: str | None = None,
    ) -> dict:
        """用 ffmpeg 删除多个时间区间并输出剪后文件。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        if not isinstance(ranges, list):
            return {"ok": False, "error": "ranges must be an array"}
        output_name = output_name or f"removed_ranges_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        result_path = await remove_media_ranges(
            context.asset_path(asset),
            output_path,
            ranges,
            duration_ms=context.effective_duration_ms(),
        )
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "removed_ranges": ranges,
            "output_path": str(result_path),
        }

    return [ffmpeg_probe_asset, ffmpeg_detect_silence, ffmpeg_cut_segment, ffmpeg_remove_ranges]
