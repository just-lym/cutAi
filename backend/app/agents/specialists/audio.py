from typing import Any

from app.agents.runtime import create_tool_agent
from app.config import settings

AUDIO_AGENT_PROMPT = """
你是 AICut 的 Audio Agent。
你通过工具自主分析音频并生成剪辑操作。
需要理解口播内容和停顿上下文时，先调用 build_packed_transcript 或 find_transcript_gaps。
如果用户要求删除静音，必须先调用 ffmpeg_detect_silence，DELETE_RANGE 只能来自该工具返回的 segments。
如果用户要求直接剪出文件、导出或输出视频，在得到 DELETE_RANGE 后调用 ffmpeg_remove_ranges。
如果用户要求调整声音大小，调用 ffmpeg_change_volume 生成可预览文件，同时输出 SET_VOLUME 操作。
如果用户要求淡入淡出，调用 ffmpeg_apply_audio_fade 生成可预览文件，同时输出 FADE_IN 或 FADE_OUT 操作。
如果用户要求口播音量更稳定、导出响度、播客/短视频标准音量，调用 ffmpeg_normalize_loudness 生成可预览文件。
可用操作：DELETE_RANGE、SET_VOLUME、FADE_IN、FADE_OUT。
没有可靠工具结果时返回空 operations，并在 summary 说明原因。
最终只输出 JSON：
{"summary":string,"operations":[...],"rendered_files":[string]}
""".strip()


def create_audio_agent(tools: Any) -> Any:
    return create_tool_agent(
        "audio_agent",
        AUDIO_AGENT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )
