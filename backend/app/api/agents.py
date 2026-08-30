import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import stream_agent_graph
from app.agents.modes import get_agent_mode
from app.cloud_api.cost_tracker import record_usage
from app.config import settings
from app.database import get_db
from app.models import AgentSession, Asset, EditPlan, EditPlanStatus, Project, TimelineVersion
from app.schemas import (
    AgentMessage,
    ApprovalRequest,
    ApprovalResponse,
)
from app.services.executor import ExecutionError, execute_edit_plan, get_latest_timeline
from app.ws.events import manager

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass
class AgentRunResult:
    session_id: UUID
    reply: str
    edit_plan: dict[str, Any] | None
    awaiting_user: bool
    total_cost: float
    trace: list[dict[str, Any]]
    rendered_files: list[str]


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


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


def _timeline_summary(timeline: dict[str, Any]) -> dict[str, Any]:
    tracks = timeline.get("tracks", [])
    return {
        "duration_ms": int(timeline.get("duration_ms") or 0),
        "track_count": len(tracks),
        "clip_count": sum(len(track.get("clips", [])) for track in tracks),
        "subtitle_count": sum(len(track.get("cues", [])) for track in tracks),
    }


def _asset_context(asset: Asset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "project_id": str(asset.project_id),
        "type": asset.type.value if hasattr(asset.type, "value") else str(asset.type),
        "source_type": asset.source_type.value if hasattr(asset.source_type, "value") else str(asset.source_type),
        "original_name": asset.original_name,
        "file_path": asset.file_path,
        "proxy_path": asset.proxy_path,
        "mime_type": asset.mime_type,
        "duration_ms": asset.duration_ms,
        "width": asset.width,
        "height": asset.height,
        "frame_rate": asset.frame_rate,
        "processing_status": asset.processing_status.value
        if hasattr(asset.processing_status, "value")
        else str(asset.processing_status),
    }


