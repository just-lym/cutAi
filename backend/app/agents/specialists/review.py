from typing import Any

from app.agents.base import (
    collect_operations,
    normalize_operations,
    toolbox,
    trace,
    valid_operations,
)
from app.agents.runtime import create_tool_agent, run_agent
from app.agents.state import AgentState
from app.config import settings

REVIEW_AGENT_PROMPT = """
你是 AICut 的 Review Agent。
你负责汇总 specialist 输出，调用 validate_edit_operations 校验，生成最终 EditPlan。
必须先看输入里的 candidate_operations，再调用 validate_edit_operations。
不要输出校验失败的操作。没有可用操作时返回空 operations。
最终只输出 JSON：
{"plan":{"summary":string,"operations":[...],"conflicts":[...],"requires_user_approval":boolean}}
""".strip()


def create_review_agent(tools: Any) -> Any:
    return create_tool_agent(
        "review",
        REVIEW_AGENT_PROMPT,
        tools,
        settings.cloud.review_model or settings.cloud.agent_model,
    )


def _fallback_response(
    error: Exception,
    operations: list[dict[str, Any]],
    conflicts: list[str],
) -> dict[str, Any]:
    return {
        "plan": {
            "summary": f"Review Agent 执行失败，已使用本地校验结果：{type(error).__name__}: {error}",
            "operations": operations,
            "conflicts": conflicts,
            "requires_user_approval": bool(operations),
        }
    }


async def run_review_node(state: AgentState) -> AgentState:
    tools = toolbox(state)
    proposed_operations = collect_operations(state.get("agent_outputs", {}))
    operations, deterministic_conflicts = valid_operations(proposed_operations, state.get("timeline", {}))
    try:
        response, usage_records, tool_calls = await run_agent(
            {
                **state,
                "agent_outputs": {
                    **state.get("agent_outputs", {}),
                    "candidate_operations": {"operations": operations, "conflicts": deterministic_conflicts},
                },
            },
            "review",
            create_review_agent(tools),
            tools,
        )
    except Exception as exc:  # noqa: BLE001 - agent failures fall back to local validation.
        response, usage_records, tool_calls = _fallback_response(exc, operations, deterministic_conflicts), [], []

    plan = response.get("plan") if isinstance(response.get("plan"), dict) else {}
    operations = normalize_operations(plan.get("operations")) or operations
    operations, review_conflicts = valid_operations(operations, state.get("timeline", {}))
    conflicts = [
        *deterministic_conflicts,
        *review_conflicts,
        *[str(item) for item in plan.get("conflicts", []) if item],
    ]
    summary = str(plan.get("summary") or f"Review Agent 合并出 {len(operations)} 条编辑建议。")

    rendered_files = []
    for output in state.get("agent_outputs", {}).values():
        rendered_files.extend(output.get("rendered_files") or [])
    if rendered_files:
        summary += f" FFmpeg 已输出 {len(rendered_files)} 个文件。"

    edit_plan = {
        "summary": summary,
        "operations": operations,
        "conflicts": conflicts,
        "requires_user_approval": bool(operations),
        "rendered_files": rendered_files,
    }
    return {
        "edit_plans": edit_plan,
        "reply": summary,
        "awaiting_user": bool(operations),
        "usage_records": [*state.get("usage_records", []), *usage_records],
        "trace": trace(
            state,
            "Review Agent(create_agent) 执行完成",
            summary,
            {
                "available_tools": tools.names_for("review"),
                "operation_count": len(operations),
                "conflict_count": len(conflicts),
                "rendered_files": rendered_files,
                "tool_calls": tool_calls,
            },
        ),
    }
