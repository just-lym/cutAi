from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext
from app.agents.tools.schema import AgentTool
from app.tools.timeline_tools import validate_edit_plan


def build_timeline_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("get_project_timeline")
    async def get_project_timeline(include_tracks: bool = False, max_items: int = 30) -> dict:
        """读取当前项目时间线。需要了解轨道、片段、整体时长、已有 B-roll 或音频布局时调用。"""
        tracks = context.tracks()
        result: dict = {
            "ok": True,
            "project_id": context.project_id,
            "timeline_version": context.timeline_version,
            "duration_ms": int(context.timeline.get("duration_ms") or 0),
            "effective_duration_ms": context.effective_duration_ms(),
            "width": context.timeline.get("width"),
            "height": context.timeline.get("height"),
            "frame_rate": context.timeline.get("frame_rate"),
            "track_count": len(tracks),
            "clip_count": sum(len(track.get("clips", [])) for track in tracks),
            "subtitle_count": len(context.subtitle_cues()),
        }
        if include_tracks:
            result["tracks"] = [
                {
                    "id": track.get("id"),
                    "type": track.get("type"),
                    "name": track.get("name"),
                    "clips": list(track.get("clips") or [])[:max_items],
                    "cues": list(track.get("cues") or [])[:max_items],
                }
                for track in tracks
            ]
        return result

    @tool("validate_edit_operations")
    async def validate_edit_operations(operations: list[dict]) -> dict:
        """校验候选编辑操作是否合法。Review Agent 生成最终计划前必须调用。"""
        if not isinstance(operations, list):
            return {"ok": False, "errors": ["operations must be an array"]}
        errors = validate_edit_plan(operations, context.timeline)
        return {"ok": not errors, "errors": errors, "operation_count": len(operations)}

    return [get_project_timeline, validate_edit_operations]
