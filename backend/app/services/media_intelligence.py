import asyncio
import uuid
from pathlib import Path
from typing import Any

from app.cloud_api.audio_client import AudioUnderstandingError, audio_chat_async
from app.cloud_api.vision_client import VisionError, parse_json_object, vision_chat_async
from app.config import settings
from app.tools.media_tools import (
    MediaToolError,
    analyze_audio_loudness,
    detect_audio_beats,
    detect_scene_changes,
    duration_ms_from_probe,
    extract_audio_range,
    probe_media,
    render_timeline_contact_sheet,
    video_info_from_probe,
)

ASSET_VISION_PROMPT = """
你是视频素材诊断员。观察这张按时间从左到右排列的接触表，返回严格 JSON，不要 Markdown：
{"summary":"素材内容概述","subjects":["主体"],"locations":["场景"],
"shot_types":["景别/运镜"],"quality_issues":["曝光、模糊、抖动、遮挡等问题"],
"strong_moments":[{"approx_percent":0到100,"reason":"值得保留的原因"}],
"editing_suggestions":["可执行建议"]}
不要声称听到了音频；时间只能按画面在接触表中的相对位置估计。
""".strip()

RENDER_VISION_PROMPT = """
你是成片质检员。观察按时间从左到右排列的渲染接触表，返回严格 JSON，不要 Markdown：
{"score":0到100,"summary":"总体判断","issues":[{"severity":"high|medium|low",
"approx_percent":0到100,"category":"continuity|composition|exposure|subtitle|transition|other",
"detail":"具体问题"}],"strengths":["优点"],"recommended_actions":["下一步修改"]}
只评价画面中真实可见的证据，不要声称听到了音频。
""".strip()


def _safe_artifact_name(path: Path) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in path.stem)[:80]


def _stream_types(probe: dict[str, Any]) -> set[str]:
    return {str(stream.get("codec_type")) for stream in probe.get("streams", [])}


