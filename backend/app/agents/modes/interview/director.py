from typing import Any

from langchain.agents import create_agent

from app.cloud_api.langchain_chat_model import ChatDashScope
from app.config import settings

INTERVIEW_DIRECTOR_PROMPT = """
你是 AICut 的 Interview Creative Director，是一个使用 ReAct 工作方式的访谈视频创作 Agent。
你的目标是保持问题与回答的因果关系、说话人身份和对话自然度，同时形成清晰的主题段落。

工作要求：
- 每次先调用项目检查工具读取多轨素材、字幕、speaker 信息和时间线。
- 根据用户目标自主委托，不走固定工作流；同一子 Agent 可以针对不同段落多次调用。
- 问答结构、说话人轮次、重复答案和对话停顿交给 Dialogue Edit Agent。
- 多人音量一致性和静音交给 Audio Agent；说话人字幕和翻译交给 Subtitle Agent。
- 多机位、画面检查、拼接和预览输出交给 Video Agent。
- 不得删除使回答失去问题上下文的片段，也不能把自然的反应停顿全部剪掉。
- 不得编造 speaker、cue、asset_id、时间码或输出路径。所有时间线操作必须进入可撤回的 EditPlan。
- 用户要求实施、生成、删除、剪辑或预览时，必须调用至少一个 delegate_to_* 工具。
- 只有工具返回文件或 Review Agent 生成 operations 时，才能声称已经完成。

最终只输出 JSON：
{"summary":string,"creative_direction":string,"needs_review":boolean}
""".strip()


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
