import asyncio
from collections.abc import AsyncGenerator
from http import HTTPStatus
from typing import Any

import dashscope

from app.config import settings


class DashScopeError(RuntimeError):
    pass


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _message_content(response: Any) -> str:
    output = _get(response, "output", {}) or {}
    choices = _get(output, "choices", []) or []
    if choices:
        message = _get(choices[0], "message", {}) or {}
        content = _get(message, "content")
        if content is not None:
            return str(content)
    text = _get(output, "text")
    if text is not None:
        return str(text)
    raise DashScopeError("DashScope response did not include message content")


def _message_tool_calls(response: Any) -> list[dict[str, Any]]:
    output = _get(response, "output", {}) or {}
    choices = _get(output, "choices", []) or []
    if not choices:
        return []
    message = _get(choices[0], "message", {}) or {}
    tool_calls = _get(message, "tool_calls", []) or []
    return [item for item in tool_calls if isinstance(item, dict)]


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

    call_kwargs: dict[str, Any] = {
        "model": model,
        "api_key": settings.cloud.dashscope_api_key,
        "workspace": settings.cloud.dashscope_workspace_id or None,
        "messages": messages,
        "result_format": "message",
        "temperature": temperature,
    }
    if tools:
        call_kwargs["tools"] = tools
    if response_format:
        call_kwargs["response_format"] = response_format
    if max_tokens:
        call_kwargs["max_tokens"] = max_tokens

    response = dashscope.Generation.call(**call_kwargs)
    status_code = _get(response, "status_code")
    if status_code and status_code != HTTPStatus.OK:
        message = _get(response, "message", "DashScope request failed")
        raise DashScopeError(str(message))

    usage = _usage(response)
    return {
        "content": _message_content(response),
        "tool_calls": _message_tool_calls(response),
        "usage": usage,
        "request_id": _get(response, "request_id"),
        "model": model,
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
    def call_stream() -> Any:
        return dashscope.Generation.call(
            model=model,
            api_key=settings.cloud.dashscope_api_key,
            workspace=settings.cloud.dashscope_workspace_id or None,
            messages=messages,
            tools=tools,
            result_format="message",
            stream=True,
            incremental_output=True,
        )

    responses = await asyncio.to_thread(call_stream)
    for response in responses:
        yield {
            "content": _message_content(response),
            "tool_calls": _message_tool_calls(response),
            "usage": _usage(response),
            "request_id": _get(response, "request_id"),
            "model": model,
        }
