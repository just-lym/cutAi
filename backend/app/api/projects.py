from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, ProjectStatus, TimelineVersion, empty_timeline
from app.schemas import ProjectCreate, ProjectRead

router = APIRouter()


@router.post("", response_model=ProjectRead)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    project = Project(
        name=payload.name,
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
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    result = await db.execute(
        select(Project)
        .where(Project.status != ProjectStatus.ARCHIVED)
        .order_by(Project.updated_at.desc())
    )
    return list(result.scalars())


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db)) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
async def archive_project(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project.status = ProjectStatus.ARCHIVED
    await db.commit()
    return {"ok": True}
