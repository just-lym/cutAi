from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool

from app.agents.base import normalize_operations
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
    agent_name: str,
    task: str,
    create_agent: Callable[[Any], Any],
) -> dict[str, Any]:
    delegated_state = {
        **state,
        "delegated_task": task,
        "agent_outputs": {**state.get("agent_outputs", {}), **collector.outputs},
    }
    try:
        response, usage_records, tool_calls = await run_agent(
            delegated_state,
            agent_name,
            create_agent(toolbox),
            toolbox,
        )
    except Exception as exc:  # noqa: BLE001 - delegate tools return failures as observations.
        response, usage_records, tool_calls = (
            {"summary": f"{agent_name} 执行失败：{type(exc).__name__}: {exc}"},
            [],
            [],
        )

    output = {
        "summary": str(response.get("summary") or f"{agent_name} 完成。"),
        "operations": normalize_operations(response.get("operations")),
        "insertions": response.get("insertions") if isinstance(response.get("insertions"), list) else [],
        "rendered_files": rendered_files_from_tool_trace(tool_calls),
        "tool_calls": tool_calls,
        "delegated_task": task,
    }
    key = _output_key(agent_name, collector.outputs)
    collector.outputs[key] = output
    collector.usage_records.extend(usage_records)
    collector.trace.append(
        {
            "title": f"Main Agent 委托 {agent_name}",
            "detail": output["summary"],
            "data": {
                "task": task,
                "operation_count": len(output["operations"]),
                "rendered_files": output["rendered_files"],
                "tool_calls": tool_calls,
            },
        }
    )
    return {"ok": True, "agent": agent_name, "output_key": key, **output}


def build_delegation_tools(
    state: dict[str, Any],
    toolbox: AgentToolbox,
    collector: DelegationCollector,
) -> list[AgentTool]:
    from app.agents.audio_agent import create_audio_agent
    from app.agents.broll_agent import create_broll_agent
    from app.agents.subtitle_agent import create_subtitle_agent
    from app.agents.video_agent import create_video_agent

    @tool("delegate_to_audio_agent")
    async def delegate_to_audio_agent(task: str) -> dict:
        """把静音检测、停顿裁剪、音量、淡入淡出等声音相关任务委托给 Audio Agent。"""
        return await _delegate_to_agent(state, toolbox, collector, "audio_agent", task, create_audio_agent)

    @tool("delegate_to_video_agent")
    async def delegate_to_video_agent(task: str) -> dict:
        """把截取、删除区间、转码预览、抽帧等视频处理任务委托给 Video Agent。"""
        return await _delegate_to_agent(state, toolbox, collector, "video_agent", task, create_video_agent)

    @tool("delegate_to_subtitle_agent")
    async def delegate_to_subtitle_agent(task: str) -> dict:
        """把字幕读取、纠错、断句和时间码检查任务委托给 Subtitle Agent。"""
        return await _delegate_to_agent(
            state,
            toolbox,
            collector,
            "subtitle_agent",
            task,
            create_subtitle_agent,
        )

    @tool("delegate_to_broll_agent")
    async def delegate_to_broll_agent(task: str) -> dict:
        """把 B-roll 位置判断、素材选择、覆盖预览等画面增强任务委托给 B-roll Agent。"""
        return await _delegate_to_agent(state, toolbox, collector, "broll_agent", task, create_broll_agent)

    return [
        delegate_to_audio_agent,
        delegate_to_video_agent,
        delegate_to_subtitle_agent,
        delegate_to_broll_agent,
    ]


__all__ = ["DelegationCollector", "build_delegation_tools"]
