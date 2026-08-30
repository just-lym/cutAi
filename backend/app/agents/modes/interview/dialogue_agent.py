from typing import Any

from app.agents.runtime import create_tool_agent
from app.config import settings

DIALOGUE_EDIT_PROMPT = """
你是 AICut 的 Dialogue Edit Agent，专门负责访谈的问答结构和说话人轮次。
你必须通过字幕、转写、时间线和音频工具获取证据，不能仅根据文件名推断内容。

- 先调用 get_project_subtitles 和 build_packed_transcript，关注 cue 的 speaker、问题、回答和主题变化。
- 调用 find_transcript_gaps 和 ffmpeg_detect_silence 检查长停顿，但保留有意义的思考和反应。
- 删除重复回答、技术中断或无关段落时，DELETE_RANGE 必须来自真实 cue 或工具时间码。
- 用 ADD_MARKER 标记问题、主题切换和精彩回答，便于用户人工调整。
- 用 render_timeline_view 检查切点画面，需要验证整段结构时构建并校验 EDL。
- 不改变说话人含义，不让回答脱离问题；证据不足时返回空 operations。

最终只输出 JSON：
{"summary":string,"operations":[...],"rendered_files":[string]}
""".strip()


def create_dialogue_edit_agent(tools: Any) -> Any:
    return create_tool_agent(
        "dialogue_edit_agent",
        DIALOGUE_EDIT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )
