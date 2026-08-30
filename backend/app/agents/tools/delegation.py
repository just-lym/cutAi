from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool

from app.agents.base import normalize_operations
from app.agents.modes.schema import DelegateSpec
from app.agents.runtime import rendered_files_from_tool_trace, run_agent
from app.agents.tools import AgentToolbox
from app.agents.tools.schema import AgentTool


@dataclass
class DelegationCollector:
    outputs: dict[str, Any] = field(default_factory=dict)
    usage_records: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)


def _output_key(agent_name: str, outputs: dict[str, Any]) -> str:
    existing = [key for key in outputs if key == agent_name or key.startswith(f"{agent_name}:")]
    return agent_name if not existing else f"{agent_name}:{len(existing) + 1}"


async def _delegate_to_agent(
    state: dict[str, Any],
    toolbox: AgentToolbox,
    collector: DelegationCollector,
    delegate: DelegateSpec,
    task: str,
    coordinator_name: str,
) -> dict[str, Any]:
    delegated_state = {
        **state,
        "delegated_task": task,
        "agent_outputs": {**state.get("agent_outputs", {}), **collector.outputs},
    }
    try:
        response, usage_records, tool_calls = await run_agent(
            delegated_state,
            delegate.agent_name,
            delegate.factory(toolbox),
            toolbox,
        )
    except Exception as exc:  # noqa: BLE001 - delegate tools return failures as observations.
        response, usage_records, tool_calls = (
            {"summary": f"{delegate.agent_name} 执行失败：{type(exc).__name__}: {exc}"},
            [],
            [],
        )

    output = {
        "summary": str(response.get("summary") or f"{delegate.agent_name} 完成。"),
        "operations": normalize_operations(response.get("operations")),
        "insertions": response.get("insertions") if isinstance(response.get("insertions"), list) else [],
        "rendered_files": rendered_files_from_tool_trace(tool_calls),
        "tool_calls": tool_calls,
        "delegated_task": task,
    }
    key = _output_key(delegate.agent_name, collector.outputs)
    collector.outputs[key] = output
    collector.usage_records.extend(usage_records)
    collector.trace.append(
        {
            "title": f"{coordinator_name} 委托 {delegate.agent_name}",
            "detail": output["summary"],
            "data": {
                "task": task,
                "agent": delegate.agent_name,
                "operation_count": len(output["operations"]),
                "rendered_files": output["rendered_files"],
                "tool_calls": tool_calls,
            },
        }
    )
    return {"ok": True, "agent": delegate.agent_name, "output_key": key, **output}


def _build_delegation_tool(
    state: dict[str, Any],
    toolbox: AgentToolbox,
    collector: DelegationCollector,
    delegate: DelegateSpec,
    coordinator_name: str,
) -> AgentTool:
    async def run_delegate(task: str) -> dict:
        return await _delegate_to_agent(
            state,
            toolbox,
            collector,
            delegate,
            task,
            coordinator_name,
        )

    return tool(delegate.tool_name, description=delegate.description)(run_delegate)


def build_delegation_tools(
    state: dict[str, Any],
    toolbox: AgentToolbox,
    collector: DelegationCollector,
    delegates: tuple[DelegateSpec, ...],
    coordinator_name: str,
) -> list[AgentTool]:
    return [
        _build_delegation_tool(state, toolbox, collector, delegate, coordinator_name)
        for delegate in delegates
    ]


__all__ = ["DelegationCollector", "build_delegation_tools"]
