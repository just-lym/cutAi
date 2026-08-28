from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Job, JobStatus, JobType, Project
from app.schemas import JobRead
from app.ws.events import manager

router = APIRouter()


async def _create_render_job(project_id: UUID, job_type: JobType, db: AsyncSession) -> Job:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    job = Job(
        project_id=project_id,
        type=job_type,
        status=JobStatus.COMPLETED,
        progress=1.0,
        output={"detail": "MVP render job created. Wire app.tools.render_tools for real export."},
        completed_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await manager.broadcast(str(project_id), "job_progress", {"job_id": job.id, "progress": 1.0})
    return job


@router.post("/projects/{project_id}/previews", response_model=JobRead)
async def create_preview(project_id: UUID, db: AsyncSession = Depends(get_db)) -> Job:
    return await _create_render_job(project_id, JobType.PREVIEW_RENDER, db)


@router.post("/projects/{project_id}/exports", response_model=JobRead)
async def create_export(project_id: UUID, db: AsyncSession = Depends(get_db)) -> Job:
    return await _create_render_job(project_id, JobType.FINAL_RENDER, db)


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.CANCELLED
    await db.commit()
    return {"ok": True}
