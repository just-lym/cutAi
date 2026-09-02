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


def _shift_timed_items(items: list[dict[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    delta = end_ms - start_ms
    kept: list[dict[str, Any]] = []
    for item in items:
        item_start = int(item.get("timeline_start_ms", item.get("start_ms", 0)))
        item_end = int(item.get("timeline_end_ms", item.get("end_ms", item_start)))
        next_item = copy.deepcopy(item)
        if item_end <= start_ms:
            kept.append(next_item)
            continue
        if item_start >= end_ms:
            if "timeline_start_ms" in next_item:
                next_item["timeline_start_ms"] -= delta
                next_item["timeline_end_ms"] -= delta
            else:
                next_item["start_ms"] -= delta
                next_item["end_ms"] -= delta
            kept.append(next_item)
            continue
        if item_start < start_ms and item_end > end_ms:
            if "timeline_start_ms" in next_item:
                speed = float(next_item.get("speed") or 1.0)
                left = copy.deepcopy(next_item)
                right = copy.deepcopy(next_item)
                left["timeline_end_ms"] = start_ms
                left["source_out_ms"] = int(
                    int(next_item.get("source_in_ms") or 0) + (start_ms - item_start) * speed
                )
                right["id"] = str(uuid.uuid4())
                right["timeline_start_ms"] = start_ms
                right["timeline_end_ms"] = item_end - delta
                right["source_in_ms"] = int(
                    int(next_item.get("source_in_ms") or 0) + (end_ms - item_start) * speed
                )
                kept.extend((left, right))
            else:
                next_item["end_ms"] = item_end - delta
                kept.append(next_item)
            continue
        if item_start < start_ms < item_end <= end_ms:
            if "timeline_start_ms" in next_item:
                speed = float(next_item.get("speed") or 1.0)
                next_item["timeline_end_ms"] = start_ms
                next_item["source_out_ms"] = int(
                    int(next_item.get("source_in_ms") or 0) + (start_ms - item_start) * speed
                )
            else:
                next_item["end_ms"] = start_ms
            kept.append(next_item)
            continue
        if start_ms <= item_start < end_ms < item_end:
            if "timeline_start_ms" in next_item:
                speed = float(next_item.get("speed") or 1.0)
                next_item["timeline_start_ms"] = start_ms
                next_item["timeline_end_ms"] = item_end - delta
                next_item["source_in_ms"] = int(
                    int(next_item.get("source_in_ms") or 0) + (end_ms - item_start) * speed
                )
            else:
                next_item["start_ms"] = start_ms
                next_item["end_ms"] = item_end - delta
            kept.append(next_item)
    return kept


def _shift_point_items(
    items: list[dict[str, Any]], start_ms: int, end_ms: int, field: str
) -> list[dict[str, Any]]:
    delta = end_ms - start_ms
    shifted: list[dict[str, Any]] = []
    for item in items:
        at_ms = int(item.get(field) or 0)
        if start_ms <= at_ms < end_ms:
            continue
        next_item = copy.deepcopy(item)
        if at_ms >= end_ms:
            next_item[field] = at_ms - delta
        shifted.append(next_item)
    return shifted


def _shift_volume_changes(
    items: list[dict[str, Any]], start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    finite = [item for item in items if int(item.get("end_ms", -1)) >= 0]
    shifted = _shift_timed_items(finite, start_ms, end_ms)
    delta = end_ms - start_ms
    for item in items:
        if int(item.get("end_ms", -1)) >= 0:
            continue
        next_item = copy.deepcopy(item)
        item_start = int(next_item.get("start_ms") or 0)
        if item_start >= end_ms:
            next_item["start_ms"] = item_start - delta
        elif item_start >= start_ms:
            next_item["start_ms"] = start_ms
        shifted.append(next_item)
    return shifted


def _apply_delete_range(timeline: dict[str, Any], start_ms: int, end_ms: int) -> None:
    for track in timeline.get("tracks", []):
        if "clips" in track:
            track["clips"] = _shift_timed_items(track["clips"], start_ms, end_ms)
        if "cues" in track:
            track["cues"] = _shift_timed_items(track["cues"], start_ms, end_ms)
        if "effects" in track:
            effects = []
            for effect in track["effects"]:
                normalized = dict(effect)
                normalized["end_ms"] = int(effect.get("start_ms") or 0) + int(effect.get("duration_ms") or 0)
                effects.append(normalized)
            shifted_effects = _shift_timed_items(effects, start_ms, end_ms)
            for effect in shifted_effects:
                effect["duration_ms"] = max(0, int(effect.pop("end_ms")) - int(effect.get("start_ms") or 0))
            track["effects"] = [effect for effect in shifted_effects if effect["duration_ms"] > 0]
    timeline["markers"] = _shift_point_items(timeline.get("markers", []), start_ms, end_ms, "at_ms")
    timeline["volume_changes"] = _shift_volume_changes(
        timeline.get("volume_changes", []), start_ms, end_ms
    )
    timeline["duration_ms"] = max(0, int(timeline.get("duration_ms", 0)) - (end_ms - start_ms))


def apply_operations(timeline: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    next_timeline = copy.deepcopy(timeline)
    errors = validate_edit_plan(operations, next_timeline)
    if errors:
        raise ExecutionError("; ".join(errors))

    delete_operations = sorted(
        (operation for operation in operations if operation["type"] == "DELETE_RANGE"),
        key=lambda operation: int(operation["start_ms"]),
        reverse=True,
    )
    ordered_operations = [*delete_operations, *(op for op in operations if op["type"] != "DELETE_RANGE")]

    for operation in ordered_operations:
        op_type = operation["type"]

        if op_type == "DELETE_RANGE":
            start_ms = int(operation["start_ms"])
            end_ms = int(operation["end_ms"])
            _apply_delete_range(next_timeline, start_ms, end_ms)

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

        elif op_type == "TRIM_CLIP":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            source_in_ms = int(operation["source_in_ms"])
            source_out_ms = int(operation["source_out_ms"])
            speed = float(clip.get("speed") or 1.0)
            clip["source_in_ms"] = source_in_ms
            clip["source_out_ms"] = source_out_ms
            clip["timeline_end_ms"] = int(clip.get("timeline_start_ms") or 0) + round(
                (source_out_ms - source_in_ms) / speed
            )

        elif op_type == "MOVE_CLIP":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            duration_ms = int(clip.get("timeline_end_ms") or 0) - int(clip.get("timeline_start_ms") or 0)
            clip["timeline_start_ms"] = int(operation["timeline_start_ms"])
            clip["timeline_end_ms"] = int(operation["timeline_start_ms"]) + duration_ms

        elif op_type == "SET_CLIP_SPEED":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            speed = float(operation["speed"])
            clip["speed"] = speed
            source_duration = int(clip.get("source_out_ms") or 0) - int(clip.get("source_in_ms") or 0)
            clip["timeline_end_ms"] = int(clip.get("timeline_start_ms") or 0) + round(source_duration / speed)

        elif op_type == "SET_CLIP_VOLUME":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            clip["volume"] = float(operation["volume"])

        elif op_type == "DUPLICATE_CLIP":
            track, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            duplicate = copy.deepcopy(clip)
            duplicate["id"] = str(operation.get("new_clip_id") or uuid.uuid4())
            duration_ms = int(clip.get("timeline_end_ms") or 0) - int(clip.get("timeline_start_ms") or 0)
            duplicate["timeline_start_ms"] = int(operation["timeline_start_ms"])
            duplicate["timeline_end_ms"] = int(operation["timeline_start_ms"]) + duration_ms
            track.setdefault("clips", []).append(duplicate)
            track["clips"].sort(key=lambda item: int(item.get("timeline_start_ms") or 0))

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

        elif op_type == "REMOVE_EFFECT":
            _, clip = _find_clip(next_timeline, str(operation["clip_id"]))
            effect_id = str(operation["effect_id"])
            clip["effects"] = [
                effect for effect in clip.get("effects") or [] if str(effect.get("id")) != effect_id
            ]

        elif op_type == "ADD_TRANSITION":
            next_timeline.setdefault("transitions", []).append(
                {
                    "id": str(operation.get("transition_id") or uuid.uuid4()),
                    "from_clip_id": str(operation["from_clip_id"]),
                    "to_clip_id": str(operation["to_clip_id"]),
                    "transition_type": str(operation.get("transition_type") or "crossfade"),
                    "duration_ms": int(operation["duration_ms"]),
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

        elif op_type == "UPDATE_SUBTITLE_STYLE":
            cue_id = str(operation["cue_id"])
            subtitle_track = _track(next_timeline, "subtitles")
            for cue in subtitle_track.setdefault("cues", []):
                if str(cue.get("id")) == cue_id:
                    style = dict(cue.get("style") or {})
                    style.update(operation["style"])
                    cue["style"] = style
                    break

        elif op_type == "ADD_MARKER":
            next_timeline.setdefault("markers", []).append(
                {
                    "id": str(operation.get("marker_id") or uuid.uuid4()),
                    "at_ms": int(operation["at_ms"]),
                    "label": str(operation.get("label") or "Marker"),
                    "color": str(operation.get("color") or "purple"),
                }
            )

        elif op_type == "REMOVE_MARKER":
            marker_id = str(operation["marker_id"])
            next_timeline["markers"] = [
                marker for marker in next_timeline.get("markers", []) if str(marker.get("id")) != marker_id
            ]

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

    next_timeline["duration_ms"] = max(int(next_timeline.get("duration_ms", 0)), _timeline_end(next_timeline))
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
