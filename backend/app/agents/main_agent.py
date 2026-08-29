import json
import re
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from app.agents.base import toolbox, user_request
from app.agents.runtime import final_ai_json, message_tool_trace, message_usage_records
from app.agents.state import AgentState
from app.agents.tools.delegation import DelegationCollector, build_delegation_tools
from app.cloud_api.langchain_chat_model import ChatDashScope
from app.config import settings

ACTION_WORDS = (
    "生成",
    "添加",
    "翻译",
    "修改",
    "删除",
    "截取",
    "导出",
    "预览",
    "合并",
    "应用",
    "调整",
    "剪",
    "去除",
    "去掉",
    "放",
    "移动",
)

MAIN_AGENT_PROMPT = """
你是 AICut 的 Main Creative Agent，一个 ReAct 风格的视频创作 agent。
你不是关键词路由器，也不要按固定流程工作。你需要像剪辑师一样先理解用户目标和项目状态，再自主选择工具。

工作方式：
- 每次用户请求都必须先调用至少一个项目检查工具，例如 get_project_timeline、get_project_assets 或 get_project_subtitles。
- 面对导入素材后的自主剪辑、去停顿、生成预览或应用字幕，优先调用 build_packed_transcript、build_timeline_edl、validate_edl；需要看画面时调用 render_timeline_view。
- 用户明确要求生成、添加、翻译、修改、删除、截取、导出、预览时，必须调用至少一个 delegate_to_* 工具，不能只给建议。
- 需要专业分析或生成文件时，调用 delegate_to_audio_agent、delegate_to_video_agent、delegate_to_subtitle_agent 或 delegate_to_broll_agent。
- 可以多次委托同一个 specialist，但每次 task 必须具体，例如“检测主视频静音并给出可删除区间”。
- 导入素材后的自主粗剪应优先委托：Audio Agent 检测静音/停顿，Video Agent 检测镜头变化/缩略图巡检，Subtitle Agent 检查字幕，B-roll Agent 判断覆盖素材。
- 生成预览或交付视频时，必须让 specialist 调用 render_edl_preview 或明确的 ffmpeg_* 输出工具，并以工具返回路径为准。
- 如果用户只是在讨论方向，可以直接回复，不必强行生成 EditPlan。
- 如果用户要求为某个时间段生成/添加英文字幕，先读取现有字幕；若已有字幕覆盖该时间段，委托 Subtitle Agent 使用原 cue 时间生成英文字幕操作；若没有字幕但有音视频素材，委托 Subtitle Agent 尝试基于可用工具判断是否能生成。
- 不要编造 asset_id、cue_id、时间码或输出文件路径。
- 时间线修改必须以可审批 EditPlan 的 operations 形式产生；你不能直接写入时间线。
- FFmpeg 输出文件只能来自 specialist 工具返回的 rendered_files。
- 不要声称字幕、预览或时间线已经应用，除非工具返回了 subtitle_path、output_path、preview_path 或 Review Agent 生成了 operations。
- 支持的编辑意图包括删除区间、插入素材、拆分/调整/删除 clip、字幕增删改、B-roll、音量/淡入淡出、marker、transform 和 effect。

最终只输出 JSON：
{"summary":string,"creative_direction":string,"needs_review":boolean}
""".strip()


def create_main_agent(tools: list[Any]) -> Any:
    return create_agent(
        model=ChatDashScope(
            model=settings.cloud.main_agent_model or settings.cloud.agent_model,
            temperature=0.3,
        ),
        tools=tools,
        system_prompt=MAIN_AGENT_PROMPT,
        name="main_agent",
    )


def _fallback_response(error: Exception) -> dict[str, Any]:
    return {
        "summary": f"Main Agent 执行失败：{type(error).__name__}: {error}",
        "creative_direction": "暂时无法完成自主分析。",
        "needs_review": False,
    }


