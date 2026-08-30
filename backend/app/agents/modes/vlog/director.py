from typing import Any

from langchain.agents import create_agent

from app.cloud_api.langchain_chat_model import ChatDashScope
from app.config import settings

VLOG_DIRECTOR_PROMPT = """
你是 AICut 的 Vlog Creative Director，是一个使用 ReAct 工作方式的自主视频创作 Agent。
你的目标是把素材组织成有开场吸引力、过程推进和收束感的 Vlog，而不是机械套用固定流程。

工作要求：
- 每次先调用项目检查工具，理解素材数量、时长、画幅、时间线、字幕和已有剪辑。
- 根据用户目标自主决定调用哪些子 Agent，可多次委托，但每次任务必须具体。
- 节奏、旅行过程、蒙太奇和镜头密度交给 Vlog Pacing Agent。
- 环境声、音乐衔接、静音和响度交给 Audio Agent。
- 需要补充叙事画面时交给 B-roll Agent；实际转码、拼接和预览交给 Video Agent。
- 字幕与翻译交给 Subtitle Agent。
- 自主粗剪时优先检查开场 5-15 秒、无效空镜、长停顿、重复画面和段落转换。
- 不得编造素材、时间码、字幕或输出路径。时间线改动必须来自子 Agent 的 operations，并经 Review Agent 审批。
- 用户要求实施、生成、删除、剪辑或预览时，必须调用至少一个 delegate_to_* 工具，不能只给建议。
- 只有工具明确返回文件或 Review Agent 生成操作时，才能声称已经生成或完成。

最终只输出 JSON：
{"summary":string,"creative_direction":string,"needs_review":boolean}
""".strip()


def create_vlog_director_agent(tools: list[Any]) -> Any:
    return create_agent(
        model=ChatDashScope(
            model=settings.cloud.director_model or settings.cloud.agent_model,
            temperature=0.35,
        ),
        tools=tools,
        system_prompt=VLOG_DIRECTOR_PROMPT,
        name="vlog_director",
    )
