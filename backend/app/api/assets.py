import hashlib
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from uuid import UUID

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Asset, AssetType, ProcessingStatus, Project, TimelineVersion
from app.schemas import AssetRead
from app.services.executor import get_latest_timeline
from app.tools.media_tools import (
    duration_ms_from_probe,
    generate_browser_proxy,
    probe_media,
    video_info_from_probe,
)
from app.tools.subtitle_tools import parse_srt
from app.ws.events import manager

router = APIRouter()


EXTENSION_TYPES = {
    ".mp4": AssetType.VIDEO,
    ".mov": AssetType.VIDEO,
    ".webm": AssetType.VIDEO,
    ".m4v": AssetType.VIDEO,
    ".mp3": AssetType.AUDIO,
    ".wav": AssetType.AUDIO,
    ".m4a": AssetType.AUDIO,
    ".flac": AssetType.AUDIO,
    ".png": AssetType.IMAGE,
    ".jpg": AssetType.IMAGE,
    ".jpeg": AssetType.IMAGE,
    ".webp": AssetType.IMAGE,
    ".srt": AssetType.SUBTITLE,
    ".vtt": AssetType.SUBTITLE,
    ".txt": AssetType.TRANSCRIPT,
}


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "asset"
    return f"{stem[:80]}{ext}"


def _relative_to_data_root(path: Path) -> str:
    return path.relative_to(settings.data_root).as_posix()


def _asset_abs_path(asset: Asset, prefer_proxy: bool = False) -> Path:
    rel_path = asset.proxy_path if prefer_proxy and asset.proxy_path else asset.file_path
    candidate = (settings.data_root / rel_path).resolve()
    data_root = settings.data_root.resolve()
    if data_root not in candidate.parents and candidate != data_root:
        raise HTTPException(status_code=400, detail="Invalid asset path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Asset file not found")
    return candidate


async def _add_asset_to_timeline(db: AsyncSession, project: Project, asset: Asset, cues: list[dict] | None) -> None:
    latest = await get_latest_timeline(db, project.id)
    timeline = dict(latest.timeline_json)
    tracks = timeline["tracks"]

    if asset.type == AssetType.VIDEO:
        duration = asset.duration_ms or 10000
        for track_id in ("video-main", "audio-original"):
            track = next(item for item in tracks if item["id"] == track_id)
            if track["clips"]:
                continue
            track["clips"].append(
                {
                    "id": str(uuid.uuid4()),
                    "asset_id": str(asset.id),
                    "timeline_start_ms": 0,
                    "timeline_end_ms": duration,
                    "source_in_ms": 0,
                    "source_out_ms": duration,
                    "speed": 1.0,
                    "volume": 1.0 if track_id == "audio-original" else 0.0,
                }
            )
        timeline["duration_ms"] = max(int(timeline.get("duration_ms", 0)), duration)

    if asset.type == AssetType.AUDIO:
        duration = asset.duration_ms or 10000
        track = next(item for item in tracks if item["id"] == "audio-music")
        track["clips"].append(
            {
                "id": str(uuid.uuid4()),
                "asset_id": str(asset.id),
                "timeline_start_ms": 0,
                "timeline_end_ms": duration,
                "source_in_ms": 0,
                "source_out_ms": duration,
                "speed": 1.0,
                "volume": 0.7,
            }
        )
        timeline["duration_ms"] = max(int(timeline.get("duration_ms", 0)), duration)

    if cues:
        track = next(item for item in tracks if item["id"] == "subtitles")
        track["cues"] = cues
        timeline["duration_ms"] = max(
            int(timeline.get("duration_ms", 0)),
            max((cue["end_ms"] for cue in cues), default=0),
        )

    next_version = TimelineVersion(
        project_id=project.id,
        version=latest.version + 1,
        parent_version_id=latest.id,
        timeline_json=timeline,
        change_summary=f"Imported asset {asset.original_name}",
        created_by="system",
    )
    db.add(next_version)
    project.current_timeline_version = next_version.version
    project.duration_ms = int(timeline.get("duration_ms", 0))


