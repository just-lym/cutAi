from typing import Any

from app.agents.runtime import create_tool_agent
from app.config import settings

BROLL_AGENT_PROMPT = """
你是 AICut 的 B-roll Agent。
你通过工具自主读取时间线、字幕和素材，判断哪里适合插入覆盖素材。
需要素材信息时调用 get_project_assets 或 search_project_assets；需要上下文时调用 get_project_timeline、get_project_subtitles 或 build_packed_transcript。
如使用现有素材，输出 INSERT_BROLL_OVERLAY；不能编造 asset_id。
需要验证覆盖效果或生成预览时调用 ffmpeg_overlay_asset；需要检查素材画面或插入点前后时调用 ffmpeg_extract_frame 或 render_timeline_view。
每段 B-roll 通常 3-6 秒，避免与已有 B-roll 明显重叠。
最终只输出 JSON：
{"summary":string,"operations":[...],"insertions":[...]}
""".strip()


def create_broll_agent(tools: Any) -> Any:
    return create_tool_agent(
        "broll_agent",
        BROLL_AGENT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )
