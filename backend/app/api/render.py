import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session, get_db
from app.models import Asset, Job, JobStatus, JobType, Project
from app.schemas import JobRead, RenderPathRequest, RenderPathResponse, RenderRequest
from app.services.executor import get_latest_timeline
from app.tools.media_tools import (
    MediaToolError,
    apply_timeline_overlays,
    burn_subtitles,
    cancel_media_job,
    clear_media_job_cancel,
    mix_timeline_audio,
    probe_media,
    render_edl_ranges,
)
from app.tools.subtitle_tools import cues_to_srt
from app.ws.events import manager

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]
ACTIVE_RENDER_TASKS: dict[str, asyncio.Task[None]] = {}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _asset_path(asset: Asset) -> Path:
    path = (settings.data_root / asset.file_path).resolve()
    data_root = settings.data_root.resolve()
    if data_root not in path.parents and path != data_root:
        raise HTTPException(status_code=400, detail="Invalid asset path")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Asset file not found: {asset.id}")
    return path


def _main_ranges(timeline: dict) -> list[dict]:
    for track in timeline.get("tracks", []):
        if track.get("id") != "video-main":
            continue
        ranges = []
        for clip in sorted(track.get("clips") or [], key=lambda item: int(item.get("timeline_start_ms") or 0)):
            timeline_start_ms = int(clip.get("timeline_start_ms") or 0)
            timeline_end_ms = int(clip.get("timeline_end_ms") or timeline_start_ms)
            source_in_ms = int(clip.get("source_in_ms") or 0)
            source_out_ms = int(clip.get("source_out_ms") or source_in_ms + timeline_end_ms - timeline_start_ms)
            if clip.get("asset_id") and source_out_ms > source_in_ms:
                ranges.append(
                    {
                        "asset_id": str(clip["asset_id"]),
                        "timeline_start_ms": timeline_start_ms,
                        "timeline_end_ms": timeline_end_ms,
                        "source_in_ms": source_in_ms,
                        "source_out_ms": source_out_ms,
                    }
                )
        return ranges
    return []


def _track_clips(timeline: dict, track_id: str) -> list[dict]:
    for track in timeline.get("tracks", []):
        if track.get("id") == track_id:
            return sorted(track.get("clips") or [], key=lambda item: int(item.get("timeline_start_ms") or 0))
    return []


def _subtitle_cues(timeline: dict) -> list[dict]:
    for track in timeline.get("tracks", []):
        if track.get("id") == "subtitles":
            return list(track.get("cues") or [])
    return []


def _render_dimensions(timeline_json: dict, options: RenderRequest | None) -> tuple[int, int, float]:
    width = int(options.width if options and options.width else timeline_json.get("width") or 1920)
    height = int(options.height if options and options.height else timeline_json.get("height") or 1080)
    frame_rate = float(
        options.frame_rate if options and options.frame_rate else timeline_json.get("frame_rate") or 30.0
    )
    if width < 16 or height < 16:
        raise MediaToolError("Render width and height must be at least 16")
    if width > 7680 or height > 4320:
        raise MediaToolError("Render width/height is too large")
    if frame_rate < 1 or frame_rate > 120:
        raise MediaToolError("Render frame_rate must be between 1 and 120")
    return width, height, frame_rate


def _estimate_render_seconds(
    timeline_json: dict,
    width: int,
    height: int,
    frame_rate: float,
    overlay_count: int,
    music_clip_count: int,
    subtitle_count: int,
) -> int:
    duration_s = max(1.0, int(timeline_json.get("duration_ms") or 0) / 1000)
    pixel_factor = (width * height) / (1280 * 720)
    fps_factor = frame_rate / 30
    complexity = 1.2 + overlay_count * 0.35 + music_clip_count * 0.15 + (0.3 if subtitle_count else 0)
    return max(5, round(duration_s * pixel_factor * fps_factor * complexity * 0.35))


def _requested_output_path(default_path: Path, options: RenderRequest | None) -> Path:
    requested = (options.output_path or "").strip() if options else ""
    if not requested:
        return default_path

    raw_path = Path(requested).expanduser()
    looks_like_dir = requested.endswith(("/", "\\")) or (raw_path.exists() and raw_path.is_dir())
    if looks_like_dir:
        raw_path = raw_path / default_path.name
    elif raw_path.suffix.lower() != ".mp4":
        raw_path = raw_path.with_suffix(".mp4")

    if not raw_path.is_absolute():
        raw_path = default_path.parent / raw_path
    return raw_path.resolve()


def _planned_render_paths(
    project_id: UUID,
    job_type: JobType,
    timeline_version: int,
    options: RenderRequest | None,
) -> dict[str, str]:
    render_dir = settings.projects_root / str(project_id) / "renders"
    stem = "preview" if job_type == JobType.PREVIEW_RENDER else "final"
    default_path = render_dir / f"{stem}_v{timeline_version}_{_utc_now().strftime('%Y%m%d%H%M%S')}.mp4"
    output_path = _requested_output_path(default_path, options)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_path = output_path.with_name(f"{output_path.stem}_base{output_path.suffix}")
    overlay_path = output_path.with_name(f"{output_path.stem}_overlays{output_path.suffix}")
    audio_path = output_path.with_name(f"{output_path.stem}_mixed{output_path.suffix}")
    subtitle_path = output_path.with_name(f"{output_path.stem}.srt")
    return {
        "output_path": str(output_path),
        "base_path": str(base_path),
        "overlay_path": str(overlay_path),
        "audio_path": str(audio_path),
        "subtitle_path": str(subtitle_path),
    }