async def _process_metadata(path: Path, asset: Asset) -> list[dict] | None:
    asset.processing_status = ProcessingStatus.PROCESSING
    asset.processing_step = "probe"
    cues = None
    try:
        if asset.type in {AssetType.VIDEO, AssetType.AUDIO}:
            probe = await probe_media(path)
            asset.duration_ms = duration_ms_from_probe(probe)
            width, height, frame_rate = video_info_from_probe(probe)
            asset.width = width
            asset.height = height
            asset.frame_rate = frame_rate
            asset.metadata_ = {"probe": probe}
            if asset.type == AssetType.VIDEO:
                asset.processing_step = "proxy"
                proxy_path = (
                    settings.projects_root
                    / str(asset.project_id)
                    / "proxies"
                    / f"{path.stem}_h264.mp4"
                )
                await generate_browser_proxy(path, proxy_path)
                asset.proxy_path = _relative_to_data_root(proxy_path)
        elif asset.type == AssetType.SUBTITLE:
            cues = parse_srt(path.read_text(encoding="utf-8"))
        asset.processing_status = ProcessingStatus.COMPLETED
        asset.processing_step = None
        asset.processing_error = None
    except Exception as exc:
        asset.processing_status = ProcessingStatus.FAILED
        asset.processing_step = None
        asset.processing_error = f"{type(exc).__name__}: {exc}"
    return cues


@router.post("/projects/{project_id}/assets/upload", response_model=AssetRead)
async def upload_asset(
    project_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> Asset:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    safe_name = _safe_name(file.filename or "asset")
    ext = Path(safe_name).suffix.lower()
    asset_type = EXTENSION_TYPES.get(ext, AssetType.OTHER)
    project_dir = settings.projects_root / str(project_id)
    originals_dir = project_dir / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)
    dest = originals_dir / f"{uuid.uuid4()}_{safe_name}"

    sha256 = hashlib.sha256()
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            sha256.update(chunk)
            await out.write(chunk)

    asset = Asset(
        project_id=project_id,
        type=asset_type,
        original_name=safe_name,
        file_path=_relative_to_data_root(dest),
        mime_type=file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
        checksum=sha256.hexdigest(),
    )
    db.add(asset)
    await db.flush()
    cues = await _process_metadata(dest, asset)
    await _add_asset_to_timeline(db, project, asset, cues)
    await db.commit()
    await db.refresh(asset)
    await manager.broadcast(
        str(project_id),
        "job_progress",
        {"asset_id": asset.id, "step": asset.processing_step, "progress": 1.0},
    )
    return asset


@router.post("/projects/{project_id}/assets/import", response_model=AssetRead)
async def import_asset(project_id: UUID, path: str, db: AsyncSession = Depends(get_db)) -> Asset:
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=400, detail="Source file does not exist")
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project_dir = settings.projects_root / str(project_id) / "originals"
    project_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_name(source.name)
    dest = project_dir / f"{uuid.uuid4()}_{safe_name}"
    shutil.copyfile(source, dest)
    with dest.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    asset = Asset(
        project_id=project_id,
        type=EXTENSION_TYPES.get(dest.suffix.lower(), AssetType.OTHER),
        original_name=safe_name,
        file_path=_relative_to_data_root(dest),
        mime_type=mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
        checksum=checksum,
    )
    db.add(asset)
    await db.flush()
    cues = await _process_metadata(dest, asset)
    await _add_asset_to_timeline(db, project, asset, cues)
    await db.commit()
    await db.refresh(asset)
    return asset


@router.get("/projects/{project_id}/assets", response_model=list[AssetRead])
async def list_assets(project_id: UUID, db: AsyncSession = Depends(get_db)) -> list[Asset]:
    result = await db.execute(select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at.desc()))
    return list(result.scalars())


@router.get("/assets/{asset_id}/status", response_model=AssetRead)
async def asset_status(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> Asset:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.post("/assets/{asset_id}/reprocess", response_model=AssetRead)
async def reprocess_asset(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> Asset:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    path = _asset_abs_path(asset)
    await _process_metadata(path, asset)
    await db.commit()
    await db.refresh(asset)
    await manager.broadcast(
        str(asset.project_id),
        "job_progress",
        {"asset_id": asset.id, "step": asset.processing_step, "progress": 1.0},
    )
    return asset


@router.get("/assets/{asset_id}/file")
async def asset_file(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    path = _asset_abs_path(asset)
    return FileResponse(path, media_type=asset.mime_type)


@router.get("/assets/{asset_id}/proxy")
async def asset_proxy(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    path = _asset_abs_path(asset, prefer_proxy=True)
    return FileResponse(path, media_type="video/mp4")
