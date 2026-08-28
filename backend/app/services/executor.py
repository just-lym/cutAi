import copy
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, TimelineVersion
from app.tools.timeline_tools import validate_edit_plan


class ExecutionError(RuntimeError):
    pass


def _track(timeline: dict[str, Any], track_id: str) -> dict[str, Any]:
    for track in timeline.get("tracks", []):
        if track.get("id") == track_id:
            return track
    raise ExecutionError(f"Missing timeline track: {track_id}")


def _shift_after_delete(items: list[dict[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    delta = end_ms - start_ms
    kept: list[dict[str, Any]] = []
    for item in items:
        item_start = int(item.get("timeline_start_ms", item.get("start_ms", 0)))
        item_end = int(item.get("timeline_end_ms", item.get("end_ms", item_start)))
        if item_end <= start_ms:
            kept.append(item)
            continue
        if item_start >= end_ms:
            item = copy.deepcopy(item)
            if "timeline_start_ms" in item:
                item["timeline_start_ms"] -= delta
                item["timeline_end_ms"] -= delta
            else:
                item["start_ms"] -= delta
                item["end_ms"] -= delta
            kept.append(item)
    return kept


def apply_operations(timeline: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    next_timeline = copy.deepcopy(timeline)
    errors = validate_edit_plan(operations, next_timeline)
    if errors:
        raise ExecutionError("; ".join(errors))

    for operation in operations:
        op_type = operation["type"]

        if op_type == "DELETE_RANGE":
            start_ms = int(operation["start_ms"])
            end_ms = int(operation["end_ms"])
            for track in next_timeline.get("tracks", []):
                if "clips" in track:
                    track["clips"] = _shift_after_delete(track["clips"], start_ms, end_ms)
                if "cues" in track:
                    track["cues"] = _shift_after_delete(track["cues"], start_ms, end_ms)
            next_timeline["duration_ms"] = max(0, int(next_timeline.get("duration_ms", 0)) - (end_ms - start_ms))

        elif op_type == "SET_VOLUME":
            next_timeline.setdefault("volume_changes", []).append(
                {
                    "id": str(uuid.uuid4()),
                    "start_ms": int(operation.get("start_ms", 0)),
                    "end_ms": int(operation.get("end_ms", -1)),
                    "volume": float(operation["volume"]),
                }
            )

        elif op_type == "INSERT_BROLL_OVERLAY":
            broll_track = _track(next_timeline, "video-broll")
            position_ms = int(operation["position_ms"])
            duration_ms = int(operation["duration_ms"])
            broll_track.setdefault("clips", []).append(
                {
                    "id": str(uuid.uuid4()),
                    "asset_id": str(operation["asset_id"]),
                    "timeline_start_ms": position_ms,
                    "timeline_end_ms": position_ms + duration_ms,
                    "source_in_ms": 0,
                    "source_out_ms": duration_ms,
                    "speed": 1.0,
                    "volume": 0.0,
                    "transform": {"x": 0, "y": 0, "scale": 1.0},
                    "effects": [],
                }
            )

        elif op_type == "UPDATE_SUBTITLE":
            cue_id = operation["cue_id"]
            subtitle_track = _track(next_timeline, "subtitles")
            for cue in subtitle_track.setdefault("cues", []):
                if cue["id"] == cue_id:
                    for field in ("text", "start_ms", "end_ms", "speaker"):
                        if field in operation:
                            cue[field] = operation[field]
                    break
            else:
                raise ExecutionError(f"Subtitle cue not found: {cue_id}")

        elif op_type in {"FADE_IN", "FADE_OUT"}:
            original_audio = _track(next_timeline, "audio-original")
            original_audio.setdefault("effects", []).append(
                {
                    "id": str(uuid.uuid4()),
                    "type": op_type,
                    "start_ms": int(operation["start_ms"]),
                    "duration_ms": int(operation["duration_ms"]),
                }
            )

    return next_timeline


async def get_latest_timeline(db: AsyncSession, project_id: UUID) -> TimelineVersion:
    result = await db.execute(
        select(TimelineVersion)
        .where(TimelineVersion.project_id == project_id)
        .order_by(TimelineVersion.version.desc())
        .limit(1)
    )
    timeline = result.scalar_one_or_none()
    if timeline is None:
        raise ExecutionError("Timeline does not exist")
    return timeline


async def execute_edit_plan(
    db: AsyncSession,
    project_id: UUID,
    operations: list[dict[str, Any]],
    created_by: str = "agent",
    change_summary: str = "Applied edit plan",
) -> TimelineVersion:
    current = await get_latest_timeline(db, project_id)
    next_json = apply_operations(current.timeline_json, operations)
    next_version = TimelineVersion(
        project_id=project_id,
        version=current.version + 1,
        parent_version_id=current.id,
        timeline_json=next_json,
        change_summary=change_summary,
        created_by=created_by,
    )
    db.add(next_version)

    project = await db.get(Project, project_id)
    if project is not None:
        project.current_timeline_version = next_version.version
        project.duration_ms = int(next_json.get("duration_ms", 0))

    await db.flush()
    return next_version
