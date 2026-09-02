import asyncio
import json
from collections.abc import AsyncGenerator
from http import HTTPStatus
from typing import Any

import httpx

from app.config import settings


class DashScopeError(RuntimeError):
    pass


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def format_dashscope_error(response: Any, fallback: str = "DashScope request failed") -> str:
    status_code = _get(response, "status_code")
    code = str(_get(response, "code", "") or "").strip()
    message = str(_get(response, "message", fallback) or fallback).strip()
    request_id = str(_get(response, "request_id", "") or "").strip()
    if code == "AllocationQuota.FreeTierOnly" or "FreeTierOnly" in message:
        message = (
            "DashScope 拒绝按量付费：当前账号开启了“免费额度用完即停”，"
            "或尚未完成实名认证。请在阿里云百炼免费额度页面关闭该开关；"
            "配置同步可能需要约 30 分钟。"
        )
    details = []
    if status_code:
        details.append(f"HTTP {status_code}")
    if code:
        details.append(code)
    if request_id:
        details.append(f"request_id={request_id}")
    return f"{message} ({', '.join(details)})" if details else message


def _usage(response: Any) -> dict[str, int]:
    usage = _get(response, "usage", {}) or {}
    input_tokens = _get(usage, "input_tokens", 0) or _get(usage, "prompt_tokens", 0) or 0
    output_tokens = _get(usage, "output_tokens", 0) or _get(usage, "completion_tokens", 0) or 0
    return {"input_tokens": int(input_tokens), "output_tokens": int(output_tokens)}


def llm_chat_sync(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    if not settings.cloud.dashscope_api_key:
        raise DashScopeError("DashScope API key is not configured")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    if response_format:
        payload["response_format"] = response_format
    if max_tokens:
        payload["max_tokens"] = max_tokens

    headers = {"Authorization": f"Bearer {settings.cloud.dashscope_api_key}"}
    if settings.cloud.dashscope_workspace_id:
        headers["X-DashScope-WorkSpace"] = settings.cloud.dashscope_workspace_id
    try:
        response = httpx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120.0,
        )
    except httpx.HTTPError as exc:
        raise DashScopeError(f"DashScope request failed: {exc}") from exc
    if response.status_code != HTTPStatus.OK:
        try:
            error = response.json()
        except ValueError:
            error = {"message": response.text or "DashScope request failed"}
        error["status_code"] = response.status_code
        error.setdefault("request_id", response.headers.get("x-request-id"))
        raise DashScopeError(format_dashscope_error(error))

    body = response.json()
    choices = body.get("choices") or []
    if not choices:
        raise DashScopeError("DashScope response did not include choices")
    message = choices[0].get("message") or {}
    tool_calls = [item for item in message.get("tool_calls") or [] if isinstance(item, dict)]
    content = str(message.get("content") or "")
    usage = _usage(body)
    return {
        "content": content,
        "tool_calls": tool_calls,
        "usage": usage,
        "request_id": body.get("id") or response.headers.get("x-request-id"),
        "model": str(body.get("model") or model),
    }


async def llm_chat_async(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        llm_chat_sync,
        model,
        messages,
        tools,
        response_format,
        temperature,
        max_tokens,
    )


async def llm_chat_stream(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    if not settings.cloud.dashscope_api_key:
        raise DashScopeError("DashScope API key is not configured")
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {settings.cloud.dashscope_api_key}"}
    if settings.cloud.dashscope_workspace_id:
        headers["X-DashScope-WorkSpace"] = settings.cloud.dashscope_workspace_id

    try:
        async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
            "POST",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != HTTPStatus.OK:
                raw = await response.aread()
                try:
                    error = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    error = {"message": raw.decode("utf-8", errors="replace")}
                error["status_code"] = response.status_code
                error.setdefault("request_id", response.headers.get("x-request-id"))
                raise DashScopeError(format_dashscope_error(error))
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                chunk = json.loads(data)
                choices = chunk.get("choices") or []
                delta = (choices[0].get("delta") or {}) if choices else {}
                yield {
                    "content": str(delta.get("content") or ""),
                    "tool_calls": [
                        item for item in delta.get("tool_calls") or [] if isinstance(item, dict)
                    ],
                    "usage": _usage(chunk),
                    "request_id": chunk.get("id") or response.headers.get("x-request-id"),
                    "model": str(chunk.get("model") or model),
                }
    except httpx.HTTPError as exc:
        raise DashScopeError(f"DashScope streaming request failed: {exc}") from exc
