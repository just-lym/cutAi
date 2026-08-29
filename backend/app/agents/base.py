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
