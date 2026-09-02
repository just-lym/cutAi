import json
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.state import AgentState
from app.agents.tools import AgentToolbox
from app.tools.timeline_tools import SUPPORTED_OPERATIONS, validate_edit_plan


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def user_request(state: AgentState) -> str:
    messages = state.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return content_text(message.content)
    return ""


def compact_history(
    history: list[dict[str, Any]],
    limit: int = 20,
    character_budget: int = 6000,
) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    remaining = max(500, character_budget)
    for item in reversed(history[-max(1, limit) :]):
        content = " ".join(str(item.get("content") or "").split())
        if not content:
            continue
        content = content[: min(800, remaining)]
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        compact_metadata = {
            key: metadata[key]
            for key in (
                "event",
                "plan_id",
                "operation_types",
                "timeline_version",
                "render_status",
            )
            if key in metadata
        }
        quality_report = metadata.get("quality_report")
        if isinstance(quality_report, dict):
            compact_metadata["quality_report"] = {
                "score": quality_report.get("score"),
                "passed": quality_report.get("passed"),
                "issues": list(quality_report.get("issues") or [])[:5],
            }
        compact.append(
            {
                "role": str(item.get("role") or "system"),
                "content": content,
                "metadata": compact_metadata,
            }
        )
        remaining -= len(content)
        if remaining <= 0:
            break
    return list(reversed(compact))


def trace(
    state: AgentState,
    title: str,
    detail: str,
    data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"title": title, "detail": detail, "data": data or {}}]


def toolbox(state: AgentState) -> AgentToolbox:
    return AgentToolbox(
        project_id=str(state.get("project_id") or ""),
        project_dir=str(state.get("project_dir") or ""),
        timeline_version=state.get("timeline_version"),
        timeline=state.get("timeline", {}),
        assets=state.get("assets", []),
        preferences=state.get("preferences", {}),
        selection=state.get("selection"),
    )


def assets_summary(assets: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        asset
        for asset in assets
        if asset.get("processing_status") == "COMPLETED" and asset.get("duration_ms")
    ]
    max_duration_ms = max((int(asset.get("duration_ms") or 0) for asset in completed), default=0)
    return {
        "asset_count": len(assets),
        "completed_media_count": len(completed),
        "max_asset_duration_ms": max_duration_ms,
        "media": [
            {
                "id": asset.get("id"),
                "name": asset.get("original_name"),
                "type": asset.get("type"),
                "duration_ms": asset.get("duration_ms"),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "frame_rate": asset.get("frame_rate"),
            }
            for asset in assets[:20]
        ],
    }


def effective_duration_ms(timeline: dict[str, Any], assets: list[dict[str, Any]]) -> int:
    timeline_duration = int(timeline.get("duration_ms") or 0)
    asset_duration = int(assets_summary(assets)["max_asset_duration_ms"])
    return max(timeline_duration, asset_duration)


