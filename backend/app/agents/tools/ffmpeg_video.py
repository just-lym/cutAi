from pathlib import Path

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import (
    MediaToolError,
    concatenate_media,
    crop_scale_media,
    cut_media_segment,
    detect_scene_changes,
    overlay_media,
    remove_media_ranges,
    transcode_media,
)


def build_ffmpeg_video_tools(context: AgentToolContext) -> list[AgentTool]:
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
        try:
            result_path = await cut_media_segment(context.asset_path(asset), output_path, start_ms, end_ms)
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
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
        try:
            result_path = await remove_media_ranges(
                context.asset_path(asset),
                output_path,
                ranges,
                duration_ms=context.effective_duration_ms(),
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "removed_ranges": ranges,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_transcode_preview")
    async def ffmpeg_transcode_preview(
        asset_id: str | None = None,
        output_name: str | None = None,
        width: int = 1280,
        start_ms: int | None = None,
        duration_ms: int | None = None,
        crf: int = 23,
    ) -> dict:
        """用 ffmpeg 转码生成浏览器友好的预览文件，可限制起点、时长、宽度和 CRF。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"preview_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await transcode_media(
                context.asset_path(asset),
                output_path,
                width=width,
                start_ms=start_ms,
                duration_ms=duration_ms,
                crf=crf,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "output_path": str(result_path),
            "width": width,
            "start_ms": start_ms,
            "duration_ms": duration_ms,
        }

    @tool("ffmpeg_crop_scale")
    async def ffmpeg_crop_scale(
        width: int,
        height: int,
        asset_id: str | None = None,
        output_name: str | None = None,
        crop_x: int | None = None,
        crop_y: int | None = None,
        crop_width: int | None = None,
        crop_height: int | None = None,
        fit: str = "cover",
        crf: int = 22,
    ) -> dict:
        """裁剪/缩放/补边生成指定尺寸视频，适合横转竖、方形画幅和平台预设。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"crop_scale_{width}x{height}_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await crop_scale_media(
                context.asset_path(asset),
                output_path,
                width,
                height,
                crop_x=crop_x,
                crop_y=crop_y,
                crop_width=crop_width,
                crop_height=crop_height,
                fit=fit,
                crf=crf,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "width": width,
            "height": height,
            "fit": fit,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_overlay_asset")
    async def ffmpeg_overlay_asset(
        overlay_asset_id: str,
        position_ms: int,
        duration_ms: int,
        base_asset_id: str | None = None,
        output_name: str | None = None,
        x: int = 0,
        y: int = 0,
        overlay_width: int = 480,
    ) -> dict:
        """用 ffmpeg 把一个视频/图片素材覆盖到主视频上并输出预览文件。"""
        base_asset = context.find_asset(base_asset_id, media_only=True)
        overlay_asset = context.find_asset(overlay_asset_id, media_only=False)
        if base_asset is None:
            return {"ok": False, "error": "Base media asset not found"}
        if overlay_asset is None:
            return {"ok": False, "error": "Overlay asset not found"}
        output_name = output_name or f"overlay_{base_asset.get('id')}_{overlay_asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await overlay_media(
                context.asset_path(base_asset),
                context.asset_path(overlay_asset),
                output_path,
                position_ms,
                duration_ms,
                x=x,
                y=y,
                overlay_width=overlay_width,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, base_asset, include_path=True)}
        return {
            "ok": True,
            "base_asset": asset_summary(context, base_asset),
            "overlay_asset": asset_summary(context, overlay_asset),
            "position_ms": position_ms,
            "duration_ms": duration_ms,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_concat_assets")
    async def ffmpeg_concat_assets(
        asset_ids: list[str],
        output_name: str | None = None,
    ) -> dict:
        """按给定 asset_ids 顺序拼接多个媒体文件并输出新文件。素材编码不兼容时可能失败。"""
        if not isinstance(asset_ids, list) or len(asset_ids) < 2:
            return {"ok": False, "error": "asset_ids must include at least two assets"}
        assets = [context.find_asset(asset_id, media_only=True) for asset_id in asset_ids]
        missing = [asset_id for asset_id, asset in zip(asset_ids, assets, strict=False) if asset is None]
        if missing:
            return {"ok": False, "error": "Some assets were not found", "missing_asset_ids": missing}
        output_name = output_name or "concat_assets.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await concatenate_media([context.asset_path(asset) for asset in assets if asset], output_path)
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "assets": [asset_summary(context, asset) for asset in assets if asset]}
        return {
            "ok": True,
            "assets": [asset_summary(context, asset) for asset in assets if asset],
            "output_path": str(result_path),
        }

    @tool("ffmpeg_detect_scene_changes")
    async def ffmpeg_detect_scene_changes(
        asset_id: str | None = None,
        threshold: float = 0.35,
        min_gap_ms: int = 500,
    ) -> dict:
        """检测镜头/画面变化点，适合粗剪、自动找转场点和素材巡检。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        try:
            scenes = await detect_scene_changes(context.asset_path(asset), threshold, min_gap_ms)
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "threshold": threshold,
            "scene_count": len(scenes),
            "scenes": scenes,
        }

    return [
        ffmpeg_cut_segment,
        ffmpeg_remove_ranges,
        ffmpeg_transcode_preview,
        ffmpeg_crop_scale,
        ffmpeg_overlay_asset,
        ffmpeg_concat_assets,
        ffmpeg_detect_scene_changes,
    ]
