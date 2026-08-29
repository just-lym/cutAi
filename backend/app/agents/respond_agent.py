from app.agents.base import timeline_summary, trace, user_request
from app.agents.state import AgentState


async def respond_node(state: AgentState) -> AgentState:
    reply = "我没有识别到明确的剪辑操作。你可以说：删除静音、调整音量、检查字幕、插入 B-roll，或直接剪出文件。"
    return {
        "reply": reply,
        "edit_plans": None,
        "awaiting_user": False,
        "trace": trace(
            state,
            "Respond Agent 执行完成",
            reply,
            {
                "request": user_request(state),
                "timeline": timeline_summary(state.get("timeline", {}), state.get("assets", [])),
            },
        ),
    }
