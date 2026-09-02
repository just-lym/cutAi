import subprocess
from array import array
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.agents.graph import build_initial_state
from app.agents.tools import AgentToolbox
from app.api.render import _main_ranges
from app.cloud_api import dashscope_client
from app.cloud_api.asr_client import _segments
from app.cloud_api.dashscope_client import format_dashscope_error
from app.cloud_api.vision_client import parse_json_object
from app.config import settings
from app.schemas import AgentMessage
from app.services import media_intelligence
from app.services.preferences import learn_from_approval
from app.tools import media_tools


def test_parse_json_object_accepts_fenced_qwen_vl_response() -> None:
    result = parse_json_object('说明如下：```json\n{"score":88,"issues":[]}\n```')

    assert result == {"score": 88, "issues": []}


def test_model_roles_use_compatible_paid_endpoints() -> None:
    assert settings.cloud.agent_model == "qwen3.8-max"
    assert settings.cloud.director_model == "qwen3.8-max"
    assert settings.cloud.specialist_model == "qwen3.8-max"
    assert settings.cloud.review_model == "qwen3.8-max"
    assert settings.cloud.vision_model == "qwen3-vl-plus"
    assert settings.cloud.audio_model == "qwen3-omni-flash"
    assert settings.cloud.asr_model == "qwen-audio-3.0-asr-flash-streaming"


def test_asr_segments_preserve_timing_and_speaker() -> None:
    assert _segments(
        [
            {"begin_time": 120, "end_time": 640, "text": "你好", "speaker_id": 2},
            {"begin_time": 640, "end_time": 900, "text": "  ", "speaker_id": None},
        ]
    ) == [
        {
            "start_ms": 120,
            "end_ms": 640,
            "text": "你好",
            "speaker": "speaker_2",
        }
    ]


def test_dashscope_free_tier_error_explains_paid_billing_switch() -> None:
    message = format_dashscope_error(
        {
            "status_code": 403,
            "code": "AllocationQuota.FreeTierOnly",
            "message": "Free tier exhausted",
            "request_id": "request-1",
        }
    )

    assert "免费额度用完即停" in message
    assert "HTTP 403" in message
    assert "AllocationQuota.FreeTierOnly" in message
    assert "request_id=request-1" in message


def test_qwen_chat_uses_compatible_endpoint_and_parses_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {"x-request-id": "request-1"}

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "id": "completion-1",
                "model": "qwen3.8-max",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "inspect_video",
                                        "arguments": '{"asset_id":"a1"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            }

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(settings.cloud, "dashscope_api_key", "test-key")
    monkeypatch.setattr(dashscope_client.httpx, "post", fake_post)
    result = dashscope_client.llm_chat_sync(
        "qwen3.8-max",
        [{"role": "user", "content": "检查视频"}],
        tools=[{"type": "function", "function": {"name": "inspect_video"}}],
    )

    assert captured["url"].endswith("/compatible-mode/v1/chat/completions")
    assert captured["json"]["model"] == "qwen3.8-max"
    assert result["tool_calls"][0]["function"]["name"] == "inspect_video"
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 3}


def test_parse_loudness_report_normalizes_ffmpeg_values() -> None:
    report = media_tools._parse_loudness_report(
        'noise\n{"input_i":"-14.20","input_tp":"-1.50",'
        '"input_lra":"6.10","input_thresh":"-24.00"}\n'
    )

    assert report == {
        "integrated_lufs": -14.2,
        "true_peak_dbfs": -1.5,
        "loudness_range_lu": 6.1,
        "threshold_lufs": -24.0,
    }


def test_atempo_filters_support_wide_speed_range() -> None:
    assert media_tools._atempo_filters(4.0) == ["atempo=2.000000", "atempo=2.000000"]
    assert media_tools._atempo_filters(0.25) == ["atempo=0.500000", "atempo=0.500000"]


def test_render_ranges_use_original_audio_track_volume_and_clip_speed() -> None:
    timeline = {
        "tracks": [
            {
                "id": "video-main",
                "clips": [
                    {
                        "id": "video",
                        "asset_id": "asset",
                        "timeline_start_ms": 0,
                        "timeline_end_ms": 2000,
                        "source_in_ms": 1000,
                        "source_out_ms": 5000,
                        "speed": 2.0,
                        "volume": 0.0,
                    }
                ],
            },
            {
                "id": "audio-original",
                "clips": [
                    {
                        "id": "audio",
                        "asset_id": "asset",
                        "timeline_start_ms": 0,
                        "timeline_end_ms": 2000,
                        "volume": 0.85,
                    }
                ],
            },
        ]
    }

    ranges = _main_ranges(timeline)

    assert ranges[0]["speed"] == 2.0
    assert ranges[0]["volume"] == 0.85


def test_initial_state_preserves_selection_and_preferences() -> None:
    selection = {"start_ms": 1200, "end_ms": 4500, "asset_id": "asset-1"}
    preferences = {"sample_count": 8, "confidence": 0.4, "accepted_operations": {"DELETE_RANGE": 5}}

    state = build_initial_state(
        "优化框选部分",
        "project-1",
        ".",
        1,
        {"duration_ms": 5000, "tracks": []},
        [],
        "TALKING_HEAD",
        preferences,
        selection,
    )

    assert state["selection"] == selection
    assert state["preferences"] == preferences
    assert state["trace"][0]["data"]["selection"] == selection


