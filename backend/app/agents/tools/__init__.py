from typing import Any

from app.agents.tools.assets import build_asset_tools
from app.agents.tools.context import AgentToolContext
from app.agents.tools.ffmpeg import build_ffmpeg_tools
from app.agents.tools.schema import AgentTool
from app.agents.tools.subtitles import build_subtitle_tools
from app.agents.tools.timeline import build_timeline_tools


class AgentToolbox:
    def __init__(
        self,
        project_id: str,
        project_dir: str,
        timeline_version: int | None,
        timeline: dict[str, Any],
        assets: list[dict[str, Any]],
    ) -> None:
        self.context = AgentToolContext(project_id, project_dir, timeline_version, timeline, assets)
        tools = [
            *build_timeline_tools(self.context),
            *build_asset_tools(self.context),
            *build_subtitle_tools(self.context),
            *build_ffmpeg_tools(self.context),
        ]
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> AgentTool:
        return self._tools[name]

    async def run(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            return await tool.ainvoke(arguments or {})
        except Exception as exc:  # noqa: BLE001 - tools report failures to agents.
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def names_for(self, agent_name: str) -> list[str]:
        common = ["get_project_timeline", "get_project_assets", "get_project_subtitles"]
        if agent_name == "subtitle_agent":
            return [*common, "ffmpeg_probe_asset"]
        if agent_name == "audio_agent":
            return [*common, "ffmpeg_probe_asset", "ffmpeg_detect_silence", "ffmpeg_remove_ranges"]
        if agent_name == "broll_agent":
            return [*common, "search_project_assets", "ffmpeg_probe_asset", "ffmpeg_cut_segment"]
        if agent_name == "video_agent":
            return [*common, "ffmpeg_probe_asset", "ffmpeg_cut_segment", "ffmpeg_remove_ranges"]
        if agent_name == "review":
            return [*common, "validate_edit_operations"]
        return common


__all__ = ["AgentTool", "AgentToolContext", "AgentToolbox"]
