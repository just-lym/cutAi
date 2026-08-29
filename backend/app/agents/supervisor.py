from app.agents.base import trace, user_request
from app.agents.intent import recognize_intent
from app.agents.state import AgentState


async def intent_node(state: AgentState) -> AgentState:
    intent = recognize_intent(user_request(state))
    return {
        "intent": intent,
        "trace": trace(
            state,
            "意图识别",
            str(intent.get("reason") or "已识别用户基础操作。"),
            {
                "category": intent.get("category"),
                "operation_types": intent.get("operation_types", []),
                "specialist_agents": intent.get("specialist_agents", []),
                "confidence": intent.get("confidence"),
                "matched_keywords": intent.get("matched_keywords", []),
            },
        ),
    }


async def supervisor_node(state: AgentState) -> AgentState:
    route_history = state.get("route_history", [])
    outputs = state.get("agent_outputs", {})
    intent = state.get("intent", {})
    specialist_agents = list(intent.get("specialist_agents") or [])

    for agent_name in specialist_agents:
        if agent_name not in outputs and agent_name not in route_history:
            return {
                "next": agent_name,
                "route_history": [*route_history, agent_name],
                "trace": trace(
                    state,
                    "Supervisor 调度",
                    f"根据意图识别结果调度 {agent_name}。",
                    {"next": agent_name, "operation_types": intent.get("operation_types", [])},
                ),
            }

    if outputs:
        return {
            "next": "review",
            "route_history": [*route_history, "review"],
            "trace": trace(state, "Supervisor 调度", "专业 Agent 已完成，进入 Review。", {"next": "review"}),
        }

    return {
        "next": "respond",
        "route_history": [*route_history, "respond"],
        "trace": trace(state, "Supervisor 调度", "没有明确可执行剪辑操作，直接回复。", {"next": "respond"}),
    }


def route_next(state: AgentState) -> str:
    return state.get("next", "respond")
