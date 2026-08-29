import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.cloud_api.dashscope_client import llm_chat_sync


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return str(content)


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _standard_tool_calls(raw_tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for index, tool_call in enumerate(raw_tool_calls):
        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = function.get("name") or tool_call.get("name")
        if not name:
            continue
        converted.append(
            {
                "name": str(name),
                "args": _parse_tool_args(function.get("arguments")),
                "id": str(tool_call.get("id") or tool_call.get("tool_call_id") or f"call_{index}"),
                "type": "tool_call",
            }
        )
    return converted


def _convert_tools_to_dashscope(tools: list[Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict):
            converted.append(tool)
            continue
        name = getattr(tool, "name", None)
        description = getattr(tool, "description", "")
        args_schema = getattr(tool, "args_schema", None)
        parameters = {}
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            parameters = args_schema.model_json_schema()
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name or tool.__class__.__name__,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
    return converted


def _dashscope_tool_calls(message: AIMessage) -> list[dict[str, Any]]:
    raw = message.response_metadata.get("tool_calls") if message.response_metadata else None
    if isinstance(raw, list) and raw:
        return [item for item in raw if isinstance(item, dict)]

    converted = []
    for index, tool_call in enumerate(message.tool_calls or []):
        converted.append(
            {
                "id": str(tool_call.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": str(tool_call.get("name") or ""),
                    "arguments": json.dumps(tool_call.get("args") or {}, ensure_ascii=False),
                },
            }
        )
    return converted


def _messages_to_dashscope(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = "user"
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, ToolMessage):
            role = "tool"
        elif isinstance(message, HumanMessage):
            role = "user"

        item: dict[str, Any] = {"role": role, "content": _content_to_text(message.content)}
        if isinstance(message, AIMessage):
            tool_calls = _dashscope_tool_calls(message)
            if tool_calls:
                item["tool_calls"] = tool_calls
        if isinstance(message, ToolMessage):
            item["tool_call_id"] = message.tool_call_id
            if message.name:
                item["name"] = message.name
        converted.append(item)
    return converted


class ChatDashScope(BaseChatModel):
    model_name: str = Field(default="qwen-max", alias="model")
    temperature: float = 0.2
    max_tokens: int | None = None

    @property
    def _llm_type(self) -> str:
        return "dashscope-chat"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        return self.bind(tools=_convert_tools_to_dashscope(tools), **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = llm_chat_sync(
            model=self.model_name,
            messages=_messages_to_dashscope(messages),
            tools=kwargs.get("tools"),
            response_format=kwargs.get("response_format"),
            temperature=float(kwargs.get("temperature", self.temperature)),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        usage = response.get("usage", {})
        raw_tool_calls = response.get("tool_calls") or []
        content = response.get("content") or ""
        message = AIMessage(
            content=content,
            tool_calls=_standard_tool_calls(raw_tool_calls),
            response_metadata={
                "provider": "dashscope",
                "model": self.model_name,
                "request_id": response.get("request_id"),
                "usage": usage,
                "tool_calls": raw_tool_calls,
            },
        )
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output={
                "provider": "dashscope",
                "model": self.model_name,
                "request_id": response.get("request_id"),
                "usage": usage,
            },
        )
