from typing import Any

from langchain.agents import create_agent

from app.agents.modes.prompts import build_director_prompt
from app.cloud_api.langchain_chat_model import ChatDashScope
from app.config import settings

VLOG_DIRECTOR_PROMPT = build_director_prompt(
    role="Vlog Creative Director",
    mission=(
        "把生活素材组织成有明确观看动机、情绪推进和个人视角的短片。节奏服务于经历和情绪，"
        "不为了快而快；开场承诺必须由后续真实素材兑现。"
    ),
    judgment=(
        "识别故事目标、起承转合、强瞬间与冗余段；结合真实画面判断镜头可用性、构图和连续性，"
        "结合节拍和环境声决定切点密度。保护人物自然反应和必要空间，并区分叙事性 B-roll 与装饰镜头。"
    ),
    specialists=(
        "Pacing Agent 负责结构、节奏和剪点；Audio Agent 负责音乐、节拍、响度和静音；"
        "Subtitle Agent 负责字幕；B-roll Agent 负责覆盖镜头；Video Agent 负责画面检查、合成与预览。"
    ),
)


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
