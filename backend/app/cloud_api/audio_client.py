import asyncio
from http import HTTPStatus
from pathlib import Path
from typing import Any

import dashscope

from app.cloud_api.dashscope_client import format_dashscope_error
from app.config import settings


class AudioUnderstandingError(RuntimeError):
    pass


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _response_text(response: Any) -> str:
    output = _get(response, "output", {}) or {}
    choices = _get(output, "choices", []) or []
    if not choices:
        raise AudioUnderstandingError("DashScope audio response did not include choices")
    content = _get(_get(choices[0], "message", {}) or {}, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = "\n".join(str(_get(item, "text")) for item in content if _get(item, "text"))
        if text:
            return text
    raise AudioUnderstandingError("DashScope audio response did not include text")


def audio_chat_sync(prompt: str, audio_path: Path, model: str | None = None) -> dict[str, Any]:
    if not settings.cloud.dashscope_api_key:
        raise AudioUnderstandingError("DashScope API key is not configured")
    path = audio_path.resolve()
    if not path.is_file():
        raise AudioUnderstandingError(f"Audio input does not exist: {path}")
    selected_model = model or settings.cloud.audio_model
    response = dashscope.MultiModalConversation.call(
        model=selected_model,
        api_key=settings.cloud.dashscope_api_key,
        workspace=settings.cloud.dashscope_workspace_id or None,
        messages=[
            {
                "role": "user",
                "content": [{"audio": path.as_uri()}, {"text": prompt}],
            }
        ],
    )
    status_code = _get(response, "status_code")
    if status_code and status_code != HTTPStatus.OK:
        raise AudioUnderstandingError(format_dashscope_error(response, "DashScope audio request failed"))
    usage = _get(response, "usage", {}) or {}
    return {
        "content": _response_text(response),
        "usage": {
            "input_tokens": int(_get(usage, "input_tokens", 0) or 0),
            "output_tokens": int(_get(usage, "output_tokens", 0) or 0),
        },
        "request_id": _get(response, "request_id"),
        "model": selected_model,
    }


async def audio_chat_async(prompt: str, audio_path: Path, model: str | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(audio_chat_sync, prompt, audio_path, model)
