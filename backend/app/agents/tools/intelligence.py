import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary, diagnosis_summary
from app.agents.tools.schema import AgentTool
from app.cloud_api.asr_client import ASRError, transcribe_audio_async
from app.cloud_api.audio_client import AudioUnderstandingError, audio_chat_async
from app.cloud_api.vision_client import VisionError, vision_chat_async
from app.tools.media_tools import (
    MediaToolError,
    detect_audio_beats,
    extract_audio_range,
    render_timeline_contact_sheet,
)


def _artifact_dir(context: AgentToolContext) -> Path:
    path = Path(context.project_dir) / "agent_outputs" / "intelligence"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_intelligence_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("qwen_vl_inspect_range")
    async def qwen_vl_inspect_range(
        question: str,
        asset_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        frames: int = 8,
    ) -> dict:
        """抽取真实画面并交给 Qwen-VL 观察。用于内容、构图、连续性、字幕遮挡和剪点判断。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None or asset.get("type") != "VIDEO":
            return {"ok": False, "error": "Video asset not found"}
        selection = context.selection or {}
        range_start = int(start_ms if start_ms is not None else selection.get("start_ms") or 0)
        range_end = int(
            end_ms
            if end_ms is not None
            else selection.get("end_ms") or asset.get("duration_ms") or context.effective_duration_ms()
        )
        if range_end <= range_start:
            return {"ok": False, "error": "end_ms must be greater than start_ms"}
        output = _artifact_dir(context) / f"vl_{asset.get('id')}_{range_start}_{range_end}.jpg"
        try:
            await render_timeline_contact_sheet(
                context.asset_path(asset),
                output,
                start_ms=range_start,
                end_ms=range_end,
                frames=max(2, min(16, frames)),
                frame_width=260,
            )
            response = await vision_chat_async(
                "你是视频剪辑视觉观察员。图片从左到右按时间排列。"
                f"请基于真实可见画面回答，不要推测音频。问题：{question}",
                [output],
            )
        except (MediaToolError, VisionError) as exc:
            return {"ok": False, "error": str(exc), "contact_sheet_path": str(output)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "range": {"start_ms": range_start, "end_ms": range_end},
            "observation": response["content"],
            "contact_sheet_path": str(output),
            "vision_model": response["model"],
            "usage": response["usage"],
        }

    @tool("ffmpeg_detect_beats")
    async def ffmpeg_detect_beats(
        asset_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        max_beats: int = 240,
    ) -> dict:
        """分析音频能量起音，返回估计 BPM、置信度和节拍时间点，供卡点与镜头密度决策。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Media asset not found"}
        selection = context.selection or {}
        range_start = int(start_ms if start_ms is not None else selection.get("start_ms") or 0)
        range_end = end_ms if end_ms is not None else selection.get("end_ms")
        try:
            analysis = await detect_audio_beats(
                context.asset_path(asset),
                start_ms=range_start,
                end_ms=int(range_end) if range_end is not None else None,
                max_beats=max_beats,
            )
        except MediaToolError as exc:
            return {"ok": False, "error": str(exc), "asset": asset_summary(context, asset)}
        return {"ok": True, "asset": asset_summary(context, asset), **analysis}

    @tool("qwen_audio_analyze_range")
    async def qwen_audio_analyze_range(
        question: str,
        asset_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict:
        """让 Qwen-Audio 真正听取所选音频，分析语音、音乐、噪声、情绪与可剪辑点。单次最多 120 秒。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Media asset not found"}
        selection = context.selection or {}
        range_start = int(start_ms if start_ms is not None else selection.get("start_ms") or 0)
        requested_end = int(
            end_ms
            if end_ms is not None
            else selection.get("end_ms") or asset.get("duration_ms") or range_start + 120000
        )
        range_end = min(requested_end, range_start + 120000)
        audio_path = _artifact_dir(context) / f"audio_{asset.get('id')}_{range_start}_{range_end}.wav"
        try:
            await extract_audio_range(context.asset_path(asset), audio_path, range_start, range_end)
            response = await audio_chat_async(
                "你是视频剪辑音频观察员。基于真实听到的内容回答，标出相对时间、语音内容、"
                f"音乐节拍、噪声、停顿、情绪和建议剪点。问题：{question}",
                audio_path,
            )
        except (MediaToolError, AudioUnderstandingError) as exc:
            return {"ok": False, "error": str(exc), "audio_path": str(audio_path)}
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "range": {"start_ms": range_start, "end_ms": range_end},
            "observation": response["content"],
            "audio_path": str(audio_path),
            "audio_model": response["model"],
            "usage": response["usage"],
        }

    @tool("asr_transcribe_asset")
    async def asr_transcribe_asset(
        asset_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        chunk_ms: int = 60000,
        max_chunks: int = 10,
    ) -> dict:
        """用 Qwen-Audio 分块转写所选素材，返回带时间范围和说话人的 ASR cues 及 JSON artifact。"""
        asset = context.find_asset(asset_id, media_only=True)
        if asset is None:
            return {"ok": False, "error": "Media asset not found"}
        selection = context.selection or {}
        range_start = int(start_ms if start_ms is not None else selection.get("start_ms") or 0)
        range_end = int(
            end_ms
            if end_ms is not None
            else selection.get("end_ms") or asset.get("duration_ms") or range_start
        )
        if range_end <= range_start:
            return {"ok": False, "error": "A finite asset duration or end_ms is required"}
        safe_chunk_ms = max(10000, min(120000, int(chunk_ms)))
        chunks = min(max(1, int(max_chunks)), 20)
        cues: list[dict[str, Any]] = []
        usage_records: list[dict[str, Any]] = []
        cursor = range_start
        try:
            while cursor < range_end and len(usage_records) < chunks:
                chunk_end = min(range_end, cursor + safe_chunk_ms)
                audio_path = _artifact_dir(context) / f"asr_{asset.get('id')}_{cursor}_{chunk_end}.wav"
                await extract_audio_range(context.asset_path(asset), audio_path, cursor, chunk_end)
                response = await transcribe_audio_async(audio_path)
                cues.extend(
                    {
                        **segment,
                        "start_ms": min(chunk_end, cursor + int(segment["start_ms"])),
                        "end_ms": min(chunk_end, cursor + int(segment["end_ms"])),
                    }
                    for segment in response["segments"]
                    if int(segment["end_ms"]) > int(segment["start_ms"])
                )
                usage_records.append(
                    {
                        **response["usage"],
                        "provider": "dashscope",
                        "model": response["model"],
                        "request_id": response.get("request_id"),
                    }
                )
                cursor = chunk_end
        except (MediaToolError, ASRError) as exc:
            return {"ok": False, "error": str(exc), "cues": cues, "processed_until_ms": cursor}
        artifact_path = _artifact_dir(context) / f"transcript_{asset.get('id')}_{range_start}_{cursor}.json"
        artifact_path.write_text(json.dumps({"cues": cues}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "asset": asset_summary(context, asset),
            "range": {"start_ms": range_start, "end_ms": cursor},
            "cue_count": len(cues),
            "cues": cues,
            "artifact_path": str(artifact_path),
            "usage_records": usage_records,
            "truncated": cursor < range_end,
        }

    @tool("recommend_edit_strategy")
    async def recommend_edit_strategy(goal: str = "") -> dict:
        """汇总素材自动诊断、当前框选范围和历史审批偏好，返回有证据的剪辑建议上下文。"""
        diagnosed_assets: list[dict[str, Any]] = []
        for asset in context.assets:
            diagnosis = diagnosis_summary(asset)
            if diagnosis:
                diagnosed_assets.append(
                    {"asset": asset_summary(context, asset), "diagnosis": diagnosis}
                )
        preferences = context.preferences or {"sample_count": 0, "confidence": 0.0}
        accepted = preferences.get("accepted_operations") or {}
        rejected = preferences.get("rejected_operations") or {}
        preferred_operations = sorted(accepted, key=accepted.get, reverse=True)[:5]
        avoided_operations = sorted(rejected, key=rejected.get, reverse=True)[:5]
        return {
            "ok": True,
            "goal": goal,
            "selection": context.selection,
            "preference_confidence": preferences.get("confidence", 0.0),
            "preferred_operations": preferred_operations,
            "frequently_rejected_operations": avoided_operations,
            "feedback_notes": list(preferences.get("feedback_notes") or [])[-5:],
            "diagnosed_assets": diagnosed_assets,
            "recommendation_rule": (
                "优先使用诊断中的 strong_moments 和 editing_suggestions；仅在偏好置信度足够时"
                "把审批统计作为软约束，并严格限制在 selection 范围内。"
            ),
        }

    return [
        qwen_vl_inspect_range,
        ffmpeg_detect_beats,
        qwen_audio_analyze_range,
        asr_transcribe_asset,
        recommend_edit_strategy,
    ]
