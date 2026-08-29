import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool
from app.tools.media_tools import MediaToolError, burn_subtitles, probe_media, render_edl_ranges
from app.tools.subtitle_tools import cues_to_srt


def _edit_dir(context: AgentToolContext) -> Path:
    path = Path(context.project_dir) / "edit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _main_video_clips(context: AgentToolContext) -> list[dict[str, Any]]:
    for track in context.tracks():
        if track.get("id") == "video-main":
            return list(track.get("clips") or [])
    return []


def _timeline_ranges_from_clips(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges = []
    for clip in sorted(clips, key=lambda item: int(item.get("timeline_start_ms") or 0)):
        timeline_start_ms = int(clip.get("timeline_start_ms") or 0)
        timeline_end_ms = int(clip.get("timeline_end_ms") or timeline_start_ms)
        source_in_ms = int(clip.get("source_in_ms") or 0)
        source_out_ms = int(clip.get("source_out_ms") or source_in_ms + timeline_end_ms - timeline_start_ms)
        if timeline_end_ms <= timeline_start_ms or source_out_ms <= source_in_ms:
            continue
        ranges.append(
            {
                "clip_id": clip.get("id"),
                "asset_id": clip.get("asset_id"),
                "timeline_start_ms": timeline_start_ms,
                "timeline_end_ms": timeline_end_ms,
                "source_in_ms": source_in_ms,
                "source_out_ms": source_out_ms,
            }
        )
    return ranges


def _cue_overlaps_range(cue: dict[str, Any], start_ms: int, end_ms: int) -> bool:
    return int(cue.get("start_ms") or 0) < end_ms and start_ms < int(cue.get("end_ms") or 0)


def _master_cues_for_ranges(context: AgentToolContext, ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cues = context.subtitle_cues()
    output_cues: list[dict[str, Any]] = []
    output_cursor = 0
    for item in ranges:
        timeline_start_ms = int(item.get("timeline_start_ms") or 0)
        timeline_end_ms = int(item.get("timeline_end_ms") or timeline_start_ms)
        duration_ms = timeline_end_ms - timeline_start_ms
        for cue in cues:
            if not _cue_overlaps_range(cue, timeline_start_ms, timeline_end_ms):
                continue
            cue_start = max(int(cue.get("start_ms") or 0), timeline_start_ms)
            cue_end = min(int(cue.get("end_ms") or 0), timeline_end_ms)
            if cue_end <= cue_start:
                continue
            next_cue = dict(cue)
            next_cue["start_ms"] = output_cursor + (cue_start - timeline_start_ms)
            next_cue["end_ms"] = output_cursor + (cue_end - timeline_start_ms)
            output_cues.append(next_cue)
        output_cursor += duration_ms
    return output_cues


def _validate_edl(context: AgentToolContext, edl: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    assets_by_id = {str(asset.get("id")): asset for asset in context.assets}
    ranges = edl.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        errors.append("EDL requires a non-empty ranges array")
        return errors, warnings

    for index, item in enumerate(ranges):
        if not isinstance(item, dict):
            errors.append(f"ranges[{index}] must be an object")
            continue
        asset_id = str(item.get("asset_id") or "")
        asset = assets_by_id.get(asset_id)
        if asset is None:
            errors.append(f"ranges[{index}] references unknown asset_id: {asset_id}")
            continue
        source_in_ms = int(item.get("source_in_ms") or item.get("start_ms") or 0)
        source_out_ms = int(item.get("source_out_ms") or item.get("end_ms") or 0)
        if source_out_ms <= source_in_ms:
            errors.append(f"ranges[{index}] requires source_in_ms < source_out_ms")
        duration_ms = int(asset.get("duration_ms") or 0)
        if duration_ms and source_out_ms > duration_ms:
            errors.append(f"ranges[{index}] exceeds asset duration")

        timeline_start_ms = int(item.get("timeline_start_ms") or source_in_ms)
        timeline_end_ms = int(item.get("timeline_end_ms") or source_out_ms)
        for cue in context.subtitle_cues():
            cue_start = int(cue.get("start_ms") or 0)
            cue_end = int(cue.get("end_ms") or 0)
            if cue_start < timeline_start_ms < cue_end or cue_start < timeline_end_ms < cue_end:
                warnings.append(f"ranges[{index}] boundary cuts through subtitle cue {cue.get('id')}")
                break
    return errors, warnings


def _load_edl(context: AgentToolContext, edl_path: str | None, edl: dict[str, Any] | None) -> dict[str, Any]:
    if edl is not None:
        return edl
    if not edl_path:
        default_path = _edit_dir(context) / "edl.json"
        if not default_path.exists():
            raise FileNotFoundError("edl_path is required because edit/edl.json does not exist")
        edl_path = str(default_path)
    path = Path(edl_path)
    return json.loads(path.read_text(encoding="utf-8"))


def build_edl_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("build_timeline_edl")
    async def build_timeline_edl(output_name: str = "edl.json") -> dict:
        """把当前主视频时间线转换成 EDL artifact，作为 Agent 创作和渲染的可验证中间产物。"""
        ranges = _timeline_ranges_from_clips(_main_video_clips(context))
        edl = {
            "version": 1,
            "project_id": context.project_id,
            "base_timeline_version": context.timeline_version,
            "width": int(context.timeline.get("width") or 1920),
            "height": int(context.timeline.get("height") or 1080),
            "frame_rate": float(context.timeline.get("frame_rate") or 30.0),
            "ranges": ranges,
            "subtitles": {
                "mode": "timeline",
                "cue_count": len(context.subtitle_cues()),
                "apply_last": True,
            },
            "render_rules": {
                "extract_segments_first": True,
                "audio_fade_ms_at_cuts": 30,
                "subtitles_last": True,
                "master_srt_uses_output_offsets": True,
            },
        }
        errors, warnings = _validate_edl(context, edl)
        path = _edit_dir(context) / Path(output_name).name
        path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": not errors,
            "artifact_type": "edl",
            "artifact_path": str(path),
            "edl_path": str(path),
            "range_count": len(ranges),
            "errors": errors,
            "warnings": warnings,
            "edl": edl,
        }

    @tool("validate_edl")
    async def validate_edl(edl_path: str | None = None, edl: dict | None = None) -> dict:
        """校验候选 EDL 是否能被当前项目执行，并提醒是否切穿字幕 cue。"""
        try:
            loaded = _load_edl(context, edl_path, edl)
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"], "warnings": []}
        errors, warnings = _validate_edl(context, loaded)
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "range_count": len(loaded.get("ranges") or []),
        }

    @tool("render_edl_preview")
    async def render_edl_preview(
        edl_path: str | None = None,
        edl: dict | None = None,
        output_name: str = "preview.mp4",
        burn_timeline_subtitles: bool = True,
    ) -> dict:
        """按 EDL 渲染浏览器可播放预览。先分段抽取加切点淡化，再 concat，字幕最后应用。"""
        try:
            loaded = _load_edl(context, edl_path, edl)
            errors, warnings = _validate_edl(context, loaded)
            if errors:
                return {"ok": False, "errors": errors, "warnings": warnings}

            assets_by_id = {str(asset.get("id")): asset for asset in context.assets}
            asset_paths = {
                asset_id: context.asset_path(asset)
                for asset_id, asset in assets_by_id.items()
                if asset.get("type") in {"VIDEO", "AUDIO"}
            }
            output_path = _edit_dir(context) / Path(output_name).name
            working_path = output_path
            if burn_timeline_subtitles and context.subtitle_cues():
                working_path = output_path.with_name(f"{output_path.stem}_nosubs{output_path.suffix}")

            rendered = await render_edl_ranges(
                loaded["ranges"],
                asset_paths,
                working_path,
                width=int(loaded.get("width") or context.timeline.get("width") or 1920),
                height=int(loaded.get("height") or context.timeline.get("height") or 1080),
                audio_fade_ms=int(loaded.get("render_rules", {}).get("audio_fade_ms_at_cuts") or 30),
            )

            subtitle_path = None
            if burn_timeline_subtitles and context.subtitle_cues():
                master_cues = _master_cues_for_ranges(context, loaded["ranges"])
                subtitle_path = _edit_dir(context) / "master.srt"
                subtitle_path.write_text(cues_to_srt(master_cues), encoding="utf-8")
                rendered = await burn_subtitles(rendered, subtitle_path, output_path)
                working_path.unlink(missing_ok=True)

            probe = await probe_media(rendered)
        except (FileNotFoundError, MediaToolError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"], "warnings": []}

        return {
            "ok": True,
            "artifact_type": "render_preview",
            "output_path": str(rendered),
            "preview_path": str(rendered),
            "subtitle_path": str(subtitle_path) if subtitle_path else None,
            "range_count": len(loaded.get("ranges") or []),
            "warnings": warnings,
            "probe": {
                "duration": probe.get("format", {}).get("duration"),
                "size": probe.get("format", {}).get("size"),
                "format_name": probe.get("format", {}).get("format_name"),
            },
        }

    @tool("summarize_edl_sources")
    async def summarize_edl_sources(edl_path: str | None = None, edl: dict | None = None) -> dict:
        """概览 EDL 使用了哪些素材和总输出时长，适合 Main Agent 在执行前解释创作方案。"""
        try:
            loaded = _load_edl(context, edl_path, edl)
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        assets_by_id = {str(asset.get("id")): asset for asset in context.assets}
        total_ms = 0
        sources: dict[str, dict[str, Any]] = {}
        for item in loaded.get("ranges") or []:
            asset_id = str(item.get("asset_id") or "")
            duration_ms = int(item.get("source_out_ms") or 0) - int(item.get("source_in_ms") or 0)
            total_ms += max(0, duration_ms)
            if asset_id in sources:
                sources[asset_id]["used_ms"] += max(0, duration_ms)
            elif asset_id in assets_by_id:
                sources[asset_id] = {
                    **asset_summary(context, assets_by_id[asset_id]),
                    "used_ms": max(0, duration_ms),
                }
        return {
            "ok": True,
            "range_count": len(loaded.get("ranges") or []),
            "estimated_output_duration_ms": total_ms,
            "sources": list(sources.values()),
        }

    return [build_timeline_edl, validate_edl, render_edl_preview, summarize_edl_sources]
