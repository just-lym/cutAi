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
        if isinstance(message, ToolMessage):
            item["tool_call_id"] = message.tool_call_id
        converted.append(item)
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
        ai_message = AIMessage(
            content=response["content"],
            response_metadata={
                "provider": "dashscope",
                "model": self.model_name,
                "request_id": response.get("request_id"),
                "usage": usage,
                "tool_calls": response.get("tool_calls") or [],
            },
        )
        return ChatResult(
            generations=[ChatGeneration(message=ai_message)],
            llm_output={
                "provider": "dashscope",
                "model": self.model_name,
                "request_id": response.get("request_id"),
                "usage": usage,
            },
        )