def timeline_summary(timeline: dict[str, Any], assets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    asset_list = assets or []
    tracks = timeline.get("tracks", [])
    return {
        "duration_ms": int(timeline.get("duration_ms") or 0),
        "effective_duration_ms": effective_duration_ms(timeline, asset_list),
        "track_count": len(tracks),
        "clip_count": sum(len(track.get("clips", [])) for track in tracks),
        "subtitle_count": sum(len(track.get("cues", [])) for track in tracks),
        "assets": assets_summary(asset_list),
    }


def normalize_operations(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    operations: list[dict[str, Any]] = []
    for item in items[:500]:
        if isinstance(item, dict) and item.get("type") in SUPPORTED_OPERATIONS:
            operations.append(item)
    return operations


def collect_operations(agent_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for output in agent_outputs.values():
        operations.extend(normalize_operations(output.get("operations")))
        for insertion in output.get("insertions") or []:
            if not isinstance(insertion, dict) or not insertion.get("asset_id"):
                continue
            operations.append(
                {
                    "type": "INSERT_BROLL_OVERLAY",
                    "asset_id": insertion["asset_id"],
                    "position_ms": int(insertion.get("position_ms") or 0),
                    "duration_ms": int(insertion.get("duration_ms") or 4000),
                    "context": insertion.get("context") or insertion.get("visual_description") or "",
                }
            )
    return operations


def valid_operations(
    operations: list[dict[str, Any]],
    timeline: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    combined_errors = validate_edit_plan(operations, timeline)
    if not combined_errors:
        return operations, []

    kept: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for operation in operations:
        errors = validate_edit_plan([operation], timeline)
        if errors:
            conflicts.extend(errors)
        else:
            kept.append(operation)
    kept_errors = validate_edit_plan(kept, timeline)
    if kept_errors:
        conflicts.extend(kept_errors)
        return [], conflicts
    return kept, [*combined_errors, *conflicts]


def _operation_scope(
    operation: dict[str, Any], timeline: dict[str, Any]
) -> tuple[int, int] | None:
    op_type = str(operation.get("type") or "")
    if "start_ms" in operation:
        start_ms = int(operation.get("start_ms") or 0)
        if "end_ms" in operation:
            end_ms = int(operation.get("end_ms") or -1)
            return start_ms, end_ms if end_ms >= 0 else int(timeline.get("duration_ms") or start_ms)
        if "duration_ms" in operation:
            return start_ms, start_ms + int(operation.get("duration_ms") or 0)
        return start_ms, start_ms
    if "position_ms" in operation:
        start_ms = int(operation.get("position_ms") or 0)
        return start_ms, start_ms + int(operation.get("duration_ms") or 0)
    if "at_ms" in operation:
        at_ms = int(operation.get("at_ms") or 0)
        return at_ms, at_ms

    clips = {
        str(clip.get("id")): clip
        for track in timeline.get("tracks", [])
        for clip in track.get("clips") or []
        if clip.get("id")
    }
    clip_ids = [
        str(operation[key])
        for key in ("clip_id", "from_clip_id", "to_clip_id")
        if operation.get(key)
    ]
    clip_ranges = [
        (
            int(clips[clip_id].get("timeline_start_ms") or 0),
            int(clips[clip_id].get("timeline_end_ms") or 0),
        )
        for clip_id in clip_ids
        if clip_id in clips
    ]
    if op_type in {"MOVE_CLIP", "DUPLICATE_CLIP"} and clip_ranges:
        duration_ms = clip_ranges[0][1] - clip_ranges[0][0]
        start_ms = int(operation.get("timeline_start_ms") or 0)
        return start_ms, start_ms + duration_ms
    if clip_ranges:
        return min(item[0] for item in clip_ranges), max(item[1] for item in clip_ranges)

    cue_id = str(operation.get("cue_id") or "")
    for track in timeline.get("tracks", []):
        for cue in track.get("cues") or []:
            if str(cue.get("id")) == cue_id:
                return int(cue.get("start_ms") or 0), int(cue.get("end_ms") or 0)
    marker_id = str(operation.get("marker_id") or "")
    for marker in timeline.get("markers", []):
        if str(marker.get("id")) == marker_id:
            at_ms = int(marker.get("at_ms") or 0)
            return at_ms, at_ms
    return None


def constrain_operations_to_selection(
    operations: list[dict[str, Any]],
    timeline: dict[str, Any],
    selection: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not selection:
        return operations, []
    selection_start = int(selection.get("start_ms") or 0)
    selection_end = int(selection.get("end_ms") or 0)
    selected_clip_ids = {str(item) for item in selection.get("clip_ids") or []}
    kept: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for index, operation in enumerate(operations):
        target_clip_ids = {
            str(operation[key])
            for key in ("clip_id", "from_clip_id", "to_clip_id")
            if operation.get(key)
        }
        if target_clip_ids and selected_clip_ids and target_clip_ids.issubset(selected_clip_ids):
            kept.append(operation)
            continue
        scope = _operation_scope(operation, timeline)
        if scope is None:
            conflicts.append(f"operation[{index}] 无法证明位于用户框选范围内，已拦截")
            continue
        if selection_start <= scope[0] and scope[1] <= selection_end:
            kept.append(operation)
            continue
        conflicts.append(
            f"operation[{index}] {operation.get('type')} 范围 {scope[0]}-{scope[1]}ms "
            f"超出用户框选 {selection_start}-{selection_end}ms，已拦截"
        )
    return kept, conflicts
