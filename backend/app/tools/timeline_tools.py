from typing import Any

SUPPORTED_OPERATIONS = {
    "DELETE_RANGE",
    "SET_VOLUME",
    "INSERT_MEDIA_CLIP",
    "SPLIT_CLIP",
    "UPDATE_CLIP",
    "DELETE_CLIP",
    "UPDATE_CLIP_TRANSFORM",
    "APPLY_CLIP_EFFECT",
    "INSERT_BROLL_OVERLAY",
    "UPDATE_SUBTITLE",
    "CREATE_SUBTITLE",
    "DELETE_SUBTITLE",
    "ADD_MARKER",
    "FADE_IN",
    "FADE_OUT",
}


def _to_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = -1) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_edit_plan(operations: list[dict[str, Any]], timeline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ranges: list[tuple[int, int]] = []
    duration = int(timeline.get("duration_ms") or 0)
    known_clip_ids = {
        str(clip.get("id"))
        for track in timeline.get("tracks", [])
        for clip in track.get("clips") or []
        if clip.get("id")
    }
    known_cue_ids = {
        str(cue.get("id"))
        for track in timeline.get("tracks", [])
        for cue in track.get("cues") or []
        if cue.get("id")
    }
    known_track_ids = {
        str(track.get("id"))
        for track in timeline.get("tracks", [])
        if track.get("id")
    }

    for index, operation in enumerate(operations):
        op_type = operation.get("type")
        if op_type not in SUPPORTED_OPERATIONS:
            errors.append(f"operation[{index}] unsupported type: {op_type}")
            continue

        if op_type == "DELETE_RANGE":
            start_ms = _to_int(operation.get("start_ms"))
            end_ms = _to_int(operation.get("end_ms"))
            if start_ms < 0 or end_ms <= start_ms:
                errors.append(f"operation[{index}] DELETE_RANGE requires start_ms < end_ms")
            if duration and end_ms > duration:
                errors.append(f"operation[{index}] DELETE_RANGE exceeds timeline duration")
            ranges.append((start_ms, end_ms))

        if op_type == "SET_VOLUME":
            volume = _to_float(operation.get("volume"))
            if volume < 0 or volume > 2:
                errors.append(f"operation[{index}] SET_VOLUME requires 0 <= volume <= 2")

        if op_type == "INSERT_MEDIA_CLIP":
            if not operation.get("asset_id"):
                errors.append(f"operation[{index}] INSERT_MEDIA_CLIP requires asset_id")
            track_id = operation.get("track_id")
            if track_id and str(track_id) not in known_track_ids:
                errors.append(f"operation[{index}] INSERT_MEDIA_CLIP track does not exist: {track_id}")
            position_ms = _to_int(operation.get("position_ms"), 0)
            duration_ms = _to_int(operation.get("duration_ms"))
            if position_ms < 0 or duration_ms <= 0:
                errors.append(f"operation[{index}] INSERT_MEDIA_CLIP requires position_ms >= 0 and duration_ms > 0")
            if operation.get("clip_id"):
                known_clip_ids.add(str(operation["clip_id"]))

        if op_type == "SPLIT_CLIP":
            clip_id = operation.get("clip_id")
            at_ms = _to_int(operation.get("at_ms"))
            if not clip_id or str(clip_id) not in known_clip_ids:
                errors.append(f"operation[{index}] SPLIT_CLIP requires an existing clip_id")
            if at_ms < 0:
                errors.append(f"operation[{index}] SPLIT_CLIP requires at_ms >= 0")
            if operation.get("new_clip_id"):
                known_clip_ids.add(str(operation["new_clip_id"]))

        if op_type == "UPDATE_CLIP":
            clip_id = operation.get("clip_id")
            if not clip_id or str(clip_id) not in known_clip_ids:
                errors.append(f"operation[{index}] UPDATE_CLIP requires an existing clip_id")

        if op_type == "DELETE_CLIP":
            clip_id = operation.get("clip_id")
            if not clip_id or str(clip_id) not in known_clip_ids:
                errors.append(f"operation[{index}] DELETE_CLIP requires an existing clip_id")
            else:
                known_clip_ids.discard(str(clip_id))

        if op_type == "UPDATE_CLIP_TRANSFORM":
            clip_id = operation.get("clip_id")
            transform = operation.get("transform")
            if not clip_id or str(clip_id) not in known_clip_ids:
                errors.append(f"operation[{index}] UPDATE_CLIP_TRANSFORM requires an existing clip_id")
            if not isinstance(transform, dict):
                errors.append(f"operation[{index}] UPDATE_CLIP_TRANSFORM requires transform object")

        if op_type == "APPLY_CLIP_EFFECT":
            clip_id = operation.get("clip_id")
            effect = operation.get("effect")
            if not clip_id or str(clip_id) not in known_clip_ids:
                errors.append(f"operation[{index}] APPLY_CLIP_EFFECT requires an existing clip_id")
            if not isinstance(effect, dict) or not effect.get("type"):
                errors.append(f"operation[{index}] APPLY_CLIP_EFFECT requires effect.type")

        if op_type == "INSERT_BROLL_OVERLAY":
            if not operation.get("asset_id"):
                errors.append(f"operation[{index}] INSERT_BROLL_OVERLAY requires asset_id")
            if _to_int(operation.get("duration_ms"), 0) <= 0:
                errors.append(f"operation[{index}] INSERT_BROLL_OVERLAY requires duration_ms > 0")

        if op_type == "UPDATE_SUBTITLE":
            cue_id = operation.get("cue_id")
            if not cue_id:
                errors.append(f"operation[{index}] UPDATE_SUBTITLE requires cue_id")
            elif str(cue_id) not in known_cue_ids:
                errors.append(f"operation[{index}] UPDATE_SUBTITLE cue does not exist: {cue_id}")

        if op_type == "CREATE_SUBTITLE":
            text = str(operation.get("text") or "").strip()
            start_ms = _to_int(operation.get("start_ms"))
            end_ms = _to_int(operation.get("end_ms"))
            if not text:
                errors.append(f"operation[{index}] CREATE_SUBTITLE requires text")
            if start_ms < 0 or end_ms <= start_ms:
                errors.append(f"operation[{index}] CREATE_SUBTITLE requires start_ms < end_ms")
            if duration and end_ms > duration:
                errors.append(f"operation[{index}] CREATE_SUBTITLE exceeds timeline duration")
            if operation.get("cue_id"):
                known_cue_ids.add(str(operation["cue_id"]))

        if op_type == "DELETE_SUBTITLE":
            cue_id = operation.get("cue_id")
            if not cue_id or str(cue_id) not in known_cue_ids:
                errors.append(f"operation[{index}] DELETE_SUBTITLE requires an existing cue_id")
            else:
                known_cue_ids.discard(str(cue_id))

        if op_type == "ADD_MARKER":
            at_ms = _to_int(operation.get("at_ms"))
            if at_ms < 0:
                errors.append(f"operation[{index}] ADD_MARKER requires at_ms >= 0")

        if op_type in {"FADE_IN", "FADE_OUT"}:
            start_ms = _to_int(operation.get("start_ms"))
            duration_ms = _to_int(operation.get("duration_ms"))
            if start_ms < 0 or duration_ms <= 0:
                errors.append(f"operation[{index}] {op_type} requires start_ms >= 0 and duration_ms > 0")

    for left_index, left in enumerate(ranges):
        for right in ranges[left_index + 1 :]:
            if left[0] < right[1] and right[0] < left[1]:
                errors.append("DELETE_RANGE operations must not overlap")
    return errors
