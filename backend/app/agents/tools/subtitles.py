from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext
from app.agents.tools.schema import AgentTool


def build_subtitle_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("get_project_subtitles")
    async def get_project_subtitles(
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 80,
    ) -> dict:
        """读取当前时间线中的字幕 cues。字幕纠错、断句、翻译、按文字定位时间点时调用。"""
        cues = context.subtitle_cues()
        if start_ms is not None:
            cues = [cue for cue in cues if int(cue.get("end_ms") or 0) >= int(start_ms)]
        if end_ms is not None:
            cues = [cue for cue in cues if int(cue.get("start_ms") or 0) <= int(end_ms)]
        return {"ok": True, "count": len(cues), "cues": cues[:limit]}

    return [get_project_subtitles]
