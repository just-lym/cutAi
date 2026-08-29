from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.base import effective_duration_ms
from app.agents.main_agent import route_after_main, run_main_node
from app.agents.review_agent import run_review_node
from app.agents.state import AgentState


def build_initial_state(
    content: str,
    project_id: str,
    project_dir: str,
    timeline_version: int,
    timeline: dict[str, Any],
    assets: list[dict[str, Any]],
) -> AgentState:
    return {
        "messages": [HumanMessage(content=content)],
        "project_id": project_id,
        "project_dir": project_dir,
        "timeline_version": timeline_version,
        "timeline": timeline,
        "assets": assets,
        "edit_plans": None,
        "agent_outputs": {},
        "awaiting_user": False,
        "total_costs": 0.0,
        "trace": [
            {
                "title": "初始化 AgentState",
                "detail": "已创建任务状态，准备进入 Main Creative Agent 自主分析。",
                "data": {
                    "project_id": project_id,
                    "timeline_version": timeline_version,
                    "timeline_duration_ms": int(timeline.get("duration_ms") or 0),
                    "effective_duration_ms": effective_duration_ms(timeline, assets),
                    "asset_count": len(assets),
                },
            }
        ],
        "route_history": [],
        "reply": "",
        "usage_records": [],
    }


def build_agentic_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("main_agent", run_main_node)
    graph.add_node("review", run_review_node)
    graph.set_entry_point("main_agent")
    graph.add_conditional_edges(
        "main_agent",
        route_after_main,
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
):
    initial_state = build_initial_state(content, project_id, project_dir, timeline_version, timeline, assets)
    graph = build_agentic_graph()
    async for state in graph.astream(initial_state, {"recursion_limit": 12}, stream_mode="values"):
        yield state
