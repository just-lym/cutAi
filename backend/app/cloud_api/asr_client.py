import asyncio
from http import HTTPStatus
from pathlib import Path
from typing import Any

from dashscope.audio.asr import Recognition, RecognitionCallback

from app.config import settings


class ASRError(RuntimeError):
    pass


class _RecognitionCallback(RecognitionCallback):
    def __init__(self) -> None:
        self.error: str | None = None

    def on_error(self, result: Any) -> None:
        code = getattr(result, "code", None)
        message = getattr(result, "message", None)
        self.error = ": ".join(str(value) for value in (code, message) if value)


def _segments(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for sentence in sentences:
        text = str(sentence.get("text") or "").strip()
        if not text:
            continue
        begin_time = max(0, int(sentence.get("begin_time") or 0))
        end_time = max(begin_time + 1, int(sentence.get("end_time") or begin_time + 1))
        speaker_id = sentence.get("speaker_id")
        segments.append(
            {
                "start_ms": begin_time,
                "end_ms": end_time,
                "text": text,
                "speaker": f"speaker_{speaker_id}" if speaker_id is not None else None,
            }
        )
    return segments


def transcribe_audio_sync(audio_path: Path, model: str | None = None) -> dict[str, Any]:
    if not settings.cloud.dashscope_api_key:
        raise ASRError("DashScope API key is not configured")
    path = audio_path.resolve()
    if not path.is_file():
        raise ASRError(f"ASR input does not exist: {path}")

    selected_model = model or settings.cloud.asr_model
    callback = _RecognitionCallback()
    recognition = Recognition(
        model=selected_model,
        callback=callback,
        format="wav",
        sample_rate=16000,
        workspace=settings.cloud.dashscope_workspace_id or None,
        api_key=settings.cloud.dashscope_api_key,
        diarization_enabled=True,
        timestamp_alignment_enabled=True,
    )
    result = recognition.call(str(path))
    if result.status_code != HTTPStatus.OK:
        detail = callback.error or ": ".join(
            str(value) for value in (result.code, result.message) if value
        )
        raise ASRError(detail or f"DashScope ASR failed with status {result.status_code}")

    sentences = result.get_sentence() or []
    normalized = _segments([item for item in sentences if isinstance(item, dict)])
    audio_duration_ms = max(
        (int(item.get("end_time") or 0) for item in sentences if isinstance(item, dict)),
        default=0,
    )
    usage = dict(result.usage or {}) if isinstance(result.usage, dict) else {}
    usage["audio_duration_ms"] = audio_duration_ms
    return {
        "transcript": "".join(item["text"] for item in normalized),
        "segments": normalized,
        "usage": usage,
        "request_id": result.request_id,
        "model": selected_model,
    }


async def transcribe_audio_async(audio_path: Path, model: str | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(transcribe_audio_sync, audio_path, model)
