import asyncio
import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import dashscope

from app.config import settings


class AgentLLMError(RuntimeError):
    pass


@dataclass
class AgentLLMResult:
    reply: str
    operations: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    model: str = ""


SYSTEM_PROMPT = """
你是 AICut 的剪辑规划 Agent。你要根据用户目标和当前时间线，生成可人工审批的结构化剪辑计划。

只允许输出 JSON，不要输出 Markdown。JSON 结构必须是：
{
  "reply": "给用户看的简短回复",
  "trace": [
    {"title": "步骤标题", "detail": "给用户看的执行说明", "data": {"可选": "少量结构化数据"}}
  ],
  "operations": []
}

trace 是可展示的执行过程，不能包含隐藏思维链、长篇推理或敏感信息。它应该说明你读取了哪些上下文、识别了哪些目标、生成了哪些操作。

operations 只能使用这些类型：
1. DELETE_RANGE: {"type":"DELETE_RANGE","start_ms":number,"end_ms":number,"reason":string}
2. SET_VOLUME: {"type":"SET_VOLUME","start_ms":number,"end_ms":number,"volume":number}
3. UPDATE_SUBTITLE: {"type":"UPDATE_SUBTITLE","cue_id":string,"text":string,"start_ms":number,"end_ms":number}
4. INSERT_BROLL_OVERLAY: {"type":"INSERT_BROLL_OVERLAY","asset_id":string,"position_ms":number,"duration_ms":number,"context":string}
5. FADE_IN: {"type":"FADE_IN","start_ms":number,"duration_ms":number}
6. FADE_OUT: {"type":"FADE_OUT","start_ms":number,"duration_ms":number}

如果当前上下文不足以可靠执行，就返回空 operations，并在 reply 中说明缺少什么。
""".strip()


def _timeline_context(timeline: dict[str, Any]) -> dict[str, Any]:
    tracks = timeline.get("tracks", [])
    context_tracks: list[dict[str, Any]] = []
    for track in tracks:
        clips = track.get("clips") or []
        cues = track.get("cues") or []
        context_tracks.append(
            {
                "id": track.get("id"),
                "type": track.get("type"),
                "clip_count": len(clips),
                "clips": clips[:20],
                "subtitle_count": len(cues),
                "cues": cues[:30],
            }
        )
    return {
        "duration_ms": int(timeline.get("duration_ms") or 0),
        "width": timeline.get("width"),
        "height": timeline.get("height"),
        "frame_rate": timeline.get("frame_rate"),
        "tracks": context_tracks,
    }


def _response_get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _response_content(response: Any) -> str:
    output = _response_get(response, "output", {})
    choices = _response_get(output, "choices", [])
    if choices:
        message = _response_get(choices[0], "message", {})
        content = _response_get(message, "content")
        if content:
            return str(content)
    text = _response_get(output, "text")
    if text:
        return str(text)
    raise AgentLLMError("DashScope response did not include message content")


def _response_usage(response: Any) -> tuple[int, int]:
    usage = _response_get(response, "usage", {}) or {}
    input_tokens = _response_get(usage, "input_tokens", 0) or _response_get(usage, "prompt_tokens", 0) or 0
    output_tokens = _response_get(usage, "output_tokens", 0) or _response_get(usage, "completion_tokens", 0) or 0
    return int(input_tokens), int(output_tokens)


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_trace(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "执行步骤")
        detail = str(item.get("detail") or "")
        data = item.get("data")
        normalized.append(
            {
                "title": title[:80],
                "detail": detail[:500],
                "data": data if isinstance(data, dict) else {},
            }
        )
    return normalized


def _normalize_operations(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items[:20] if isinstance(item, dict) and item.get("type")]


async def build_llm_plan(content: str, timeline: dict[str, Any]) -> AgentLLMResult:
    if not settings.cloud.dashscope_api_key:
        raise AgentLLMError("DashScope API key is not configured")

    model = settings.cloud.agent_model
    user_payload = {
        "user_request": content,
        "timeline": _timeline_context(timeline),
    }

    def call_dashscope() -> Any:
        return dashscope.Generation.call(
            model=model,
            api_key=settings.cloud.dashscope_api_key,
            workspace=settings.cloud.dashscope_workspace_id or None,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            result_format="message",
            response_format={"type": "json_object"},
            temperature=0.2,
        )

    response = await asyncio.to_thread(call_dashscope)
    status_code = _response_get(response, "status_code")
    if status_code and status_code != HTTPStatus.OK:
        message = _response_get(response, "message", "DashScope request failed")
        raise AgentLLMError(str(message))

    payload = _parse_json_object(_response_content(response))
    input_tokens, output_tokens = _response_usage(response)
    request_id = _response_get(response, "request_id")

    trace = [
        {
            "title": "调用 DashScope 大模型",
            "detail": f"已使用 {model} 生成剪辑计划。",
            "data": {"provider": "dashscope", "model": model},
        }
    ]
    trace.extend(_normalize_trace(payload.get("trace")))

    return AgentLLMResult(
        reply=str(payload.get("reply") or "已生成大模型剪辑建议。"),
        operations=_normalize_operations(payload.get("operations")),
        trace=trace,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        request_id=str(request_id) if request_id else None,
        model=model,
    )
