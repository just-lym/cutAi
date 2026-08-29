from pathlib import Path

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import (
    MediaToolError,
    check_media_tool,
    extract_frame,
    extract_thumbnail_sequence,
    media_tool_version,
    probe_media,
)


def build_ffmpeg_media_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("ffmpeg_check_available")
    async def ffmpeg_check_available() -> dict:
        """检查 ffmpeg 和 ffprobe 是否可用。导出、转码或媒体分析前可以调用。"""
        try:
            return {
                "ok": True,
                "ffmpeg": await check_media_tool("ffmpeg"),
                "ffprobe": await check_media_tool("ffprobe"),
            }
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc)}

    @tool("ffmpeg_get_version")
    async def ffmpeg_get_version(tool_name: str = "ffmpeg") -> dict:
        """读取 ffmpeg 或 ffprobe 版本，tool_name 只能是 ffmpeg 或 ffprobe。"""
        try:
            return {"ok": True, "tool": tool_name, "version": await media_tool_version(tool_name)}
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "tool": tool_name}

    @tool("ffmpeg_probe_asset")
    async def ffmpeg_probe_asset(asset_id: str | None = None) -> dict:
        """用 ffprobe 获取某个媒体素材的真实音视频流信息。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        try:
            probe = await probe_media(context.asset_path(asset))
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {"ok": True, "asset": asset_summary(context, asset, include_path=True), "probe": probe}

    @tool("ffmpeg_extract_frame")
    async def ffmpeg_extract_frame(
        at_ms: int = 0,
        asset_id: str | None = None,
        output_name: str | None = None,
        width: int | None = None,
    ) -> dict:
        """用 ffmpeg 从视频素材抽取单帧图片，适合生成封面、检查画面或做预览。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"frame_{asset.get('id')}_{at_ms}.jpg"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await extract_frame(context.asset_path(asset), output_path, at_ms, width)
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "at_ms": at_ms,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_extract_thumbnails")
    async def ffmpeg_extract_thumbnails(
        asset_id: str | None = None,
        every_ms: int = 1000,
        width: int = 240,
        limit: int = 60,
    ) -> dict:
        """按固定间隔抽取缩略图序列，适合让 Agent 快速巡检画面和镜头节奏。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_dir = context.output_dir / f"thumbs_{asset.get('id')}"
        try:
            paths = await extract_thumbnail_sequence(
                context.asset_path(asset),
                output_dir,
                every_ms=every_ms,
                width=width,
                limit=limit,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "thumbnail_count": len(paths),
            "output_paths": [str(path) for path in paths],
        }

    return [
        ffmpeg_check_available,
        ffmpeg_get_version,
        ffmpeg_probe_asset,
        ffmpeg_extract_frame,
        ffmpeg_extract_thumbnails,
    ]