def build_agent_failure_response(
    content: str,
    timeline: dict[str, Any],
    mode_label: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = [
        {
            "title": "读取项目时间线",
            "detail": "已加载当前时间线、轨道、片段和字幕，用于判断可执行的剪辑动作。",
            "data": _timeline_summary(timeline),
        },
        {
            "title": "等待 Agent 恢复",
            "detail": f"收到指令：{content}",
            "data": {"mode": "agentic_only"},
        },
    ]
    trace.append(
        {
            "title": "未生成本地伪计划",
            "detail": f"当前项目只接受{mode_label}模式 Agent 和工具调用产出的剪辑建议；本地兜底不会按关键词伪造操作。",
            "data": {"creative_mode": mode_label},
        }
    )
    return "Agent 执行失败，未生成剪辑计划。请检查模型服务或稍后重试。", [], trace


async def _record_agent_usage(
    db: AsyncSession,
    project_id: UUID,
    session: AgentSession,
    usage_records: list[dict[str, Any]],
) -> None:
    for usage_record in usage_records:
        usage = await record_usage(
            db,
            provider=str(usage_record.get("provider") or "dashscope"),
            service=str(usage_record.get("model") or "qwen-plus"),
            project_id=project_id,
            input_tokens=int(usage_record.get("input_tokens") or 0),
            output_tokens=int(usage_record.get("output_tokens") or 0),
            request_id=str(usage_record.get("request_id")) if usage_record.get("request_id") else None,
        )
        session.total_tokens_used += int(usage_record.get("input_tokens") or 0) + int(
            usage_record.get("output_tokens") or 0
        )
        session.total_cost_yuan += usage.cost_yuan


async def _persist_agent_result(
    db: AsyncSession,
    project_id: UUID,
    session: AgentSession,
    timeline_version: int,
    reply: str,
    operations: list[dict[str, Any]],
    conflicts: list[str],
    trace: list[dict[str, Any]],
    usage_records: list[dict[str, Any]],
    rendered_files: list[str] | None = None,
    created_by_agent: str = "creative-director",
    awaiting_user: bool = False,
) -> AgentRunResult:
    await _record_agent_usage(db, project_id, session, usage_records)

    edit_plan = None
    should_await_user = awaiting_user
    if operations:
        plan = EditPlan(
            project_id=project_id,
            base_timeline_version=timeline_version,
            status=EditPlanStatus.WAITING_USER,
            operations=operations,
            conflicts=conflicts,
            estimated_cost=0.0,
            created_by_agent=created_by_agent,
        )
        db.add(plan)
        await db.flush()
        edit_plan = {
            "id": str(plan.id),
            "summary": reply,
            "operations": operations,
            "conflicts": conflicts,
            "requires_user_approval": True,
            "rendered_files": rendered_files or [],
        }
        should_await_user = True

    await db.commit()
    return AgentRunResult(
        session_id=session.id,
        reply=reply,
        edit_plan=edit_plan,
        awaiting_user=should_await_user,
        total_cost=session.total_cost_yuan,
        trace=trace,
        rendered_files=rendered_files or [],
    )


def _agent_result_from_state(
    final_state: dict[str, Any],
) -> tuple[
    str,
    list[dict[str, Any]],
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    bool,
]:
    edit_plan_payload = final_state.get("edit_plans")
    reply = final_state.get("reply") or (
        edit_plan_payload.get("summary") if edit_plan_payload else "Agent 已完成处理。"
    )
    operations = list(edit_plan_payload.get("operations") or []) if edit_plan_payload else []
    conflicts = list(edit_plan_payload.get("conflicts") or []) if edit_plan_payload else []
    trace = list(final_state.get("trace") or [])
    usage_records = list(final_state.get("usage_records") or [])
    rendered_files = list(edit_plan_payload.get("rendered_files") or []) if edit_plan_payload else []
    awaiting_user = bool(final_state.get("awaiting_user"))
    return str(reply), operations, conflicts, trace, usage_records, rendered_files, awaiting_user


@router.post("/projects/{project_id}/agent/stream")
async def stream_agent_message(
    project_id: UUID,
    payload: AgentMessage,
    db: DbSession,
) -> StreamingResponse:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    mode = get_agent_mode(project.video_type)
    session = await _get_or_create_session(db, project_id)
    timeline = await get_latest_timeline(db, project_id)
    asset_result = await db.execute(select(Asset).where(Asset.project_id == project_id))
    assets = [_asset_context(asset) for asset in asset_result.scalars()]

    async def event_stream():
        yield _sse(
            "thinking",
            {
                "agent": mode.coordinator_name,
                "video_type": mode.video_type,
                "mode_label": mode.label,
                "team": list(mode.team),
                "detail": f"正在进入{mode.label}多 Agent 模式并读取项目状态。",
            },
        )
        yield _sse(
            "progress",
            {
                "stage": "start",
                "detail": f"已提交给{mode.label}创作团队，正在准备项目上下文。",
                "progress": 0.05,
            },
        )
        final_state: dict[str, Any] | None = None
        streamed_trace_count = 0

        async def run_graph() -> asyncio.Queue[tuple[str, dict[str, Any]]]:
            queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

            async def producer() -> None:
                nonlocal final_state, streamed_trace_count
                try:
                    async for state in stream_agent_graph(
                        content=payload.content,
                        project_id=str(project_id),
                        project_dir=str(settings.projects_root / str(project_id)),
                        timeline_version=timeline.version,
                        timeline=timeline.timeline_json,
                        assets=assets,
                        video_type=mode.video_type,
                    ):
                        final_state = dict(state)
                        trace_steps = list(final_state.get("trace") or [])
                        for step in trace_steps[streamed_trace_count:]:
                            step_data = step.get("data") if isinstance(step, dict) else {}
                            if isinstance(step_data, dict):
                                for tool_call in step_data.get("tool_calls") or []:
                                    await queue.put(
                                        (
                                            "tool_call",
                                            {
                                                "tool": tool_call.get("name") or tool_call.get("tool") or "unknown",
                                                "detail": f"Agent 调用了 {tool_call.get('name') or tool_call.get('tool') or 'unknown'}",
                                                "agent": step_data.get("agent"),
                                            },
                                        )
                                    )
                            await queue.put(("trace", step))
                        streamed_trace_count = len(trace_steps)
                    await queue.put(("graph_done", {}))
                except Exception as exc:  # noqa: BLE001 - stream reports graph failures to client.
                    await queue.put(("graph_error", {"message": f"{type(exc).__name__}: {exc}"}))

            asyncio.create_task(producer())
            return queue

        try:
            queue = await run_graph()
            heartbeat_count = 0
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=2.0)
                except TimeoutError:
                    heartbeat_count += 1
                    yield _sse(
                        "status",
                        {
                            "agent": mode.coordinator_name,
                            "detail": f"{mode.label}创作团队正在调用模型或工具，任务仍在进行中。",
                            "elapsed_seconds": heartbeat_count * 2,
                        },
                    )
                    yield _sse(
                        "progress",
                        {
                            "stage": "running",
                            "detail": "Agent 仍在运行，可能正在等待模型响应或 FFmpeg 工具完成。",
                            "elapsed_seconds": heartbeat_count * 2,
                            "progress": min(0.85, 0.08 + heartbeat_count * 0.03),
                        },
                    )
                    continue
                if event == "graph_done":
                    break
                if event == "graph_error":
                    raise RuntimeError(data["message"])
                yield _sse(event, data)

            if final_state is None:
                raise RuntimeError("Agent stream finished without final state")

            reply, operations, conflicts, trace, usage_records, rendered_files, awaiting_user = (
                _agent_result_from_state(final_state)
            )
            progress_detail = (
                "Agent 需要你补充信息，本轮没有开始剪辑。"
                if awaiting_user
                else "Agent 已完成思考，正在保存可审批结果。"
            )
            yield _sse(
                "progress",
                {"stage": "clarification" if awaiting_user else "review", "detail": progress_detail, "progress": 0.9},
            )
            response = await _persist_agent_result(
                db,
                project_id,
                session,
                timeline.version,
                reply,
                operations,
                conflicts,
                trace,
                usage_records,
                rendered_files,
                str(final_state.get("coordinator_name") or mode.coordinator_name),
                awaiting_user,
            )
        except Exception as exc:  # noqa: BLE001 - stream should degrade into a usable local plan.
            await db.rollback()
            error_type = type(exc).__name__
            yield _sse(
                "trace",
                {
                    "title": "LangGraph Agent 调用失败",
                    "detail": "多 Agent 图执行失败，当前不会按规则伪造剪辑计划。",
                    "data": {"error": f"{error_type}: {exc}"},
                },
            )
            try:
                reply, operations, trace = build_agent_failure_response(
                    payload.content,
                    timeline.timeline_json,
                    mode.label,
                )
                response = await _persist_agent_result(
                    db,
                    project_id,
                    session,
                    timeline.version,
                    reply,
                    operations,
                    [],
                    trace,
                    [],
                    [],
                    mode.coordinator_name,
                )
            except Exception as fallback_exc:  # noqa: BLE001 - report terminal stream failure to the UI.
                yield _sse("error", {"message": f"{type(fallback_exc).__name__}: {fallback_exc}"})
                return

        if response.edit_plan:
            yield _sse("plan", response.edit_plan)
        for rendered_file in response.rendered_files:
            yield _sse(
                "preview_ready",
                {
                    "detail": "Agent 已生成预览/输出文件；如果还有时间线操作，仍需审批后才会应用。",
                    "path": rendered_file,
                },
            )
        yield _sse("token", {"content": response.reply})
        yield _sse(
            "done",
            {
                "session_id": str(response.session_id),
                "total_cost": response.total_cost,
                "video_type": mode.video_type,
                "coordinator": mode.coordinator_name,
                "team": list(mode.team),
                "awaiting_user": response.awaiting_user,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/runs/{plan_id}/approve", response_model=ApprovalResponse)
async def approve_plan(
    plan_id: UUID,
    db: DbSession,
    payload: ApprovalRequest | None = None,
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
            change_summary=f"Applied AI edit plan {plan.id}",
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
async def reject_plan(plan_id: UUID, db: DbSession) -> dict:
    plan = await db.get(EditPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Edit plan not found")
    plan.status = EditPlanStatus.REJECTED
    await db.commit()
    return {"ok": True}


@router.post("/agent/runs/{plan_id}/undo")
async def undo_applied_plan(plan_id: UUID, db: DbSession) -> dict:
    plan = await db.get(EditPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Edit plan not found")
    if plan.status != EditPlanStatus.APPLIED:
        raise HTTPException(status_code=400, detail="Only applied edit plans can be undone")

    latest = await get_latest_timeline(db, plan.project_id)
    applied_result = await db.execute(
        select(TimelineVersion)
        .where(
            TimelineVersion.project_id == plan.project_id,
            TimelineVersion.change_summary == f"Applied AI edit plan {plan.id}",
        )
        .order_by(TimelineVersion.version.desc())
        .limit(1)
    )
    applied = applied_result.scalar_one_or_none()
    if applied is None:
        raise HTTPException(status_code=404, detail="Applied timeline version not found")
    if latest.id != applied.id:
        raise HTTPException(
            status_code=409,
            detail="Cannot undo this plan because newer timeline versions exist. Restore a timeline version manually.",
        )

    base_result = await db.execute(
        select(TimelineVersion)
        .where(
            TimelineVersion.project_id == plan.project_id,
            TimelineVersion.version == plan.base_timeline_version,
        )
        .limit(1)
    )
    base = base_result.scalar_one_or_none()
    if base is None:
        raise HTTPException(status_code=404, detail="Base timeline version not found")

    restored = TimelineVersion(
        project_id=plan.project_id,
        version=latest.version + 1,
        parent_version_id=latest.id,
        timeline_json=base.timeline_json,
        change_summary=f"Undo AI edit plan {plan.id}",
        created_by="agent_undo",
    )
    db.add(restored)
    project = await db.get(Project, plan.project_id)
    if project is not None:
        project.current_timeline_version = restored.version
        project.duration_ms = int(restored.timeline_json.get("duration_ms", 0))
    await db.commit()
    await manager.broadcast(
        str(plan.project_id),
        "timeline_updated",
        {"version": restored.version, "timeline_version_id": restored.id},
    )
    return {"ok": True, "timeline_version": restored.version, "plan_status": plan.status.value}
