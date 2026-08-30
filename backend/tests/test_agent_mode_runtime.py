from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.modes.runtime import run_mode_coordinator
from app.agents.modes.schema import AgentMode, DelegateSpec


class FakeSpecialist:
    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "messages": [
                *state["messages"],
                AIMessage(content='{"summary":"专业分析已完成","operations":[]}'),
            ]
        }


def create_fake_specialist(_toolbox: Any) -> FakeSpecialist:
    return FakeSpecialist()


def agent_state() -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content="分析当前素材")],
        "project_id": "test-project",
        "project_dir": ".",
        "video_type": "TALKING_HEAD",
        "timeline_version": 0,
        "timeline": {"duration_ms": 1000, "tracks": []},
        "assets": [],
        "agent_outputs": {},
        "trace": [],
        "usage_records": [],
        "route_history": [],
    }


@pytest.mark.asyncio
async def test_coordinator_continues_when_first_reply_does_not_delegate() -> None:
    calls = 0

    def create_coordinator(tools: list[Any]) -> Any:
        delegate = next(tool for tool in tools if tool.name == "delegate_to_test_specialist")

        class FakeCoordinator:
            async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
                nonlocal calls
                calls += 1
                if calls == 2:
                    await delegate.ainvoke({"task": "完成专业分析"})
                completion = (
                    '{"summary":"检查完成","creative_direction":"",'
                    '"needs_review":false,"task_status":"completed",'
                    '"execution_mode":"delegated","executed_agents":["test_specialist"]}'
                    if calls == 2
                    else (
                        '{"summary":"检查完成","creative_direction":"",'
                        '"needs_review":false,"task_status":"needs_action",'
                        '"execution_mode":"direct","executed_agents":[]}'
                    )
                )
                return {
                    "messages": [
                        *state["messages"],
                        AIMessage(content=completion),
                    ]
                }

        return FakeCoordinator()

    mode = AgentMode(
        video_type="TALKING_HEAD",
        label="口播",
        coordinator_name="talking_head_director",
        coordinator_factory=create_coordinator,
        delegates=(
            DelegateSpec(
                "delegate_to_test_specialist",
                "test_specialist",
                "执行测试专业分析。",
                create_fake_specialist,
            ),
        ),
    )

    result = await run_mode_coordinator(agent_state(), mode)

    assert calls == 2
    assert result["agent_outputs"]["test_specialist"]["summary"] == "专业分析已完成"
    assert any(step["title"] == "导演 Agent 继续自主推理" for step in result["trace"])


@pytest.mark.asyncio
async def test_coordinator_does_not_claim_completion_without_delegation() -> None:
    calls = 0

    def create_coordinator(_tools: list[Any]) -> Any:
        class FakeCoordinator:
            async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
                nonlocal calls
                calls += 1
                return {
                    "messages": [
                        *state["messages"],
                        AIMessage(
                            content=(
                                '{"summary":"接下来将调用专业 Agent",'
                                '"creative_direction":"","needs_review":false,'
                                '"task_status":"needs_action","execution_mode":"direct",'
                                '"executed_agents":[]}'
                            )
                        ),
                    ]
                }

        return FakeCoordinator()

    mode = AgentMode(
        video_type="TALKING_HEAD",
        label="口播",
        coordinator_name="talking_head_director",
        coordinator_factory=create_coordinator,
        delegates=(
            DelegateSpec(
                "delegate_to_test_specialist",
                "test_specialist",
                "执行测试专业分析。",
                create_fake_specialist,
            ),
        ),
    )

    result = await run_mode_coordinator(agent_state(), mode)

    assert calls == 2
    assert result["agent_outputs"] == {}
    assert "本轮未应用分析或剪辑" in result["reply"]


@pytest.mark.asyncio
async def test_coordinator_can_finish_creative_discussion_directly() -> None:
    calls = 0

    def create_coordinator(_tools: list[Any]) -> Any:
        class FakeCoordinator:
            async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
                nonlocal calls
                calls += 1
                return {
                    "messages": [
                        *state["messages"],
                        AIMessage(
                            content=(
                                '{"summary":"建议采用倒叙开场","creative_direction":"先展示结果",'
                                '"needs_review":false,"task_status":"completed",'
                                '"execution_mode":"direct","executed_agents":[]}'
                            )
                        ),
                    ]
                }

        return FakeCoordinator()

    mode = AgentMode(
        video_type="TALKING_HEAD",
        label="口播",
        coordinator_name="talking_head_director",
        coordinator_factory=create_coordinator,
        delegates=(
            DelegateSpec(
                "delegate_to_test_specialist",
                "test_specialist",
                "执行测试专业分析。",
                create_fake_specialist,
            ),
        ),
    )

    result = await run_mode_coordinator(agent_state(), mode)

    assert calls == 1
    assert result["agent_outputs"] == {}
    assert result["reply"] == "建议采用倒叙开场 先展示结果"


@pytest.mark.asyncio
async def test_coordinator_stops_and_requests_clarification() -> None:
    calls = 0

    def create_coordinator(_tools: list[Any]) -> Any:
        class FakeCoordinator:
            async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
                nonlocal calls
                calls += 1
                return {
                    "messages": [
                        *state["messages"],
                        AIMessage(
                            content=(
                                '{"summary":"需要先明确剪辑目标。","creative_direction":"",'
                                '"needs_review":false,"clarifying_question":'
                                '"你希望我只分析问题，还是直接生成整条视频的粗剪方案？",'
                                '"task_status":"needs_clarification","execution_mode":"direct",'
                                '"executed_agents":[]}'
                            )
                        ),
                    ]
                }

        return FakeCoordinator()

    mode = AgentMode(
        video_type="TALKING_HEAD",
        label="口播",
        coordinator_name="talking_head_director",
        coordinator_factory=create_coordinator,
        delegates=(
            DelegateSpec(
                "delegate_to_test_specialist",
                "test_specialist",
                "执行测试专业分析。",
                create_fake_specialist,
            ),
        ),
    )

    result = await run_mode_coordinator(agent_state(), mode)

    assert calls == 1
    assert result["agent_outputs"] == {}
    assert result["awaiting_user"] is True
    assert "你希望我只分析问题" in result["reply"]
    assert result["trace"][-1]["title"] == "口播导演 Agent 等待用户明确需求"
