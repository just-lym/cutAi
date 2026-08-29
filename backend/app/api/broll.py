from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Asset
from app.schemas import BrollSearchRequest, BrollSelectRequest
from app.services.executor import get_latest_timeline

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/projects/{project_id}/broll/analyze")
async def analyze_broll(project_id: UUID, db: DbSession) -> dict:
    timeline = await get_latest_timeline(db, project_id)
    duration = int(timeline.timeline_json.get("duration_ms") or 120000)
    positions = [
        {
            "position_ms": max(0, duration // 3),
            "duration_ms": 4000,
            "context": "内容转折点",
            "visual_description": "与当前主题相关的补充画面",
            "prompt_en": "Relevant cinematic b-roll footage, realistic, clean composition",
            "style_hints": "cinematic, natural",
            "audio_policy": "KEEP_ORIGINAL",
        }
    ]
    return {"positions": positions}


@router.post("/projects/{project_id}/broll/search-library")
async def search_library(
    project_id: UUID,
    payload: BrollSearchRequest,
    db: DbSession,
) -> dict:
    result = await db.execute(select(Asset).where(Asset.project_id == project_id).limit(payload.limit))
    candidates = [
        {
            "asset_id": str(asset.id),
            "title": asset.original_name,
            "type": asset.type.value,
            "score": 0.75,
            "thumbnail_url": None,
        }
        for asset in result.scalars()
    ]
    return {"candidates": candidates}


@router.post("/projects/{project_id}/broll/select")
async def select_broll(
    project_id: UUID,
    payload: BrollSelectRequest,
    db: DbSession,
) -> dict:
    asset = await db.get(Asset, payload.asset_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {
        "ok": True,
        "operation": {
            "type": "INSERT_BROLL_OVERLAY",
            "asset_id": str(asset.id),
            "position_ms": payload.position_ms,
            "duration_ms": payload.duration_ms,
        },
    }