def _cleanup_partial_render_files(output: dict | None) -> None:
    if not output:
        return
    paths = [
        output.get("output_path"),
        output.get("base_path"),
        output.get("overlay_path"),
        output.get("audio_path"),
        output.get("subtitle_path"),
    ]
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(str(raw_path)).resolve()
        if path.exists() and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass

    for raw_path, suffix in (
        (output.get("base_path"), "_edl_parts"),
        (output.get("overlay_path"), "_overlay_steps"),
    ):
        if not raw_path:
            continue
        path = Path(str(raw_path)).resolve()
        temp_dir = path.parent / f"{path.stem}{suffix}"
        if temp_dir.exists() and temp_dir.is_dir():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _choose_render_output_path(default_name: str) -> str | None:
    safe_name = Path(default_name).name or "final.mp4"
    if Path(safe_name).suffix.lower() != ".mp4":
        safe_name = f"{Path(safe_name).stem}.mp4"
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise MediaToolError(f"Cannot open save dialog: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.asksaveasfilename(
            title="选择导出位置",
            defaultextension=".mp4",
            initialfile=safe_name,
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
    finally:
        root.destroy()
    return selected or None


async def _render_current_timeline(
    project_id: UUID,
    job_type: JobType,
    db: AsyncSession,
    options: RenderRequest | None,
    cancel_key: str,
    planned_paths: dict[str, str],
) -> dict:
    timeline = await get_latest_timeline(db, project_id)
    asset_result = await db.execute(select(Asset).where(Asset.project_id == project_id))
    assets = {str(asset.id): asset for asset in asset_result.scalars()}
    ranges = _main_ranges(timeline.timeline_json)
    if not ranges:
        raise MediaToolError("Timeline has no main video clips to render")

    width, height, frame_rate = _render_dimensions(timeline.timeline_json, options)
    asset_paths = {asset_id: _asset_path(asset) for asset_id, asset in assets.items()}
    output_path = Path(planned_paths["output_path"])
    base_path = Path(planned_paths["base_path"])

    rendered = await render_edl_ranges(
        ranges,
        asset_paths,
        base_path,
        width=width,
        height=height,
        frame_rate=frame_rate,
        cancel_key=cancel_key,
    )

    overlay_clips = _track_clips(timeline.timeline_json, "video-broll")
    if overlay_clips:
        overlay_path = Path(planned_paths["overlay_path"])
        rendered = await apply_timeline_overlays(
            rendered,
            overlay_clips,
            asset_paths,
            overlay_path,
            canvas_width=width,
            cancel_key=cancel_key,
        )

    music_clips = _track_clips(timeline.timeline_json, "audio-music")
    if music_clips:
        audio_path = Path(planned_paths["audio_path"])
        rendered = await mix_timeline_audio(rendered, music_clips, asset_paths, audio_path, cancel_key=cancel_key)

    subtitle_path = None
    cues = _subtitle_cues(timeline.timeline_json)
    if cues:
        subtitle_path = Path(planned_paths["subtitle_path"])
        subtitle_path.write_text(cues_to_srt(cues), encoding="utf-8")
        rendered = await burn_subtitles(rendered, subtitle_path, output_path, cancel_key=cancel_key)
    else:
        if rendered != output_path:
            rendered.replace(output_path)
            rendered = output_path

    probe = await probe_media(rendered)
    return {
        "output_path": str(rendered),
        "base_path": planned_paths["base_path"],
        "overlay_path": planned_paths["overlay_path"],
        "audio_path": planned_paths["audio_path"],
        "subtitle_path": str(subtitle_path) if subtitle_path else None,
        "timeline_version": timeline.version,
        "width": width,
        "height": height,
        "frame_rate": frame_rate,
        "range_count": len(ranges),
        "overlay_count": len(overlay_clips),
        "music_clip_count": len(music_clips),
        "duration": probe.get("format", {}).get("duration"),
        "size": probe.get("format", {}).get("size"),
    }


async def _create_render_job(
    project_id: UUID,
    job_type: JobType,
    db: AsyncSession,
    options: RenderRequest | None,
) -> Job:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    timeline = await get_latest_timeline(db, project_id)
    width, height, frame_rate = _render_dimensions(timeline.timeline_json, options)
    overlay_count = len(_track_clips(timeline.timeline_json, "video-broll"))
    music_clip_count = len(_track_clips(timeline.timeline_json, "audio-music"))
    subtitle_count = len(_subtitle_cues(timeline.timeline_json))
    estimated_seconds = _estimate_render_seconds(
        timeline.timeline_json,
        width,
        height,
        frame_rate,
        overlay_count,
        music_clip_count,
        subtitle_count,
    )
    planned_paths = _planned_render_paths(project_id, job_type, timeline.version, options)
    job = Job(
        project_id=project_id,
        type=job_type,
        status=JobStatus.RUNNING,
        progress=0.05,
        step="rendering",
        output={
            "detail": "Rendering current timeline with FFmpeg.",
            "estimated_seconds": estimated_seconds,
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "overlay_count": overlay_count,
            "music_clip_count": music_clip_count,
            "subtitle_count": subtitle_count,
            **planned_paths,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await manager.broadcast(
        str(project_id),
        "job_progress",
        {
            "job_id": job.id,
            "progress": 0.05,
            "step": "rendering",
            "estimated_seconds": estimated_seconds,
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "output_path": planned_paths["output_path"],
        },
    )
    task = asyncio.create_task(
        _run_render_job(
            job.id,
            project_id,
            job_type,
            options,
            planned_paths,
            estimated_seconds,
            _utc_now(),
        )
    )
    ACTIVE_RENDER_TASKS[str(job.id)] = task
    return job


async def _run_render_job(
    job_id: UUID,
    project_id: UUID,
    job_type: JobType,
    options: RenderRequest | None,
    planned_paths: dict[str, str],
    estimated_seconds: int,
    started_at: datetime,
) -> None:
    cancel_key = str(job_id)
    try:
        async with async_session() as db:
            output = await _render_current_timeline(project_id, job_type, db, options, cancel_key, planned_paths)
    except Exception as exc:  # noqa: BLE001 - render jobs should fail as jobs, not crash ASGI.
        async with async_session() as db:
            job = await db.get(Job, job_id)
            if job is None:
                ACTIVE_RENDER_TASKS.pop(cancel_key, None)
                clear_media_job_cancel(cancel_key)
                return
            was_cancelled = job.status == JobStatus.CANCELLED or "cancelled" in str(exc).lower()
            job.status = JobStatus.CANCELLED if was_cancelled else JobStatus.FAILED
            job.progress = 1.0
            job.step = None
            job.error = "导出已停止" if was_cancelled else str(exc.detail if isinstance(exc, HTTPException) else exc)
            job.completed_at = _utc_now()
            if was_cancelled:
                _cleanup_partial_render_files(job.output)
            await db.commit()
            await manager.broadcast(
                str(project_id),
                "job_progress",
                {"job_id": job.id, "progress": 1.0, "status": job.status.value, "error": job.error},
            )
        ACTIVE_RENDER_TASKS.pop(cancel_key, None)
        clear_media_job_cancel(cancel_key)
        return

    completed_at = _utc_now()
    async with async_session() as db:
        job = await db.get(Job, job_id)
        if job is None:
            ACTIVE_RENDER_TASKS.pop(cancel_key, None)
            clear_media_job_cancel(cancel_key)
            return
        if job.status == JobStatus.CANCELLED:
            _cleanup_partial_render_files(job.output)
            ACTIVE_RENDER_TASKS.pop(cancel_key, None)
            clear_media_job_cancel(cancel_key)
            return
        job.status = JobStatus.COMPLETED
        job.progress = 1.0
        job.step = None
        job.output = {
            **(job.output or {}),
            **output,
            "estimated_seconds": estimated_seconds,
            "actual_seconds": max(0.0, (completed_at - started_at).total_seconds()),
        }
        job.completed_at = completed_at
        await db.commit()
        await db.refresh(job)
        await manager.broadcast(
            str(project_id),
            "job_progress",
            {"job_id": job.id, "progress": 1.0, "status": "COMPLETED", "output": job.output},
        )
    ACTIVE_RENDER_TASKS.pop(cancel_key, None)
    clear_media_job_cancel(cancel_key)


@router.post("/projects/{project_id}/previews", response_model=JobRead)
async def create_preview(
    project_id: UUID,
    db: DbSession,
    payload: RenderRequest | None = None,
) -> Job:
    return await _create_render_job(project_id, JobType.PREVIEW_RENDER, db, payload)


@router.post("/projects/{project_id}/exports", response_model=JobRead)
async def create_export(
    project_id: UUID,
    db: DbSession,
    payload: RenderRequest | None = None,
) -> Job:
    return await _create_render_job(project_id, JobType.FINAL_RENDER, db, payload)


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: UUID, db: DbSession) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/render/save-path", response_model=RenderPathResponse)
async def choose_render_save_path(payload: RenderPathRequest) -> RenderPathResponse:
    try:
        path = await asyncio.to_thread(_choose_render_output_path, payload.default_name)
    except MediaToolError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RenderPathResponse(path=path)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, db: DbSession) -> dict:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.RUNNING:
        return {"ok": True, "status": job.status.value}
    stopped_process = cancel_media_job(str(job_id))
    job.status = JobStatus.CANCELLED
    job.progress = 1.0
    job.step = None
    job.error = "导出已停止"
    job.completed_at = _utc_now()
    _cleanup_partial_render_files(job.output)
    await db.commit()
    await manager.broadcast(
        str(job.project_id),
        "job_progress",
        {
            "job_id": job.id,
            "progress": 1.0,
            "status": "CANCELLED",
            "error": job.error,
        },
    )
    return {"ok": True, "status": job.status.value, "stopped_process": stopped_process}
