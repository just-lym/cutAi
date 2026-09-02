from typing import Any

from langchain.agents import create_agent

from app.agents.modes.prompts import build_director_prompt
from app.cloud_api.langchain_chat_model import ChatDashScope
from app.config import settings

TALKING_HEAD_DIRECTOR_PROMPT = build_director_prompt(
    role="Talking-head Creative Director",
    mission=(
        "把口播剪成观点清楚、表达可信、节奏紧而不赶的内容，让观众尽快理解主题、核心主张、"
        "可信依据和最终结论，同时保留自然表达和人格感。"
    ),
    judgment=(
        "从真实转写识别主张、依据、例子、反驳和结论；删除不增加含义的重说、失误和无效铺垫，"
        "但保护否定、条件、因果与自然呼吸。抽象概念需要画面支持时才使用 B-roll，人声清晰度优先。"
    ),
    specialists=(
        "Speech Edit Agent 负责语义精剪、重说和停顿；Audio Agent 负责人声和静音；"
        "Subtitle Agent 负责断句、纠错和双语；B-roll Agent 负责解释性画面；Video Agent 负责预览和输出。"
    ),
)


def create_talking_head_director_agent(tools: list[Any]) -> Any:
    return create_agent(
        model=ChatDashScope(
            model=settings.cloud.director_model or settings.cloud.agent_model,
            temperature=0.25,
        ),
        tools=tools,
        system_prompt=TALKING_HEAD_DIRECTOR_PROMPT,
        name="talking_head_director",
    )
