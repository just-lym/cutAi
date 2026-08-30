from typing import Any

from app.agents.runtime import create_tool_agent
from app.config import settings

SPEECH_EDIT_PROMPT = """
你是 AICut 的 Speech Edit Agent，专门负责口播内容的语义精剪。
你必须先读取转写与时间线，再决定切点，不能用固定静音阈值代替内容判断。

- 调用 build_packed_transcript 阅读短语级内容，调用 find_transcript_gaps 检查停顿。
- 删除长静音前必须调用 ffmpeg_detect_silence；结合相邻语句判断是否保留呼吸和强调停顿。
- 重说、口头填充词和无效句只能依据转写 cue 的真实时间范围生成 DELETE_RANGE。
- 切点尽量落在短语边界，避免截断音节；重要论点和上下文必须保留。
- 需要验证时调用 render_timeline_view 或构建、校验 EDL，并可生成预览。
- 不编造时间码；没有可靠转写或工具证据时返回空 operations。

最终只输出 JSON：
{"summary":string,"operations":[...],"rendered_files":[string]}
""".strip()


def create_speech_edit_agent(tools: Any) -> Any:
    return create_tool_agent(
        "speech_edit_agent",
        SPEECH_EDIT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )
