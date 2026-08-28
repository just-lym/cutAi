import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AgentSession, EditPlan, EditPlanStatus, Project
from app.schemas import AgentMessage, AgentRunResponse, ApprovalRequest, ApprovalResponse
from app.services.executor import ExecutionError, execute_edit_plan, get_latest_timeline
from app.ws.events import manager

router = APIRouter()


def _subtitle_track(timeline: dict[str, Any]) -> dict[str, Any]:
    return next(track for track in timeline.get("tracks", []) if track.get("id") == "subtitles")


def _broll_candidates(timeline: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            asset_id = clip.get("asset_id")
            if asset_id and asset_id not in ids:
                ids.append(asset_id)
    return ids


async def _get_or_create_session(db: AsyncSession, project_id: UUID) -> AgentSession:
    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.project_id == project_id, AgentSession.status == "ACTIVE")
        .order_by(AgentSession.updated_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        session = AgentSession(project_id=project_id)
        db.add(session)
        await db.flush()
    return session


def build_deterministic_plan(content: str, timeline: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    text = content.lower()
    duration = int(timeline.get("duration_ms") or 120000)
    operations: list[dict[str, Any]] = []

    if any(keyword in content for keyword in ["静音", "停顿", "空白"]) or "silence" in text:
        start_ms = min(1000, max(0, duration - 2000))
        operations.append(
            {
                "type": "DELETE_RANGE",
                "start_ms": start_ms,
                "end_ms": min(start_ms + 1000, duration),
                "reason": "示例计划：删除检测到的短静音段",
            }
        )

    if any(keyword in content for keyword in ["音量", "声音"]) or "volume" in text:
        operations.append({"type": "SET_VOLUME", "start_ms": 0, "end_ms": -1, "volume": 1.15})

    subtitle_track = _subtitle_track(timeline)
    cues = subtitle_track.get("cues", [])
    if cues and (any(keyword in content for keyword in ["字幕", "错字", "文案"]) or "subtitle" in text):
        first = cues[0]
        operations.append(
            {
                "type": "UPDATE_SUBTITLE",
                "cue_id": first["id"],
                "text": first["text"].strip(),
                "start_ms": first["start_ms"],
                "end_ms": first["end_ms"],
            }
        )

    if any(keyword in content for keyword in ["b-roll", "B-roll", "素材", "插入"]) or "broll" in text:
        candidates = _broll_candidates(timeline)
        if candidates:
            operations.append(
                {
                    "type": "INSERT_BROLL_OVERLAY",
                    "asset_id": candidates[0],
                    "position_ms": min(30000, max(0, duration // 3)),
                    "duration_ms": 4000,
                    "context": "示例计划：在内容转折点插入覆盖素材",
                }
            )

    if not operations:
        return "我理解了。当前 MVP Agent 会在你提到静音、字幕、音量或 B-roll 时生成可审批的编辑计划。", []

    summary = f"已生成 {len(operations)} 条编辑建议，等待你确认后应用到时间轴。"
    return summary, operations


@router.post("/projects/{project_id}/agent/messages", response_model=AgentRunResponse)
async def send_agent_message(
    project_id: UUID,
    payload: AgentMessage,
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session = await _get_or_create_session(db, project_id)
    timeline = await get_latest_timeline(db, project_id)
    reply, operations = build_deterministic_plan(payload.content, timeline.timeline_json)
    edit_plan = None
    awaiting_user = False

    if operations:
        plan = EditPlan(
            project_id=project_id,
            base_timeline_version=timeline.version,
            status=EditPlanStatus.WAITING_USER,
            operations=operations,
            conflicts=[],
            estimated_cost=0.0,
            created_by_agent="deterministic-supervisor",
        )
        db.add(plan)
        await db.flush()
        edit_plan = {
            "id": str(plan.id),
            "summary": reply,
            "operations": operations,
            "conflicts": [],
            "requires_user_approval": True,
        }
        awaiting_user = True

    await db.commit()
    return AgentRunResponse(
        session_id=session.id,
        reply=reply,
        edit_plan=edit_plan,
        awaiting_user=awaiting_user,
        total_cost=session.total_cost_yuan,
    )


@router.post("/projects/{project_id}/agent/stream")
async def stream_agent_message(
    project_id: UUID,
    payload: AgentMessage,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    async def event_stream():
        yield "event: thinking\ndata: {\"agent\":\"supervisor\"}\n\n"
        response = await send_agent_message(project_id, payload, db)
        if response.edit_plan:
            yield f"event: plan\ndata: {json.dumps(response.edit_plan, default=str)}\n\n"
        yield f"event: token\ndata: {json.dumps({'content': response.reply})}\n\n"
        yield f"event: done\ndata: {json.dumps({'session_id': str(response.session_id), 'total_cost': response.total_cost})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/agent/sessions/{session_id}")
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)) -> AgentSession:
    session = await db.get(AgentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    return session


@router.post("/agent/runs/{plan_id}/approve", response_model=ApprovalResponse)
async def approve_plan(
    plan_id: UUID,
    payload: ApprovalRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    plan = await db.get(EditPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Edit plan not found")
    if plan.status not in {EditPlanStatus.WAITING_USER, EditPlanStatus.PROPOSED}:
        raise HTTPException(status_code=400, detail="Edit plan is not waiting for approval")

    operations = list(plan.operations)
    if payload and payload.approved_indices is not None:
        approved_indices = set(payload.approved_indices)
        rejected_indices = set(payload.rejected_indices or [])
        selected = [operation for index, operation in enumerate(operations) if index in approved_indices]
        rejected_count = len(rejected_indices)
        plan.status = EditPlanStatus.PARTIALLY_APPROVED
    else:
        selected = operations
        rejected_count = 0
        plan.status = EditPlanStatus.APPROVED

    try:
        timeline = await execute_edit_plan(
            db,
            plan.project_id,
            selected,
            created_by="agent",
            change_summary="Approved AI edit plan",
        )
        plan.status = EditPlanStatus.APPLIED
        plan.approved_by = "local"
        await db.commit()
        await manager.broadcast(
            str(plan.project_id),
            "timeline_updated",
            {"version": timeline.version, "timeline_version_id": timeline.id},
        )
        return ApprovalResponse(
            ok=True,
            applied_count=len(selected),
            rejected_count=rejected_count,
            plan_status=plan.status.value,
            timeline_version=timeline.version,
        )
    except ExecutionError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/runs/{plan_id}/reject")
async def reject_plan(plan_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    plan = await db.get(EditPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Edit plan not found")
    plan.status = EditPlanStatus.REJECTED
    await db.commit()
    return {"ok": True}


@router.post("/agent/runs/{plan_id}/cancel")
async def cancel_plan(plan_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    return await reject_plan(plan_id, db)
