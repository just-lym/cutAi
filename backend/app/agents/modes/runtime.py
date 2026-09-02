import json
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.base import compact_history, toolbox, user_request
from app.agents.modes.evidence import collect_preflight_evidence as _collect_preflight_evidence
from app.agents.modes.schema import AgentMode
from app.agents.runtime import final_ai_json, message_tool_trace, message_usage_records
from app.agents.state import AgentState
from app.agents.tools.delegation import DelegationCollector, build_delegation_tools


def _fallback_response(mode: AgentMode, error: Exception) -> dict[str, Any]:
    return {
        "summary": f"{mode.label}导演 Agent 执行失败：{type(error).__name__}: {error}",
        "creative_direction": "当前没有生成可应用的剪辑计划。",
        "needs_review": False,
        "clarifying_question": "",
        "task_status": "blocked",
        "execution_mode": "direct",
        "executed_agents": [],
    }


def _completion_is_valid(response: dict[str, Any], collector: DelegationCollector) -> bool:
    status = str(response.get("task_status") or "").lower()
    execution_mode = str(response.get("execution_mode") or "").lower()
    declared_agents = {
        str(agent_name)
        for agent_name in response.get("executed_agents") or []
        if agent_name
    }
    actual_agents = {key.split(":", 1)[0] for key in collector.outputs}

    if status == "needs_clarification":
        question = str(response.get("clarifying_question") or "").strip()
        return bool(question) and execution_mode == "direct" and not actual_agents and not declared_agents
    if status == "blocked":
        return execution_mode == "direct" and not actual_agents and not declared_agents
    if status != "completed":
        return False
    if execution_mode == "direct":
        return not actual_agents and not declared_agents
    if execution_mode != "delegated" or not actual_agents:
        return False
    return not declared_agents or declared_agents.issubset(actual_agents)


