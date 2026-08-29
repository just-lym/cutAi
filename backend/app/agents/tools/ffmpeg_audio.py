from pathlib import Path

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import (
    MediaToolError,
    change_media_volume,
    fade_media_audio,
    normalize_audio_loudness,
)


def build_ffmpeg_audio_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("ffmpeg_change_volume")
    async def ffmpeg_change_volume(
        volume: float,
        asset_id: str | None = None,
        output_name: str | None = None,
    ) -> dict:
        """用 ffmpeg 调整整段媒体音量并输出新文件。volume 推荐 0 到 2，最大允许 3。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"volume_{volume:.2f}_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await change_media_volume(context.asset_path(asset), output_path, volume)
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "volume": volume,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_apply_audio_fade")
    async def ffmpeg_apply_audio_fade(
        fade_type: str,
        start_ms: int,
        duration_ms: int,
        asset_id: str | None = None,
        output_name: str | None = None,
    ) -> dict:
        """用 ffmpeg 为媒体音频添加淡入或淡出。fade_type 只能是 in 或 out。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"fade_{fade_type}_{start_ms}_{duration_ms}_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await fade_media_audio(
                context.asset_path(asset),
                output_path,
                fade_type,
                start_ms,
                duration_ms,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "fade_type": fade_type,
            "start_ms": start_ms,
            "duration_ms": duration_ms,
            "output_path": str(result_path),
        }

    @tool("ffmpeg_normalize_loudness")
    async def ffmpeg_normalize_loudness(
        asset_id: str | None = None,
        output_name: str | None = None,
        target_i: float = -16.0,
        target_tp: float = -1.5,
        target_lra: float = 11.0,
    ) -> dict:
        """用 loudnorm 将音频响度规格化，适合播客、口播、短视频导出前处理。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Asset not found"}
        output_name = output_name or f"loudnorm_{asset.get('id')}.mp4"
        output_path = context.output_dir / Path(output_name).name
        try:
            result_path = await normalize_audio_loudness(
                context.asset_path(asset),
                output_path,
                target_i=target_i,
                target_tp=target_tp,
                target_lra=target_lra,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset, include_path=True)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "target_i": target_i,
            "target_tp": target_tp,
            "target_lra": target_lra,
            "output_path": str(result_path),
        }

    return [ffmpeg_change_volume, ffmpeg_apply_audio_fade, ffmpeg_normalize_loudness]
