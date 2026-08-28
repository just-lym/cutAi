from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, TimelineVersion
from app.schemas import TimelineCommit, TimelineRead
from app.services.executor import ExecutionError, execute_edit_plan, get_latest_timeline
from app.ws.events import manager

router = APIRouter()


def timeline_read(timeline: TimelineVersion) -> TimelineRead:
    return TimelineRead(
        id=timeline.id,
        project_id=timeline.project_id,
        version=timeline.version,
        parent_version_id=timeline.parent_version_id,
        timeline_json=timeline.timeline_json,
        change_summary=timeline.change_summary,
        created_by=timeline.created_by,
    )


@router.get("/projects/{project_id}/timeline", response_model=TimelineRead)
async def get_timeline(project_id: UUID, db: AsyncSession = Depends(get_db)) -> TimelineRead:
    try:
        return timeline_read(await get_latest_timeline(db, project_id))
    except ExecutionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/timeline/commit", response_model=TimelineRead)
async def commit_timeline(
    project_id: UUID,
    payload: TimelineCommit,
    db: AsyncSession = Depends(get_db),
) -> TimelineRead:
    try:
        timeline = await execute_edit_plan(
            db,
            project_id,
            payload.operations,
            created_by="user",
            change_summary=payload.change_summary,
        )
        await db.commit()
        await manager.broadcast(
            str(project_id),
            "timeline_updated",
            {"version": timeline.version, "timeline_version_id": timeline.id},
        )
        return timeline_read(timeline)
    except ExecutionError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/timeline/versions", response_model=list[TimelineRead])
async def list_versions(project_id: UUID, db: AsyncSession = Depends(get_db)) -> list[TimelineRead]:
    result = await db.execute(
        select(TimelineVersion)
        .where(TimelineVersion.project_id == project_id)
        .order_by(TimelineVersion.version.desc())
    )
    return [timeline_read(item) for item in result.scalars()]


@router.post("/projects/{project_id}/timeline/restore/{version}", response_model=TimelineRead)
async def restore_version(
    project_id: UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
) -> TimelineRead:
    result = await db.execute(
        select(TimelineVersion)
        .where(TimelineVersion.project_id == project_id, TimelineVersion.version == version)
        .limit(1)
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Timeline version not found")
    current = await get_latest_timeline(db, project_id)
    restored = TimelineVersion(
        project_id=project_id,
        version=current.version + 1,
        parent_version_id=current.id,
        timeline_json=target.timeline_json,
        change_summary=f"Restored version {version}",
        created_by="user",
    )
    db.add(restored)
    project = await db.get(Project, project_id)
    if project is not None:
        project.current_timeline_version = restored.version
        project.duration_ms = int(restored.timeline_json.get("duration_ms", 0))
    await db.commit()
    await manager.broadcast(str(project_id), "timeline_updated", {"version": restored.version})
    return timeline_read(restored)
