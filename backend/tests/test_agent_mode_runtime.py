from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.base import compact_history, constrain_operations_to_selection
from app.agents.modes.runtime import _collect_preflight_evidence, run_mode_coordinator
from app.agents.modes.schema import AgentMode, DelegateSpec
from app.agents.tools.context import AgentToolContext


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
async def test_preflight_runs_project_evidence_and_multimodal_tools() -> None:
    calls: list[str] = []
    asset = {"id": "asset", "type": "VIDEO", "duration_ms": 20000}

    class FakeTools:
        context = SimpleNamespace(
            find_asset=lambda **_kwargs: asset,
            subtitle_cues=list,
        )

        async def run(self, name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            calls.append(name)
            return {"ok": True, "artifact_path": f"{name}.json"}

    state = {**agent_state(), "assets": [asset]}
    evidence, trace, usage = await _collect_preflight_evidence(
        state,
        FakeTools(),
        "看画面和关键帧，听音频节拍，并按语义转写字幕",
    )

    assert set(calls) == {
        "build_packed_transcript",
        "build_timeline_edl",
        "recommend_edit_strategy",
        "render_timeline_view",
        "qwen_vl_inspect_range",
        "ffmpeg_detect_beats",
        "qwen_audio_analyze_range",
        "asr_transcribe_asset",
    }
    assert set(evidence) == {*calls, "profile"}
    assert len(trace) == len(calls)
    assert usage == []


def test_selection_blocks_operations_outside_range() -> None:
    timeline = {
        "tracks": [
            {
                "id": "video-main",
                "clips": [
                    {"id": "inside", "timeline_start_ms": 1000, "timeline_end_ms": 3000},
                    {"id": "outside", "timeline_start_ms": 5000, "timeline_end_ms": 7000},
                ],
            }
        ]
    }
    kept, conflicts = constrain_operations_to_selection(
        [
            {"type": "DELETE_RANGE", "start_ms": 1200, "end_ms": 1800},
            {"type": "DELETE_RANGE", "start_ms": 4200, "end_ms": 4800},
            {"type": "SET_CLIP_VOLUME", "clip_id": "inside", "volume": 0.8},
            {"type": "DELETE_CLIP", "clip_id": "outside"},
        ],
        timeline,
        {"start_ms": 1000, "end_ms": 3000, "clip_ids": ["inside"]},
    )

    assert [operation["type"] for operation in kept] == ["DELETE_RANGE", "SET_CLIP_VOLUME"]
    assert len(conflicts) == 2


def test_history_compaction_enforces_budget_and_keeps_outcomes() -> None:
    history = [
        {
            "role": "system",
            "content": "x" * 2000,
            "metadata": {"event": "plan_approved", "timeline_version": 4, "ignored": "large"},
        }
        for _ in range(10)
    ]

    compact = compact_history(history, character_budget=1200)

    assert sum(len(item["content"]) for item in compact) <= 1200
    assert compact[-1]["metadata"] == {"event": "plan_approved", "timeline_version": 4}


def test_tool_context_prefers_selected_asset() -> None:
    context = AgentToolContext(
        project_id="project-1",
        project_dir="project-1",
        timeline_version=1,
        timeline={
            "tracks": [
                {
                    "clips": [
                        {"id": "clip-1", "asset_id": "asset-1"},
                        {"id": "clip-2", "asset_id": "asset-2"},
                    ]
                }
            ]
        },
        assets=[
            {"id": "asset-1", "type": "VIDEO", "processing_status": "COMPLETED"},
            {"id": "asset-2", "type": "VIDEO", "processing_status": "COMPLETED"},
        ],
        selection={"asset_id": "asset-2", "start_ms": 0, "end_ms": 30000},
    )

    assert context.find_asset(media_only=True)["id"] == "asset-2"


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
