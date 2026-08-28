import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TimelineVersion
from app.schemas import SubtitleUpdate
from app.services.executor import ExecutionError, execute_edit_plan, get_latest_timeline
from app.ws.events import manager

router = APIRouter()


def _subtitle_track(timeline: dict) -> dict:
    for track in timeline.get("tracks", []):
        if track.get("id") == "subtitles":
            return track
    raise HTTPException(status_code=404, detail="Subtitle track not found")


@router.get("/projects/{project_id}/subtitles")
async def list_subtitles(project_id: UUID, db: AsyncSession = Depends(get_db)) -> list[dict]:
    timeline = await get_latest_timeline(db, project_id)
    cues = _subtitle_track(timeline.timeline_json).get("cues", [])
    return sorted(cues, key=lambda cue: cue.get("start_ms", 0))


@router.put("/projects/{project_id}/subtitles/{cue_id}")
async def update_subtitle(
    project_id: UUID,
    cue_id: str,
    payload: SubtitleUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    operation = {"type": "UPDATE_SUBTITLE", "cue_id": cue_id}
    operation.update(payload.model_dump(exclude_none=True))
    try:
        timeline = await execute_edit_plan(
            db,
            project_id,
            [operation],
            created_by="user",
            change_summary="Updated subtitle",
        )
        await db.commit()
        await manager.broadcast(str(project_id), "timeline_updated", {"version": timeline.version})
        return {"ok": True, "version": timeline.version}
    except ExecutionError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/subtitles/{cue_id}")
async def delete_subtitle(
    project_id: UUID,
    cue_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    current = await get_latest_timeline(db, project_id)
    timeline = dict(current.timeline_json)
    track = _subtitle_track(timeline)
    before = len(track.get("cues", []))
    track["cues"] = [cue for cue in track.get("cues", []) if cue.get("id") != cue_id]
    if len(track["cues"]) == before:
        raise HTTPException(status_code=404, detail="Subtitle cue not found")
    next_version = TimelineVersion(
        id=uuid.uuid4(),
        project_id=project_id,
        version=current.version + 1,
        parent_version_id=current.id,
        timeline_json=timeline,
        change_summary="Deleted subtitle",
        created_by="user",
    )
    db.add(next_version)
    await db.commit()
    await manager.broadcast(str(project_id), "timeline_updated", {"version": next_version.version})
    return {"ok": True, "version": next_version.version}
