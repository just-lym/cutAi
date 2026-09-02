from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.base import effective_duration_ms
from app.agents.modes import get_agent_mode
from app.agents.modes.runtime import route_after_coordinator, run_mode_coordinator
from app.agents.specialists.review import run_review_node
from app.agents.state import AgentState


def build_initial_state(
    content: str,
    project_id: str,
    project_dir: str,
    timeline_version: int,
    timeline: dict[str, Any],
    assets: list[dict[str, Any]],
    video_type: str,
    preferences: dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> AgentState:
    mode = get_agent_mode(video_type)
    return {
        "messages": [HumanMessage(content=content)],
        "project_id": project_id,
        "project_dir": project_dir,
        "video_type": mode.video_type,
        "mode_label": mode.label,
        "coordinator_name": mode.coordinator_name,
        "timeline_version": timeline_version,
        "timeline": timeline,
        "assets": assets,
        "preferences": preferences or {"sample_count": 0, "confidence": 0.0},
        "selection": selection,
        "history": history or [],
        "evidence": {},
        "edit_plans": None,
        "agent_outputs": {},
        "awaiting_user": False,
        "total_costs": 0.0,
        "trace": [
            {
                "title": f"进入{mode.label}多 Agent 模式",
                "detail": f"已加载 {mode.coordinator_name} 和当前模式的专业 Agent 团队。",
                "data": {
                    "project_id": project_id,
                    "timeline_version": timeline_version,
                    "timeline_duration_ms": int(timeline.get("duration_ms") or 0),
                    "effective_duration_ms": effective_duration_ms(timeline, assets),
                    "asset_count": len(assets),
                    "video_type": mode.video_type,
                    "team": list(mode.team),
                    "selection": selection,
                    "preference_confidence": (preferences or {}).get("confidence", 0.0),
                    "history_count": len(history or []),
                },
            }
        ],
        "route_history": [],
        "reply": "",
        "usage_records": [],
    }


def build_agentic_graph(video_type: str = "TALKING_HEAD") -> Any:
    mode = get_agent_mode(video_type)

    async def run_coordinator(state: AgentState) -> AgentState:
        return await run_mode_coordinator(state, mode)

    graph = StateGraph(AgentState)
    graph.add_node(mode.coordinator_name, run_coordinator)
    graph.add_node("review", run_review_node)
    graph.set_entry_point(mode.coordinator_name)
    graph.add_conditional_edges(
        mode.coordinator_name,
        route_after_coordinator,
        {
            "review": "review",
            "end": END,
        },
    )
    graph.add_edge("review", END)
    return graph.compile()


async def stream_agent_graph(
    content: str,
    project_id: str,
    project_dir: str,
    timeline_version: int,
    timeline: dict[str, Any],
    assets: list[dict[str, Any]],
    video_type: str,
    preferences: dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
):
    initial_state = build_initial_state(
        content,
        project_id,
        project_dir,
        timeline_version,
        timeline,
        assets,
        video_type,
        preferences,
        selection,
        history,
    )
    graph = build_agentic_graph(video_type)
    async for state in graph.astream(initial_state, {"recursion_limit": 12}, stream_mode="values"):
        yield state
