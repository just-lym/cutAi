from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    project_id: str
    project_dir: str
    timeline_version: int | None
    timeline: dict[str, Any]
    assets: list[dict[str, Any]]
    edit_plans: dict[str, Any] | None
    agent_outputs: dict[str, Any]
    awaiting_user: bool
    total_costs: float
    trace: list[dict[str, Any]]
    route_history: list[str]
    next: str
    reply: str
    usage_records: list[dict[str, Any]]
    delegated_task: str
