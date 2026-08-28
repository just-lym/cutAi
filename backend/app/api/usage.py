from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import CloudAPIUsage

router = APIRouter()


@router.get("/usage/summary")
async def usage_summary(db: AsyncSession = Depends(get_db)) -> dict:
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(
            func.coalesce(func.sum(CloudAPIUsage.cost_yuan), 0.0),
            func.coalesce(func.sum(CloudAPIUsage.input_tokens), 0),
            func.coalesce(func.sum(CloudAPIUsage.output_tokens), 0),
            func.coalesce(func.sum(CloudAPIUsage.audio_duration_ms), 0),
        ).where(CloudAPIUsage.created_at >= month_start)
    )
    total_cost, input_tokens, output_tokens, audio_ms = result.one()
    return {
        "total_cost": float(total_cost),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "audio_ms": int(audio_ms),
        "monthly_budget": settings.monthly_budget_yuan,
        "budget_remaining": max(0.0, settings.monthly_budget_yuan - float(total_cost)),
    }


@router.get("/usage/detail")
async def usage_detail(db: AsyncSession = Depends(get_db), limit: int = 200) -> list[dict]:
    result = await db.execute(
        select(CloudAPIUsage).order_by(CloudAPIUsage.created_at.desc()).limit(min(limit, 500))
    )
    return [
        {
            "id": str(item.id),
            "project_id": str(item.project_id) if item.project_id else None,
            "provider": item.provider,
            "service": item.service,
            "cost_yuan": item.cost_yuan,
            "created_at": item.created_at,
        }
        for item in result.scalars()
    ]


@router.get("/config/budget")
async def budget_config() -> dict:
    return {
        "monthly_budget_yuan": settings.monthly_budget_yuan,
        "daily_budget_yuan": settings.daily_budget_yuan,
    }
