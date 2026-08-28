from typing import Any


SUPPORTED_OPERATIONS = {
    "DELETE_RANGE",
    "SET_VOLUME",
    "INSERT_BROLL_OVERLAY",
    "UPDATE_SUBTITLE",
    "FADE_IN",
    "FADE_OUT",
}


def validate_edit_plan(operations: list[dict[str, Any]], timeline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ranges: list[tuple[int, int]] = []
    duration = int(timeline.get("duration_ms") or 0)

    for index, operation in enumerate(operations):
        op_type = operation.get("type")
        if op_type not in SUPPORTED_OPERATIONS:
            errors.append(f"operation[{index}] unsupported type: {op_type}")
            continue

        if op_type == "DELETE_RANGE":
            start_ms = int(operation.get("start_ms", -1))
            end_ms = int(operation.get("end_ms", -1))
            if start_ms < 0 or end_ms <= start_ms:
                errors.append(f"operation[{index}] DELETE_RANGE requires start_ms < end_ms")
            if duration and end_ms > duration:
                errors.append(f"operation[{index}] DELETE_RANGE exceeds timeline duration")
            ranges.append((start_ms, end_ms))

        if op_type == "SET_VOLUME":
            volume = float(operation.get("volume", -1))
            if volume < 0 or volume > 2:
                errors.append(f"operation[{index}] SET_VOLUME requires 0 <= volume <= 2")

        if op_type == "INSERT_BROLL_OVERLAY":
            if not operation.get("asset_id"):
                errors.append(f"operation[{index}] INSERT_BROLL_OVERLAY requires asset_id")
            if int(operation.get("duration_ms", 0)) <= 0:
                errors.append(f"operation[{index}] INSERT_BROLL_OVERLAY requires duration_ms > 0")

        if op_type == "UPDATE_SUBTITLE" and not operation.get("cue_id"):
            errors.append(f"operation[{index}] UPDATE_SUBTITLE requires cue_id")

    for left_index, left in enumerate(ranges):
        for right in ranges[left_index + 1 :]:
            if left[0] < right[1] and right[0] < left[1]:
                errors.append("DELETE_RANGE operations must not overlap")
    return errors