def test_agent_selection_rejects_an_inverted_range() -> None:
    with pytest.raises(ValidationError):
        AgentMessage(content="优化", selection={"start_ms": 5000, "end_ms": 1000})


def test_toolbox_exposes_visual_audio_and_recommendation_tools(tmp_path: Path) -> None:
    toolbox = AgentToolbox("project-1", str(tmp_path), 1, {"tracks": []}, [])

    names = toolbox.names_for("talking_head_director")
    assert "qwen_vl_inspect_range" in names
    assert "ffmpeg_detect_beats" in names
    assert "recommend_edit_strategy" in names


@pytest.mark.asyncio
async def test_detect_audio_beats_finds_regular_half_second_pulses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_rate = 8000
    samples = array("h", [0] * (sample_rate * 10))
    for pulse_start in range(sample_rate // 2, len(samples), sample_rate // 2):
        for index in range(pulse_start, min(pulse_start + sample_rate // 20, len(samples))):
            samples[index] = 20000

    completed = subprocess.CompletedProcess([], 0, stdout=samples.tobytes(), stderr=b"")
    monkeypatch.setattr(media_tools.subprocess, "run", lambda *args, **kwargs: completed)

    result = await media_tools.detect_audio_beats(
        tmp_path / "audio.wav",
        end_ms=10000,
    )

    assert result["bpm"] == 120.0
    assert result["confidence"] > 0.5
    assert len(result["beats"]) >= 15


@pytest.mark.asyncio
async def test_render_quality_has_local_fallback_without_vision_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe(_path: Path) -> dict[str, Any]:
        return {
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "12.0"},
        }

    async def fake_sheet(_input: Path, output: Path, **_kwargs: Any) -> Path:
        output.write_bytes(b"image")
        return output

    async def fake_loudness(_path: Path) -> dict[str, float]:
        return {"integrated_lufs": -14.0, "true_peak_dbfs": -1.5, "loudness_range_lu": 5.0}

    monkeypatch.setattr(media_intelligence, "probe_media", fake_probe)
    monkeypatch.setattr(media_intelligence, "render_timeline_contact_sheet", fake_sheet)
    monkeypatch.setattr(media_intelligence, "analyze_audio_loudness", fake_loudness)
    monkeypatch.setattr(settings.cloud, "dashscope_api_key", "")

    report = await media_intelligence.evaluate_render_quality(tmp_path / "render.mp4", tmp_path)

    assert report["passed"] is True
    assert report["score"] == 100
    assert report["visual"] is None
    assert report["audio"]["integrated_lufs"] == -14.0


@pytest.mark.asyncio
async def test_render_quality_rejects_duration_drift_and_clipping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_probe(_path: Path) -> dict[str, Any]:
        return {
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "8.0"},
        }

    async def fake_sheet(_input: Path, output: Path, **_kwargs: Any) -> Path:
        output.write_bytes(b"image")
        return output

    async def fake_loudness(_path: Path) -> dict[str, float]:
        return {"integrated_lufs": -4.0, "true_peak_dbfs": 0.2, "loudness_range_lu": 4.0}

    monkeypatch.setattr(media_intelligence, "probe_media", fake_probe)
    monkeypatch.setattr(media_intelligence, "render_timeline_contact_sheet", fake_sheet)
    monkeypatch.setattr(media_intelligence, "analyze_audio_loudness", fake_loudness)
    monkeypatch.setattr(settings.cloud, "dashscope_api_key", "")

    report = await media_intelligence.evaluate_render_quality(
        tmp_path / "render.mp4",
        tmp_path,
        expected_duration_ms=10000,
    )

    assert report["passed"] is False
    assert {issue["category"] for issue in report["issues"]} >= {
        "duration",
        "audio_loudness",
        "audio_peak",
    }


class FakePreferenceResult:
    def scalar_one_or_none(self) -> None:
        return None


class FakePreferenceSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def execute(self, _statement: Any) -> FakePreferenceResult:
        return FakePreferenceResult()

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_approval_learning_tracks_accepted_and_rejected_operation_types() -> None:
    db = FakePreferenceSession()
    project = SimpleNamespace(owner_id="local", video_type="VLOG")
    plan = SimpleNamespace(
        operations=[
            {"type": "DELETE_RANGE", "start_ms": 0, "end_ms": 800},
            {"type": "SET_VOLUME"},
        ]
    )

    profile = await learn_from_approval(  # type: ignore[arg-type]
        db,
        project,
        plan,
        {0},
        {1},
        "保留更多环境声",
    )

    assert profile["accepted_operations"] == {"DELETE_RANGE": 1}
    assert profile["rejected_operations"] == {"SET_VOLUME": 1}
    assert profile["feedback_notes"] == ["保留更多环境声"]
    assert profile["sample_count"] == 2