async def run_mode_coordinator(state: AgentState, mode: AgentMode) -> AgentState:
    tools = toolbox(state)
    request = user_request(state)
    evidence, evidence_trace, evidence_usage = await _collect_preflight_evidence(state, tools, request)
    state = {**state, "evidence": evidence}
    collector = DelegationCollector()
    coordinator_tools = [
        *[tools.get(tool_name) for tool_name in tools.names_for(mode.coordinator_name)],
        *build_delegation_tools(
            state,
            tools,
            collector,
            mode.delegates,
            mode.coordinator_name,
        ),
    ]
    payload = {
        "user_request": request,
        "project_id": state.get("project_id"),
        "video_type": mode.video_type,
        "creative_mode": mode.label,
        "team": list(mode.team),
        "selection": state.get("selection"),
        "learned_preferences": state.get("preferences", {}),
        "history": compact_history(state.get("history") or [], limit=12),
        "evidence": evidence,
        "base_timeline_version": state.get("timeline_version"),
        "available_tools": [agent_tool.name for agent_tool in coordinator_tools],
        "tool_policy": (
            "你是自主 ReAct 创作 Agent。根据项目证据自由决定直接回答、调用工具或委托专业 Agent；"
            "没有固定步骤和关键词路由。若指令存在会实质改变剪辑结果的歧义，先提出澄清问题，"
            "不要调用专业 Agent 或生成剪辑操作。"
        ),
        "required_final_output": {
            "summary": "string",
            "creative_direction": "string",
            "needs_review": "boolean",
            "clarifying_question": "string，只有需要用户明确需求时填写",
            "task_status": "completed | blocked | needs_clarification | needs_action",
            "execution_mode": "direct | delegated",
            "executed_agents": ["实际已返回结果的 agent 名称"],
        },
    }
    completion_trace: list[dict[str, Any]] = []
    try:
        coordinator = mode.coordinator_factory(coordinator_tools)
        result = await coordinator.ainvoke(
            {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
        )
        messages = list(result.get("messages") or [])
        response = final_ai_json(messages)

        if not _completion_is_valid(response, collector):
            completion_trace.append(
                {
                    "title": "导演 Agent 继续自主推理",
                    "detail": "完成状态与实际工具证据尚不一致，正在继续同一轮 ReAct 执行。",
                    "data": {
                        "agent": mode.coordinator_name,
                        "video_type": mode.video_type,
                        "task_status": response.get("task_status"),
                        "execution_mode": response.get("execution_mode"),
                        "actual_agents": list(collector.outputs.keys()),
                        "retry": 1,
                    },
                }
            )
            continuation = HumanMessage(
                content=(
                    "你刚才返回的完成状态与实际工具调用证据不一致，当前任务不能结束。"
                    "请继续同一轮 ReAct 推理，自主决定直接给出完整创意回答，或调用任意必要工具和子 Agent。"
                    "不要遵循固定步骤，也不要描述尚未执行的未来计划。直接回答时返回 "
                    "task_status=completed、execution_mode=direct；完成专业委托后返回 "
                    "task_status=completed、execution_mode=delegated，并列出实际执行的 Agent；"
                    "缺少必要素材时返回 task_status=blocked；用户目标存在实质歧义且尚未调用子 Agent 时，"
                    "返回 task_status=needs_clarification，并在 clarifying_question 中提出最少且具体的问题。"
                )
            )
            result = await coordinator.ainvoke({"messages": [*messages, continuation]})
            messages = list(result.get("messages") or [])
            response = final_ai_json(messages)

        usage_records = message_usage_records(mode.coordinator_name, messages)
        tool_calls = message_tool_trace(messages)

        if not _completion_is_valid(response, collector):
            collector.outputs.clear()
            response = {
                "summary": f"{mode.label}导演 Agent 未能给出与执行证据一致的完成结果，本轮未应用分析或剪辑。",
                "creative_direction": "系统没有把未完成的后续计划标记为已完成。",
                "needs_review": False,
                "clarifying_question": "",
                "task_status": "blocked",
                "execution_mode": "direct",
                "executed_agents": [],
            }
    except Exception as exc:  # noqa: BLE001 - coordinator failures return a usable response.
        response, usage_records, tool_calls = _fallback_response(mode, exc), [], []

    summary = str(response.get("summary") or f"{mode.label}导演 Agent 已完成。")
    creative_direction = str(response.get("creative_direction") or "")
    clarifying_question = str(response.get("clarifying_question") or "").strip()
    detail = " ".join(
        item for item in (summary, creative_direction, clarifying_question) if item
    )
    task_status = str(response.get("task_status") or "completed").lower()
    awaiting_clarification = task_status == "needs_clarification"
    outputs = {**state.get("agent_outputs", {}), **collector.outputs}
    if awaiting_clarification:
        trace_title = f"{mode.label}导演 Agent 等待用户明确需求"
    elif task_status == "blocked":
        trace_title = f"{mode.label}导演 Agent 执行受阻"
    else:
        trace_title = f"{mode.label}导演 Agent(create_agent) 执行完成"
    return {
        "evidence": evidence,
        "agent_outputs": outputs,
        "reply": detail,
        "awaiting_user": awaiting_clarification,
        "coordinator_name": mode.coordinator_name,
        "usage_records": [
            *state.get("usage_records", []),
            *evidence_usage,
            *usage_records,
            *collector.usage_records,
        ],
        "route_history": [*state.get("route_history", []), mode.coordinator_name],
        "trace": [
            *state.get("trace", []),
            *evidence_trace,
            *completion_trace,
            *collector.trace,
            {
                "title": trace_title,
                "detail": detail,
                "data": {
                    "agent": mode.coordinator_name,
                    "video_type": mode.video_type,
                    "task_status": task_status,
                    "awaiting_user": awaiting_clarification,
                    "team": list(mode.team),
                    "available_tools": [agent_tool.name for agent_tool in coordinator_tools],
                    "delegated_agents": list(collector.outputs.keys()),
                    "tool_calls": tool_calls,
                },
            },
        ],
    }


def route_after_coordinator(state: AgentState) -> str:
    return "review" if state.get("agent_outputs") else "end"
