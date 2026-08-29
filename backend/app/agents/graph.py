from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.audio_agent import run_audio_node
from app.agents.base import effective_duration_ms
from app.agents.broll_agent import run_broll_node
from app.agents.respond_agent import respond_node
from app.agents.review_agent import run_review_node
from app.agents.state import AgentState
from app.agents.subtitle_agent import run_subtitle_node
from app.agents.supervisor import intent_node, route_next, supervisor_node
from app.agents.video_agent import run_video_node


def build_supervisor_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("intent", intent_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("subtitle_agent", run_subtitle_node)
    graph.add_node("audio_agent", run_audio_node)
    graph.add_node("broll_agent", run_broll_node)
    graph.add_node("video_agent", run_video_node)
    graph.add_node("review", run_review_node)
    graph.add_node("respond", respond_node)
    graph.set_entry_point("intent")
    graph.add_edge("intent", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "subtitle_agent": "subtitle_agent",
            "audio_agent": "audio_agent",
            "broll_agent": "broll_agent",
            "video_agent": "video_agent",
            "review": "review",
            "respond": "respond",
        },
    )
    graph.add_edge("subtitle_agent", "supervisor")
    graph.add_edge("audio_agent", "supervisor")
    graph.add_edge("broll_agent", "supervisor")
    graph.add_edge("video_agent", "supervisor")
    graph.add_edge("review", END)
    graph.add_edge("respond", END)
    return graph.compile()


async def run_agent_graph(
    content: str,
    project_id: str,
    project_dir: str,
    timeline_version: int,
    timeline: dict[str, Any],
    assets: list[dict[str, Any]],
) -> AgentState:
    initial_state: AgentState = {
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
                "detail": "已创建任务状态，准备进入意图识别和工具型 Agent 调度。",
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
        "intent": {},
    }
    graph = build_supervisor_graph()
    return await graph.ainvoke(initial_state, {"recursion_limit": 12})
