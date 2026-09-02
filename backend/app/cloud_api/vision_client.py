import asyncio
import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import dashscope

from app.cloud_api.dashscope_client import format_dashscope_error
from app.config import settings


class VisionError(RuntimeError):
    pass


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _response_text(response: Any) -> str:
    output = _get(response, "output", {}) or {}
    choices = _get(output, "choices", []) or []
    if not choices:
        raise VisionError("DashScope vision response did not include choices")
    message = _get(choices[0], "message", {}) or {}
    content = _get(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            text = _get(item, "text")
            if text:
                parts.append(str(text))
        if parts:
            return "\n".join(parts)
    raise VisionError("DashScope vision response did not include text")


def _usage(response: Any) -> dict[str, int]:
    usage = _get(response, "usage", {}) or {}
    return {
        "input_tokens": int(_get(usage, "input_tokens", 0) or 0),
        "output_tokens": int(_get(usage, "output_tokens", 0) or 0),
        "image_tokens": int(_get(usage, "image_tokens", 0) or 0),
    }


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise VisionError(f"Vision model returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VisionError("Vision model response must be a JSON object")
    return value


def vision_chat_sync(
    prompt: str,
    image_paths: list[Path],
    model: str | None = None,
) -> dict[str, Any]:
    if not settings.cloud.dashscope_api_key:
        raise VisionError("DashScope API key is not configured")
    paths = [path.resolve() for path in image_paths]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise VisionError(f"Vision input does not exist: {missing[0]}")
    content = [{"image": path.as_uri()} for path in paths]
    content.append({"text": prompt})
    response = dashscope.MultiModalConversation.call(
        model=model or settings.cloud.vision_model,
        api_key=settings.cloud.dashscope_api_key,
        workspace=settings.cloud.dashscope_workspace_id or None,
        messages=[{"role": "user", "content": content}],
    )
    status_code = _get(response, "status_code")
    if status_code and status_code != HTTPStatus.OK:
        raise VisionError(format_dashscope_error(response, "DashScope vision request failed"))
    return {
        "content": _response_text(response),
        "usage": _usage(response),
        "request_id": _get(response, "request_id"),
        "model": model or settings.cloud.vision_model,
    }


async def vision_chat_async(
    prompt: str,
    image_paths: list[Path],
    model: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(vision_chat_sync, prompt, image_paths, model)