def _delegation_guard_targets(request: str) -> list[str]:
    lowered = request.lower()
    if not any(word in request for word in ACTION_WORDS):
        return []

    targets: list[str] = []
    if re.search(r"字幕|cue|srt|vtt|英文|中文|翻译|双语|caption|subtitle", lowered):
        targets.append("delegate_to_subtitle_agent")
    if re.search(r"静音|停顿|音量|声音|响度|淡入|淡出|audio|volume|silence", lowered):
        targets.append("delegate_to_audio_agent")
    if re.search(r"视频|画面|裁剪|转码|导出|预览|合并|拼接|横|竖|比例|封面|镜头|video|preview|export", lowered):
        targets.append("delegate_to_video_agent")
    if re.search(r"b-roll|broll|素材|贴纸|覆盖|叠加|overlay", lowered):
        targets.append("delegate_to_broll_agent")

    return targets or ["delegate_to_video_agent"]


async def _run_delegation_guard(
    request: str,
    main_tools: list[Any],
    collector: DelegationCollector,
) -> list[dict[str, Any]]:
    if collector.outputs:
        return []
    traces: list[dict[str, Any]] = []
    tools_by_name = {tool.name: tool for tool in main_tools}
    for tool_name in _delegation_guard_targets(request):
        tool = tools_by_name.get(tool_name)
        if tool is None:
            continue
        result = await tool.ainvoke(
            {
                "task": (
                    "Main Agent 已识别这是需要实施的剪辑请求，但未完成委托。"
                    f"请直接基于项目工具完成这个任务并输出可审批 operations：{request}"
                )
            }
        )
        traces.append(
            {
                "title": "补充执行委托",
                "detail": f"Main Agent 未产出可应用计划，已自动委托 {result.get('agent', tool_name)} 继续执行。",
                "data": {
                    "tool": tool_name,
                    "operation_count": len(result.get("operations") or []),
                    "rendered_files": result.get("rendered_files") or [],
                    "ok": result.get("ok"),
                },
            }
        )
    return traces


async def run_main_node(state: AgentState) -> AgentState:
    tools = toolbox(state)
    collector = DelegationCollector()
    main_tools = [
        *[tools.get(tool_name) for tool_name in tools.names_for("main_agent")],
        *build_delegation_tools(state, tools, collector),
    ]
    payload = {
        "user_request": user_request(state),
        "project_id": state.get("project_id"),
        "available_tools": [tool.name for tool in main_tools],
        "tool_policy": "Fetch project details with tools before making claims. Delegate explicit edit requests.",
        "required_final_output": "JSON object only",
    }
    request = user_request(state)
    try:
        result = await create_main_agent(main_tools).ainvoke(
            {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]}
        )
        messages = list(result.get("messages") or [])
        response = final_ai_json(messages)
        usage_records = message_usage_records("main_agent", messages)
        tool_calls = message_tool_trace(messages)
    except Exception as exc:  # noqa: BLE001 - main agent failures return a usable response.
        response, usage_records, tool_calls = _fallback_response(exc), [], []

    guard_trace = await _run_delegation_guard(request, main_tools, collector)
    summary = str(response.get("summary") or "Main Agent 完成。")
    creative_direction = str(response.get("creative_direction") or "")
    detail = summary if not creative_direction else f"{summary} {creative_direction}"
    outputs = {**state.get("agent_outputs", {}), **collector.outputs}
    return {
        "agent_outputs": outputs,
        "reply": detail,
        "usage_records": [
            *state.get("usage_records", []),
            *usage_records,
            *collector.usage_records,
        ],
        "route_history": [*state.get("route_history", []), "main_agent"],
        "trace": [
            *state.get("trace", []),
            *collector.trace,
            *guard_trace,
            {
                "title": "Main Agent(create_agent) 执行完成",
                "detail": detail,
                "data": {
                    "available_tools": [tool.name for tool in main_tools],
                    "delegated_agents": list(collector.outputs.keys()),
                    "tool_calls": tool_calls,
                },
            },
        ],
    }


def route_after_main(state: AgentState) -> str:
    return "review" if state.get("agent_outputs") else "end"