async def diagnose_asset(
    path: Path,
    asset_type: str,
    project_dir: Path,
    duration_ms: int | None = None,
    probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir = project_dir / "diagnostics"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"version": 1, "status": "completed", "issues": []}
    if probe:
        report["technical"] = {
            "stream_types": sorted(_stream_types(probe)),
            "format_name": (probe.get("format") or {}).get("format_name"),
            "bit_rate": (probe.get("format") or {}).get("bit_rate"),
        }

    normalized_type = str(asset_type).upper()
    if normalized_type in {"VIDEO", "AUDIO"}:
        try:
            report["audio_beats"] = await detect_audio_beats(path, max_beats=120)
        except MediaToolError as exc:
            report["audio_beats"] = {"bpm": None, "confidence": 0.0, "beats": [], "error": str(exc)}
        if settings.cloud.dashscope_api_key and duration_ms:
            audio_end_ms = min(duration_ms, 120000)
            audio_path = artifact_dir / f"{_safe_artifact_name(path)}_diagnostic.wav"
            try:
                await extract_audio_range(path, audio_path, 0, audio_end_ms)
                response = await audio_chat_async(
                    "你是素材音频诊断员。返回严格 JSON，不要 Markdown："
                    '{"summary":"听到的内容","audio_quality_issues":["问题"],'
                    '"music_mood":"音乐情绪或null","editing_suggestions":["建议"],'
                    '"segments":[{"start_ms":相对开始毫秒,"end_ms":相对开始毫秒,'
                    '"speaker":"说话人或null","text":"逐字转写"}]}。不要编造听不清的内容。',
                    audio_path,
                )
                audio_semantics = parse_json_object(response["content"])
                report["audio_semantics"] = audio_semantics
                report["audio_usage"] = {**response["usage"], "model": response["model"]}
                transcript_cues = []
                for item in audio_semantics.get("segments") or []:
                    if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                        continue
                    start_ms = max(0, min(audio_end_ms, int(item.get("start_ms") or 0)))
                    end_ms = max(start_ms + 1, min(audio_end_ms, int(item.get("end_ms") or audio_end_ms)))
                    transcript_cues.append(
                        {
                            "id": str(uuid.uuid4()),
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "text": str(item["text"]).strip(),
                            "speaker": item.get("speaker"),
                            "confidence": None,
                        }
                    )
                report["transcript_cues"] = transcript_cues
                report["transcript_truncated"] = duration_ms > audio_end_ms
            except (MediaToolError, AudioUnderstandingError, VisionError, ValueError, TypeError) as exc:
                report["audio_semantics_error"] = str(exc)
        elif duration_ms:
            report["audio_semantics_status"] = "skipped_no_api_key"

    image_paths: list[Path] = []
    if normalized_type == "VIDEO" and duration_ms:
        try:
            report["scenes"] = await detect_scene_changes(path, threshold=0.35, min_gap_ms=700)
        except MediaToolError as exc:
            report["scenes"] = []
            report["issues"].append(f"场景检测失败：{exc}")
        sheet = artifact_dir / f"{_safe_artifact_name(path)}_contact.jpg"
        try:
            await render_timeline_contact_sheet(
                path,
                sheet,
                start_ms=0,
                end_ms=max(1000, duration_ms),
                frames=min(12, max(4, duration_ms // 5000 + 1)),
                frame_width=240,
            )
            report["contact_sheet"] = str(sheet)
            image_paths = [sheet]
        except MediaToolError as exc:
            report["issues"].append(f"视觉接触表生成失败：{exc}")
    elif normalized_type == "IMAGE":
        image_paths = [path]

    if image_paths and settings.cloud.dashscope_api_key:
        try:
            response = await vision_chat_async(ASSET_VISION_PROMPT, image_paths)
            report["visual"] = parse_json_object(response["content"])
            report["vision_usage"] = {**response["usage"], "model": response["model"]}
        except VisionError as exc:
            report["visual_error"] = str(exc)
    elif image_paths:
        report["visual_status"] = "skipped_no_api_key"
    return report


async def evaluate_render_quality(
    path: Path,
    project_dir: Path,
    expected_duration_ms: int | None = None,
) -> dict[str, Any]:
    probe = await probe_media(path)
    duration_ms = duration_ms_from_probe(probe) or 0
    width, height, frame_rate = video_info_from_probe(probe)
    stream_types = _stream_types(probe)
    issues: list[dict[str, Any]] = []
    score = 100
    if "video" not in stream_types:
        issues.append({"severity": "high", "category": "technical", "detail": "输出缺少视频流"})
        score -= 70
    if duration_ms <= 0:
        issues.append({"severity": "high", "category": "technical", "detail": "输出时长无效"})
        score -= 50
    if width and height and min(width, height) < 480:
        issues.append({"severity": "medium", "category": "technical", "detail": "输出分辨率偏低"})
        score -= 15
    if not frame_rate or frame_rate < 20:
        issues.append({"severity": "medium", "category": "technical", "detail": "帧率偏低或无法识别"})
        score -= 10
    if expected_duration_ms and duration_ms:
        duration_delta_ms = abs(duration_ms - expected_duration_ms)
        duration_tolerance_ms = max(500, round(expected_duration_ms * 0.02))
        if duration_delta_ms > duration_tolerance_ms:
            issues.append(
                {
                    "severity": "high",
                    "category": "duration",
                    "detail": (
                        f"输出时长与时间线相差 {duration_delta_ms}ms "
                        f"（期望 {expected_duration_ms}ms，实际 {duration_ms}ms）"
                    ),
                }
            )
            score -= 30

    audio: dict[str, Any] | None = None
    loudness_task: asyncio.Task[dict[str, float | None]] | None = None
    if "audio" in stream_types:
        loudness_task = asyncio.create_task(analyze_audio_loudness(path))

    quality_dir = project_dir / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    sheet = quality_dir / f"{_safe_artifact_name(path)}_quality_contact.jpg"
    visual: dict[str, Any] | None = None
    if duration_ms > 0:
        try:
            await render_timeline_contact_sheet(
                path,
                sheet,
                start_ms=0,
                end_ms=duration_ms,
                frames=min(12, max(6, duration_ms // 5000 + 1)),
                frame_width=240,
            )
            if settings.cloud.dashscope_api_key:
                response = await vision_chat_async(RENDER_VISION_PROMPT, [sheet])
                visual = parse_json_object(response["content"])
                score = min(score, max(0, min(100, int(visual.get("score", score)))))
                for item in visual.get("issues") or []:
                    if isinstance(item, dict):
                        issues.append({**item, "source": "vision"})
        except (MediaToolError, VisionError, ValueError, TypeError) as exc:
            issues.append({"severity": "low", "category": "inspection", "detail": str(exc)})

    if loudness_task:
        try:
            audio = await loudness_task
            integrated_lufs = audio.get("integrated_lufs")
            true_peak_dbfs = audio.get("true_peak_dbfs")
            if integrated_lufs is not None and not -24 <= integrated_lufs <= -8:
                issues.append(
                    {
                        "severity": "medium",
                        "category": "audio_loudness",
                        "detail": f"综合响度 {integrated_lufs:.1f} LUFS，建议控制在 -24 至 -8 LUFS",
                    }
                )
                score -= 10
            if true_peak_dbfs is not None and true_peak_dbfs > -1:
                issues.append(
                    {
                        "severity": "high",
                        "category": "audio_peak",
                        "detail": f"真峰值 {true_peak_dbfs:.1f} dBFS，存在削波风险",
                    }
                )
                score -= 20
        except MediaToolError as exc:
            issues.append({"severity": "low", "category": "audio_inspection", "detail": str(exc)})

    return {
        "version": 1,
        "score": max(0, score),
        "passed": score >= 70 and not any(item.get("severity") == "high" for item in issues),
        "technical": {
            "duration_ms": duration_ms,
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "stream_types": sorted(stream_types),
        },
        "issues": issues,
        "audio": audio,
        "visual": visual,
        "contact_sheet": str(sheet) if sheet.exists() else None,
    }
