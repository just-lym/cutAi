import asyncio
import shutil
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    AgentSession,
    Asset,
    CloudAPIUsage,
    EditPlan,
    Job,
    Project,
    ProjectStatus,
    TimelineVersion,
    empty_timeline,
)
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.tools.media_tools import cancel_media_job

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _project_storage_paths(project_id: UUID) -> tuple[Path, Path]:
    projects_root = settings.projects_root.resolve()
    project_dir = (projects_root / str(project_id)).resolve()
    staged_dir = (projects_root / f".deleting-{project_id}-{uuid4().hex}").resolve()
    if project_dir.parent != projects_root or staged_dir.parent != projects_root:
        raise HTTPException(status_code=500, detail="Invalid project storage path")
    return project_dir, staged_dir


async def _delete_project_records(db: AsyncSession, project_id: UUID) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for model in (CloudAPIUsage, AgentSession, EditPlan, Job, TimelineVersion, Asset):
        result = await db.execute(delete(model).where(model.project_id == project_id))
        deleted[model.__tablename__] = int(result.rowcount or 0)
    result = await db.execute(delete(Project).where(Project.id == project_id))
    deleted[Project.__tablename__] = int(result.rowcount or 0)
    return deleted


@router.post("", response_model=ProjectRead)
async def create_project(payload: ProjectCreate, db: DbSession) -> Project:
    project = Project(
        name=payload.name,
        video_type=payload.video_type.value,
        width=payload.width,
        height=payload.height,
        frame_rate=payload.frame_rate,
    )
    db.add(project)
    await db.flush()
    db.add(
        TimelineVersion(
            project_id=project.id,
            version=0,
            timeline_json=empty_timeline(payload.width, payload.height, payload.frame_rate),
            change_summary="Initial timeline",
            created_by="system",
        )
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
async def list_projects(db: DbSession) -> list[Project]:
    result = await db.execute(
        select(Project)
        .where(Project.status != ProjectStatus.ARCHIVED)
        .order_by(Project.updated_at.desc())
    )
    return list(result.scalars())


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: UUID, db: DbSession) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    db: DbSession,
) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Project not found")
    project.video_type = payload.video_type.value
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: UUID, db: DbSession) -> dict:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    job_result = await db.execute(select(Job.id).where(Job.project_id == project_id))
    job_ids = list(job_result.scalars())
    for job_id in job_ids:
        cancel_media_job(str(job_id))

    project_dir, staged_dir = _project_storage_paths(project_id)
    storage_staged = False
    if project_dir.exists():
        if not project_dir.is_dir():
            raise HTTPException(status_code=500, detail="Project storage path is not a directory")
        try:
            await asyncio.to_thread(project_dir.rename, staged_dir)
            storage_staged = True
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Unable to prepare project files for deletion: {exc}",
            ) from exc

    try:
        deleted = await _delete_project_records(db, project_id)
        await db.commit()
    except Exception:
        await db.rollback()
        if storage_staged and staged_dir.exists() and not project_dir.exists():
            await asyncio.to_thread(staged_dir.rename, project_dir)
        raise

    if storage_staged:
        try:
            await asyncio.to_thread(shutil.rmtree, staged_dir)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Project data was deleted, but file cleanup failed: {exc}",
            ) from exc

    return {
        "ok": True,
        "project_id": str(project_id),
        "deleted_records": deleted,
        "deleted_job_count": len(job_ids),
        "storage_deleted": not staged_dir.exists(),
    }
