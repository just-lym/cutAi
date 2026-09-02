import asyncio
from dataclasses import dataclass
from typing import Any

from app.agents.state import AgentState

VISUAL_TERMS = ("画面", "镜头", "视觉", "构图", "关键帧", "遮挡", "连贯", "b-roll", "frame", "shot")
AUDIO_TERMS = ("音频", "声音", "音乐", "节拍", "卡点", "噪声", "响度", "听", "audio", "beat")
TRANSCRIPT_TERMS = ("转写", "字幕", "台词", "语义", "口播", "访谈", "说了什么", "asr", "transcript")
AUTO_EDIT_TERMS = ("自动剪辑", "自动精剪", "精剪", "粗剪", "剪成", "生成成片", "auto edit", "rough cut")


@dataclass(frozen=True)
class EvidenceCall:
    name: str
    arguments: dict[str, Any]
    category: str


def _contains_any(request: str, terms: tuple[str, ...]) -> bool:
    lowered = request.lower()
    return any(term in lowered for term in terms)


def _compact_evidence(value: dict[str, Any]) -> dict[str, Any]:
    compact = dict(value)
    for key in ("edl", "cues", "phrases", "diagnosed_assets", "nearby_cues", "beat_times_ms"):
        items = compact.get(key)
        if isinstance(items, list):
            compact[key] = items[:20]
    compact.pop("usage", None)
    compact.pop("usage_records", None)
    return compact


def _usage_from_evidence(tool_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("usage_records"), list):
        return list(result["usage_records"])
    usage = result.get("usage")
    model = result.get("vision_model") or result.get("audio_model")
    if not isinstance(usage, dict) or not model:
        return []
    return [{**usage, "provider": "dashscope", "model": model, "tool": tool_name}]


def plan_evidence(state: AgentState, tools: Any, request: str) -> list[EvidenceCall]:
    if not state.get("assets"):
        return []

    calls = [
        EvidenceCall("build_packed_transcript", {"limit": 40}, "local"),
        EvidenceCall("build_timeline_edl", {"output_name": "agent_preflight_edl.json"}, "local"),
        EvidenceCall("recommend_edit_strategy", {"goal": request}, "cached"),
    ]
    context = tools.context
    asset = context.find_asset(media_only=True)
    wants_auto_edit = _contains_any(request, AUTO_EDIT_TERMS)
    wants_visual = wants_auto_edit or _contains_any(request, VISUAL_TERMS)
    wants_audio = wants_auto_edit or _contains_any(request, AUDIO_TERMS)
    wants_transcript = wants_auto_edit or _contains_any(request, TRANSCRIPT_TERMS)

    if asset and asset.get("type") == "VIDEO" and wants_visual:
        selection = state.get("selection") or {}
        start_ms = int(selection.get("start_ms") or 0)
        end_ms = int(
            selection.get("end_ms")
            or min(int(asset.get("duration_ms") or start_ms + 30000), start_ms + 30000)
        )
        if end_ms > start_ms:
            asset_id = str(asset.get("id"))
            calls.extend(
                [
                    EvidenceCall(
                        "render_timeline_view",
                        {"asset_id": asset_id, "start_ms": start_ms, "end_ms": end_ms, "frames": 6},
                        "visual_local",
                    ),
                    EvidenceCall(
                        "qwen_vl_inspect_range",
                        {
                            "question": request,
                            "asset_id": asset_id,
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "frames": 8,
                        },
                        "visual_cloud",
                    ),
                ]
            )
    if asset and wants_audio:
        asset_id = str(asset.get("id"))
        calls.extend(
            [
                EvidenceCall("ffmpeg_detect_beats", {"asset_id": asset_id}, "audio_local"),
                EvidenceCall(
                    "qwen_audio_analyze_range",
                    {"question": request, "asset_id": asset_id},
                    "audio_cloud",
                ),
            ]
        )
    if asset and not context.subtitle_cues() and wants_transcript:
        calls.append(
            EvidenceCall(
                "asr_transcribe_asset",
                {"asset_id": str(asset.get("id")), "max_chunks": 3},
                "asr",
            )
        )
    return calls


async def collect_preflight_evidence(
    state: AgentState,
    tools: Any,
    request: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    calls = plan_evidence(state, tools, request)
    if not calls:
        return {}, [], []

    semaphore = asyncio.Semaphore(4)

    async def execute(call: EvidenceCall) -> tuple[EvidenceCall, dict[str, Any]]:
        async with semaphore:
            return call, await tools.run(call.name, call.arguments)

    results = await asyncio.gather(*(execute(call) for call in calls))
    evidence: dict[str, Any] = {
        "profile": {
            "requested_categories": list(dict.fromkeys(call.category for call in calls)),
            "parallelism": min(4, len(calls)),
        }
    }
    trace: list[dict[str, Any]] = []
    usage_records: list[dict[str, Any]] = []
    for call, result in results:
        evidence[call.name] = _compact_evidence(result)
        usage_records.extend(_usage_from_evidence(call.name, result))
        trace.append(
            {
                "title": f"预检：{call.name}",
                "detail": "已生成并注入导演上下文。" if result.get("ok") else "预检不可用，已保留失败原因并继续。",
                "data": {
                    "agent": state.get("coordinator_name"),
                    "category": call.category,
                    "tool_calls": [{"name": call.name, "arguments": call.arguments}],
                    "ok": bool(result.get("ok")),
                    "error": result.get("error") or result.get("errors"),
                },
            }
        )
    return evidence, trace, usage_records
