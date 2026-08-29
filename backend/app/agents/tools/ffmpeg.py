from app.agents.tools.context import AgentToolContext
from app.agents.tools.ffmpeg_audio import build_ffmpeg_audio_tools
from app.agents.tools.ffmpeg_media import build_ffmpeg_media_tools
from app.agents.tools.ffmpeg_silence import build_ffmpeg_silence_tools
from app.agents.tools.ffmpeg_subtitle import build_ffmpeg_subtitle_tools
from app.agents.tools.ffmpeg_video import build_ffmpeg_video_tools
from app.agents.tools.schema import AgentTool


def build_ffmpeg_tools(context: AgentToolContext) -> list[AgentTool]:
    return [
        *build_ffmpeg_media_tools(context),
        *build_ffmpeg_silence_tools(context),
        *build_ffmpeg_audio_tools(context),
        *build_ffmpeg_video_tools(context),
        *build_ffmpeg_subtitle_tools(context),
    ]
