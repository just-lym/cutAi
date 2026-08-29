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


def _track_for_insert(timeline: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    track_id = operation.get("track_id")
    if track_id:
        return _track(timeline, str(track_id))
    track_type = str(operation.get("track_type") or "video").lower()
    if track_type in {"audio", "music"}:
        return _track(timeline, "audio-music")
    if track_type in {"broll", "overlay", "video_broll"}:
        return _track(timeline, "video-broll")
    return _track(timeline, "video-main")


def _find_clip(timeline: dict[str, Any], clip_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for track in timeline.get("tracks", []):
        for clip in track.get("clips") or []:
            if str(clip.get("id")) == str(clip_id):
                return track, clip
    raise ExecutionError(f"Clip not found: {clip_id}")


def _timeline_end(timeline: dict[str, Any]) -> int:
    end_ms = 0
    for track in timeline.get("tracks", []):
        end_ms = max(
            end_ms,
            max((int(clip.get("timeline_end_ms", 0)) for clip in track.get("clips") or []), default=0),
            max((int(cue.get("end_ms", 0)) for cue in track.get("cues") or []), default=0),
        )
    return end_ms


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

        elif op_type == "INSERT_MEDIA_CLIP":
            track = _track_for_insert(next_timeline, operation)
            position_ms = int(operation.get("position_ms") or 0)
            duration_ms = int(operation["duration_ms"])
            source_in_ms = int(operation.get("source_in_ms") or 0)
            source_out_ms = int(operation.get("source_out_ms") or source_in_ms + duration_ms)
            clip = {
                "id": str(operation.get("clip_id") or uuid.uuid4()),
                "asset_id": str(operation["asset_id"]),
                "timeline_start_ms": position_ms,
                "timeline_end_ms": position_ms + duration_ms,
                "source_in_ms": source_in_ms,
                "source_out_ms": source_out_ms,
                "speed": float(operation.get("speed") or 1.0),
                "volume": float(operation.get("volume") if operation.get("volume") is not None else 1.0),
                "transform": operation.get("transform") or {"x": 0, "y": 0, "scale": 1.0},
                "effects": operation.get("effects") or [],
            }
            track.setdefault("clips", []).append(clip)
            track["clips"] = sorted(track["clips"], key=lambda item: int(item.get("timeline_start_ms") or 0))
            next_timeline["duration_ms"] = max(int(next_timeline.get("duration_ms", 0)), _timeline_end(next_timeline))

        elif op_type == "SPLIT_CLIP":
            track, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            at_ms = int(operation["at_ms"])
            clip_start = int(clip.get("timeline_start_ms") or 0)
            clip_end = int(clip.get("timeline_end_ms") or clip_start)
            if at_ms <= clip_start or at_ms >= clip_end:
                raise ExecutionError(f"SPLIT_CLIP at_ms must be inside clip bounds: {operation['clip_id']}")
            source_in = int(clip.get("source_in_ms") or 0)
            first = copy.deepcopy(clip)
            second = copy.deepcopy(clip)
            first["timeline_end_ms"] = at_ms
            first["source_out_ms"] = source_in + (at_ms - clip_start)
            second["id"] = str(operation.get("new_clip_id") or uuid.uuid4())
            second["timeline_start_ms"] = at_ms
            second["source_in_ms"] = int(first["source_out_ms"])
            clips = track.setdefault("clips", [])
            index = clips.index(clip)
            clips[index : index + 1] = [first, second]

        elif op_type == "UPDATE_CLIP":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            allowed = {
                "timeline_start_ms",
                "timeline_end_ms",
                "source_in_ms",
                "source_out_ms",
                "speed",
                "volume",
                "name",
            }
            for field in allowed:
                if field in operation:
                    clip[field] = operation[field]
            next_timeline["duration_ms"] = max(int(next_timeline.get("duration_ms", 0)), _timeline_end(next_timeline))

        elif op_type == "DELETE_CLIP":
            track, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            track["clips"] = [item for item in track.get("clips") or [] if item.get("id") != clip.get("id")]
            next_timeline["duration_ms"] = _timeline_end(next_timeline)

        elif op_type == "UPDATE_CLIP_TRANSFORM":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            transform = dict(clip.get("transform") or {})
            transform.update(operation.get("transform") or {})
            clip["transform"] = transform

        elif op_type == "APPLY_CLIP_EFFECT":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            effect = dict(operation["effect"])
            effect.setdefault("id", str(uuid.uuid4()))
            clip.setdefault("effects", []).append(effect)

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
            next_timeline["duration_ms"] = max(int(next_timeline.get("duration_ms", 0)), _timeline_end(next_timeline))

        elif op_type == "UPDATE_SUBTITLE":
            cue_id = operation["cue_id"]
            subtitle_track = _track(next_timeline, "subtitles")
            for cue in subtitle_track.setdefault("cues", []):
                if cue["id"] == cue_id:
                    for field in ("text", "start_ms", "end_ms", "speaker", "style"):
                        if field in operation:
                            cue[field] = operation[field]
                    break
            else:
                raise ExecutionError(f"Subtitle cue not found: {cue_id}")

        elif op_type == "CREATE_SUBTITLE":
            subtitle_track = _track(next_timeline, "subtitles")
            cue = {
                "id": str(operation.get("cue_id") or uuid.uuid4()),
                "start_ms": int(operation["start_ms"]),
                "end_ms": int(operation["end_ms"]),
                "text": str(operation["text"]),
                "speaker": operation.get("speaker"),
                "confidence": operation.get("confidence"),
                "style": operation.get("style"),
            }
            subtitle_track.setdefault("cues", []).append(cue)
            subtitle_track["cues"] = sorted(
                subtitle_track["cues"],
                key=lambda item: (int(item.get("start_ms") or 0), int(item.get("end_ms") or 0)),
            )
            next_timeline["duration_ms"] = max(int(next_timeline.get("duration_ms", 0)), int(operation["end_ms"]))

        elif op_type == "DELETE_SUBTITLE":
            cue_id = str(operation["cue_id"])
            subtitle_track = _track(next_timeline, "subtitles")
            cues = subtitle_track.setdefault("cues", [])
            subtitle_track["cues"] = [cue for cue in cues if str(cue.get("id")) != cue_id]

        elif op_type == "ADD_MARKER":
            next_timeline.setdefault("markers", []).append(
                {
                    "id": str(operation.get("marker_id") or uuid.uuid4()),
                    "at_ms": int(operation["at_ms"]),
                    "label": str(operation.get("label") or "Marker"),
                    "color": str(operation.get("color") or "purple"),
                }
            )

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
