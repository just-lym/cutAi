from typing import Any

from langchain.agents import create_agent

from app.agents.modes.prompts import build_director_prompt
from app.cloud_api.langchain_chat_model import ChatDashScope
from app.config import settings

INTERVIEW_DIRECTOR_PROMPT = build_director_prompt(
    role="Interview Creative Director",
    mission=(
        "把访谈剪成观点鲜明、上下文完整、人物可信且持续推进的对话。压缩重复和技术摩擦，"
        "但不歪曲语义，不让回答脱离问题，不把不同说话人的内容错误拼接。"
    ),
    judgment=(
        "保护问答、追问和澄清的逻辑，优先保留新观点、具体案例、情绪变化、分歧与反常识信息。"
        "画面需匹配说话人和反应时机，多人响度保持一致；speaker 证据不足时不得编造身份。"
    ),
    specialists=(
        "Dialogue Edit Agent 负责问答结构、轮次和重复内容；Audio Agent 负责多人响度与静音；"
        "Subtitle Agent 负责说话人字幕；Video Agent 负责多机位检查、拼接、画幅和预览输出。"
    ),
)


def create_interview_director_agent(tools: list[Any]) -> Any:
    return create_agent(
        model=ChatDashScope(
            model=settings.cloud.director_model or settings.cloud.agent_model,
            temperature=0.2,
        ),
        tools=tools,
        system_prompt=INTERVIEW_DIRECTOR_PROMPT,
        name="interview_director",
    )
