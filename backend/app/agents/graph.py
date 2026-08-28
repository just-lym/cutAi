import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.chat_model import ChatDashScope
from app.agents.state import AgentState
from app.config import settings
from app.tools.media_tools import detect_silence
from app.tools.timeline_tools import SUPPORTED_OPERATIONS, validate_edit_plan


def _json_from_text(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Agent returned non-object JSON")
    return parsed


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


async def _call_json_agent(
    agent_name: str,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    temperature: float = 0.2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    llm = ChatDashScope(model=model, temperature=temperature)
    message = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ],
        response_format={"type": "json_object"},
    )
    metadata = dict(message.response_metadata or {})
    usage = dict(metadata.get("usage") or {})
    usage_record = {
        "agent": agent_name,
        "provider": "dashscope",
        "model": metadata.get("model") or model,
        "request_id": metadata.get("request_id"),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }
    return _json_from_text(_content_text(message.content)), usage_record


def _trace(state: AgentState, title: str, detail: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [
        *state.get("trace", []),
        {
            "title": title,
            "detail": detail,
            "data": data or {},
        },
    ]


def _append_usage(state: AgentState, usage: dict[str, Any]) -> list[dict[str, Any]]:
    return [*state.get("usage_records", []), usage]


def _user_request(state: AgentState) -> str:
    messages = state.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _content_text(message.content)
    return ""


def _assets_summary(assets: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        asset
        for asset in assets
        if asset.get("processing_status") == "COMPLETED" and asset.get("duration_ms")
    ]
    max_duration_ms = max((int(asset.get("duration_ms") or 0) for asset in completed), default=0)
    return {
        "asset_count": len(assets),
        "completed_media_count": len(completed),
        "max_asset_duration_ms": max_duration_ms,
        "media": [
            {
                "id": asset.get("id"),
                "name": asset.get("original_name"),
                "type": asset.get("type"),
                "duration_ms": asset.get("duration_ms"),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "frame_rate": asset.get("frame_rate"),
            }
            for asset in assets[:20]
        ],
    }


def _effective_duration_ms(timeline: dict[str, Any], assets: list[dict[str, Any]]) -> int:
    timeline_duration = int(timeline.get("duration_ms") or 0)
    asset_duration = int(_assets_summary(assets)["max_asset_duration_ms"])
    return max(timeline_duration, asset_duration)


def _timeline_summary(timeline: dict[str, Any], assets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    asset_list = assets or []
    tracks = timeline.get("tracks", [])
    return {
        "duration_ms": int(timeline.get("duration_ms") or 0),
        "effective_duration_ms": _effective_duration_ms(timeline, asset_list),
        "track_count": len(tracks),
        "clip_count": sum(len(track.get("clips", [])) for track in tracks),
        "subtitle_count": sum(len(track.get("cues", [])) for track in tracks),
        "assets": _assets_summary(asset_list),
    }


def _timeline_context(timeline: dict[str, Any], assets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    asset_list = assets or []
    tracks = []
    for track in timeline.get("tracks", []):
        clips = track.get("clips") or []
        cues = track.get("cues") or []
        tracks.append(
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
        "effective_duration_ms": _effective_duration_ms(timeline, asset_list),
        "width": timeline.get("width"),
        "height": timeline.get("height"),
        "frame_rate": timeline.get("frame_rate"),
        "tracks": tracks,
        "assets": _assets_summary(asset_list),
    }


def _agent_intents(request: str) -> list[str]:
    text = request.lower()
    intents: list[str] = []
    if any(keyword in request for keyword in ["字幕", "错字", "文案", "转写", "断句"]) or "subtitle" in text:
        intents.append("subtitle_agent")
    if any(keyword in request for keyword in ["静音", "停顿", "空白", "音量", "声音", "淡入", "淡出"]) or any(
        keyword in text for keyword in ["silence", "volume", "audio"]
    ):
        intents.append("audio_agent")
    if any(keyword in request for keyword in ["b-roll", "B-roll", "素材", "插入", "画面", "镜头"]) or any(
        keyword in text for keyword in ["broll", "b-roll"]
    ):
        intents.append("broll_agent")
    return intents


def _fallback_next(state: AgentState) -> str:
    outputs = state.get("agent_outputs", {})
    for agent in _agent_intents(_user_request(state)):
        if agent not in outputs:
            return agent
    if outputs:
        return "review"
    return "respond"


def _asset_path(asset: dict[str, Any]) -> str:
    return str(settings.data_root / str(asset.get("file_path")))


def _subtitle_cues(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    for track in timeline.get("tracks", []):
        if track.get("id") == "subtitles":
            return list(track.get("cues") or [])
    return []


def _referenced_asset_ids(timeline: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for track in timeline.get("tracks", []):
        for clip in track.get("clips") or []:
            asset_id = clip.get("asset_id")
            if asset_id:
                ids.add(str(asset_id))
    return ids


def _normalize_operations(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    operations: list[dict[str, Any]] = []
    for item in items[:30]:
        if isinstance(item, dict) and item.get("type") in SUPPORTED_OPERATIONS:
            operations.append(item)
    return operations


def _collect_operations(agent_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for output in agent_outputs.values():
        operations.extend(_normalize_operations(output.get("operations")))
        for insertion in output.get("insertions") or []:
            if not isinstance(insertion, dict) or not insertion.get("asset_id"):
                continue
            operations.append(
                {
                    "type": "INSERT_BROLL_OVERLAY",
                    "asset_id": insertion["asset_id"],
                    "position_ms": int(insertion.get("position_ms") or 0),
                    "duration_ms": int(insertion.get("duration_ms") or 4000),
                    "context": insertion.get("context") or insertion.get("visual_description") or "",
                }
            )
    return operations


def _valid_operations(operations: list[dict[str, Any]], timeline: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    kept: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for operation in operations:
        errors = validate_edit_plan([operation], timeline)
        if errors:
            conflicts.extend(errors)
        else:
            kept.append(operation)
    combined_errors = validate_edit_plan(kept, timeline)
    if combined_errors:
        conflicts.extend(combined_errors)
        return [], conflicts
    return kept, conflicts


async def supervisor_node(state: AgentState) -> AgentState:
    route_history = state.get("route_history", [])
    if len(route_history) >= 4:
        return {
            "next": "review",
            "trace": _trace(
                state,
                "Supervisor Agent 调用大模型",
                "已达到本轮最大调度次数，转交 Review Agent 合并结果。",
                {"next": "review"},
            ),
        }

    payload = {
        "user_request": _user_request(state),
        "timeline": _timeline_summary(state.get("timeline", {}), state.get("assets", [])),
        "finished_agents": list(state.get("agent_outputs", {}).keys()),
        "route_history": route_history,
    }
    system_prompt = """
你是视频剪辑 AI 平台的 Supervisor Agent。
你只能输出 JSON：{"next":"subtitle_agent|audio_agent|broll_agent|review|respond","reason":"简短原因"}。
可调度专业 Agent：
- subtitle_agent：字幕分析、纠错、断句、翻译、ASR 生成
- audio_agent：音频分析、音效检测与删除、音量调整
- broll_agent：B-roll 素材推荐、插入位置识别、视频生成提示词
如果已经收集到需要的 specialist 输出，选择 review。
如果用户是在询问、分析、解释、让你判断可行性，或当前系统不能真正执行该任务，选择 respond 或让 specialist 返回自然语言建议，不要硬凑审批计划。
""".strip()
    response, usage = await _call_json_agent(
        "supervisor",
        settings.cloud.supervisor_model or settings.cloud.agent_model,
        system_prompt,
        payload,
    )
    next_agent = str(response.get("next") or _fallback_next(state))
    allowed = {"subtitle_agent", "audio_agent", "broll_agent", "review", "respond"}
    if next_agent not in allowed or next_agent in route_history:
        next_agent = _fallback_next(state)
    return {
        "next": next_agent,
        "route_history": [*route_history, next_agent],
        "usage_records": _append_usage(state, usage),
        "trace": _trace(
            state,
            "Supervisor Agent 调用大模型",
            str(response.get("reason") or "已选择下一步 Agent。"),
            {"next": next_agent, "model": usage["model"]},
        ),
    }


async def run_subtitle_node(state: AgentState) -> AgentState:
    cues = _subtitle_cues(state.get("timeline", {}))
    assets = state.get("assets", [])
    available_media = [
        {
            "id": asset.get("id"),
            "name": asset.get("original_name"),
            "type": asset.get("type"),
            "duration_ms": asset.get("duration_ms"),
            "file_path": _asset_path(asset),
        }
        for asset in assets
        if asset.get("processing_status") == "COMPLETED" and asset.get("type") in {"VIDEO", "AUDIO"}
    ]
    payload = {
        "user_request": _user_request(state),
        "timeline": _timeline_context(state.get("timeline", {}), assets),
        "subtitles": cues[:50],
        "assets": _assets_summary(assets),
        "available_media_for_asr": available_media[:10],
        "implemented_subtitle_operations": ["UPDATE_SUBTITLE"],
    }
    system_prompt = """
你是 AICut 的 subtitle Agent，负责字幕分析、断句、纠错和字幕相关编辑建议。
只输出 JSON：{"summary":string,"operations":[...]}。
operations 只能使用 UPDATE_SUBTITLE。没有字幕或没有可靠修改时返回空 operations。
如果用户要求生成新字幕、翻译字幕或英文字幕，但当前没有已有字幕且系统没有提供 ASR/翻译工具结果，请自然说明：时间范围是否有效、是否存在可用媒体、当前缺少的是 ASR/翻译执行链路或字幕来源。不要说缺少音频源，除非 available_media_for_asr 为空。不要编造字幕。
判断时间范围时优先使用 timeline.effective_duration_ms，而不是只看 duration_ms。
""".strip()
    response, usage = await _call_json_agent(
        "subtitle_agent",
        settings.cloud.specialist_model or settings.cloud.agent_model,
        system_prompt,
        payload,
    )
    outputs = dict(state.get("agent_outputs", {}))
    outputs["subtitle_agent"] = {
        "summary": str(response.get("summary") or "Subtitle Agent 完成。"),
        "operations": _normalize_operations(response.get("operations")),
    }
    return {
        "agent_outputs": outputs,
        "usage_records": _append_usage(state, usage),
        "trace": _trace(
            state,
            "Subtitle Agent 调用大模型完成",
            outputs["subtitle_agent"]["summary"],
            {
                "operation_count": len(outputs["subtitle_agent"]["operations"]),
                "available_media_count": len(available_media),
                "model": usage["model"],
            },
        ),
    }


async def run_audio_node(state: AgentState) -> AgentState:
    timeline = state.get("timeline", {})
    assets = state.get("assets", [])
    referenced_ids = _referenced_asset_ids(timeline)
    candidate = next((asset for asset in assets if str(asset.get("id")) in referenced_ids), None)
    if candidate is None:
        candidate = next(
            (
                asset
                for asset in assets
                if asset.get("processing_status") == "COMPLETED" and asset.get("type") in {"VIDEO", "AUDIO"}
            ),
            None,
        )
    silence_segments: list[dict[str, Any]] = []
    silence_error = None
    if candidate:
        try:
            silence_segments = await detect_silence(settings.data_root / str(candidate.get("file_path")))
        except Exception as exc:
            silence_error = f"{type(exc).__name__}: {exc}"

    payload = {
        "user_request": _user_request(state),
        "timeline": _timeline_context(timeline, assets),
        "media_asset": {
            "id": candidate.get("id"),
            "name": candidate.get("original_name"),
            "path": _asset_path(candidate),
        }
        if candidate
        else None,
        "silence_segments": silence_segments[:50],
        "silence_error": silence_error,
    }
    system_prompt = """
你是 AICut 的 audio Agent，负责静音检测、音量分析、淡入淡出建议。
只输出 JSON：{"summary":string,"operations":[...]}。
DELETE_RANGE 必须来自输入中的 silence_segments，不能凭空编造静音区间。
可用操作：DELETE_RANGE、SET_VOLUME、FADE_IN、FADE_OUT。没有可靠建议时返回空 operations。
判断时间范围时优先使用 timeline.effective_duration_ms，而不是只看 duration_ms。
""".strip()
    response, usage = await _call_json_agent(
        "audio_agent",
        settings.cloud.specialist_model or settings.cloud.agent_model,
        system_prompt,
        payload,
    )
    outputs = dict(state.get("agent_outputs", {}))
    outputs["audio_agent"] = {
        "summary": str(response.get("summary") or "Audio Agent 完成。"),
        "operations": _normalize_operations(response.get("operations")),
        "silence_segments": silence_segments,
    }
    return {
        "agent_outputs": outputs,
        "usage_records": _append_usage(state, usage),
        "trace": _trace(
            state,
            "Audio Agent 调用大模型完成",
            outputs["audio_agent"]["summary"],
            {
                "operation_count": len(outputs["audio_agent"]["operations"]),
                "silence_count": len(silence_segments),
                "silence_error": silence_error,
                "model": usage["model"],
            },
        ),
    }


async def run_broll_node(state: AgentState) -> AgentState:
    timeline = state.get("timeline", {})
    assets = state.get("assets", [])
    payload = {
        "user_request": _user_request(state),
        "timeline": _timeline_context(timeline, assets),
        "available_assets": [
            {
                "id": asset.get("id"),
                "name": asset.get("original_name"),
                "type": asset.get("type"),
                "duration_ms": asset.get("duration_ms"),
            }
            for asset in assets[:30]
        ],
    }
    system_prompt = """
你是 AICut 的 b-roll Agent，负责识别内容转折点、推荐覆盖素材或生成视频提示词。
只输出 JSON：{"summary":string,"operations":[...],"insertions":[...]}。
如使用现有素材，operations 使用 INSERT_BROLL_OVERLAY。每段 3-6 秒，避免覆盖无素材的位置。
如果没有合适素材，可在 insertions 中给出 visual_description 和 prompt_en，但不要编造 asset_id。
判断时间范围时优先使用 timeline.effective_duration_ms，而不是只看 duration_ms。
""".strip()
    response, usage = await _call_json_agent(
        "broll_agent",
        settings.cloud.supervisor_model or settings.cloud.agent_model,
        system_prompt,
        payload,
    )
    outputs = dict(state.get("agent_outputs", {}))
    outputs["broll_agent"] = {
        "summary": str(response.get("summary") or "B-roll Agent 完成。"),
        "operations": _normalize_operations(response.get("operations")),
        "insertions": response.get("insertions") if isinstance(response.get("insertions"), list) else [],
    }
    return {
        "agent_outputs": outputs,
        "usage_records": _append_usage(state, usage),
        "trace": _trace(
            state,
            "B-roll Agent 调用大模型完成",
            outputs["broll_agent"]["summary"],
            {
                "operation_count": len(outputs["broll_agent"]["operations"]),
                "insertion_count": len(outputs["broll_agent"]["insertions"]),
                "model": usage["model"],
            },
        ),
    }


async def run_review_node(state: AgentState) -> AgentState:
    timeline = state.get("timeline", {})
    proposed_operations = _collect_operations(state.get("agent_outputs", {}))
    valid_operations, deterministic_conflicts = _valid_operations(proposed_operations, timeline)
    payload = {
        "user_request": _user_request(state),
        "timeline": _timeline_summary(timeline, state.get("assets", [])),
        "agent_outputs": state.get("agent_outputs", {}),
        "valid_operations": valid_operations,
        "validation_conflicts": deterministic_conflicts,
    }
    system_prompt = """
你是 AICut 的 review Agent。
职责：合并 specialist 输出，按时间顺序整理，指出冲突，输出最终 EditPlan。
只输出 JSON：{"plan":{"summary":string,"operations":[...],"conflicts":[...],"requires_user_approval":boolean}}。
不要输出未通过 validation_conflicts 的操作。
如果没有 valid_operations，请给自然语言回复，说明当前能做什么、缺什么，不要把回复写成必须提交计划。
判断时间范围时优先使用 timeline.effective_duration_ms，而不是只看 duration_ms。
""".strip()
    response, usage = await _call_json_agent(
        "review",
        settings.cloud.review_model or settings.cloud.agent_model,
        system_prompt,
        payload,
    )
    plan = response.get("plan") if isinstance(response.get("plan"), dict) else {}
    operations = _normalize_operations(plan.get("operations")) or valid_operations
    operations, review_conflicts = _valid_operations(operations, timeline)
    conflicts = [
        *deterministic_conflicts,
        *review_conflicts,
        *[str(item) for item in plan.get("conflicts", []) if item],
    ]
    summary = str(plan.get("summary") or f"Review Agent 合并出 {len(operations)} 条编辑建议。")
    edit_plan = {
        "summary": summary,
        "operations": operations,
        "conflicts": conflicts,
        "requires_user_approval": bool(operations),
    }
    return {
        "edit_plans": edit_plan,
        "reply": summary,
        "awaiting_user": bool(operations),
        "usage_records": _append_usage(state, usage),
        "trace": _trace(
            state,
            "Review Agent 调用大模型完成",
            summary,
            {"operation_count": len(operations), "conflict_count": len(conflicts), "model": usage["model"]},
        ),
    }


async def respond_node(state: AgentState) -> AgentState:
    payload = {
        "user_request": _user_request(state),
        "timeline": _timeline_summary(state.get("timeline", {}), state.get("assets", [])),
    }
    system_prompt = """
你是 AICut 的 respond Agent。用户没有提出可执行的剪辑计划时，直接给出简短中文回复。
只输出 JSON：{"reply":string}。
回复要理解用户自然语言，不要假定用户一定要提交 EditPlan。判断视频长度时使用 timeline.effective_duration_ms。
""".strip()
    response, usage = await _call_json_agent(
        "respond",
        settings.cloud.supervisor_model or settings.cloud.agent_model,
        system_prompt,
        payload,
    )
    reply = str(response.get("reply") or "我理解了，请告诉我具体想调整字幕、音频还是 B-roll。")
    return {
        "reply": reply,
        "edit_plans": None,
        "awaiting_user": False,
        "usage_records": _append_usage(state, usage),
        "trace": _trace(state, "Respond Agent 调用大模型完成", reply, {"model": usage["model"]}),
    }


def route_next(state: AgentState) -> str:
    return state.get("next", "respond")


def build_supervisor_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("subtitle_agent", run_subtitle_node)
    graph.add_node("audio_agent", run_audio_node)
    graph.add_node("broll_agent", run_broll_node)
    graph.add_node("review", run_review_node)
    graph.add_node("respond", respond_node)
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "subtitle_agent": "subtitle_agent",
            "audio_agent": "audio_agent",
            "broll_agent": "broll_agent",
            "review": "review",
            "respond": "respond",
        },
    )
    graph.add_edge("subtitle_agent", "supervisor")
    graph.add_edge("audio_agent", "supervisor")
    graph.add_edge("broll_agent", "supervisor")
    graph.add_edge("review", END)
    graph.add_edge("respond", END)
    return graph.compile()


async def run_agent_graph(
    content: str,
    project_id: str,
    project_dir: str,
    timeline_version: int,
    timeline: dict[str, Any],
    assets: list[dict[str, Any]],
) -> AgentState:
    initial_state: AgentState = {
        "messages": [HumanMessage(content=content)],
        "project_id": project_id,
        "project_dir": project_dir,
        "timeline_version": timeline_version,
        "timeline": timeline,
        "assets": assets,
        "edit_plans": None,
        "agent_outputs": {},
        "awaiting_user": False,
        "total_costs": 0.0,
        "trace": [
            {
                "title": "初始化 AgentState",
                "detail": "已按 03-多Agent系统.md 构建共享状态，准备进入 Supervisor。",
                "data": {
                    "project_id": project_id,
                    "timeline_version": timeline_version,
                    "timeline_duration_ms": int(timeline.get("duration_ms") or 0),
                    "effective_duration_ms": _effective_duration_ms(timeline, assets),
                    "asset_count": len(assets),
                },
            }
        ],
        "route_history": [],
        "reply": "",
        "usage_records": [],
    }
    graph = build_supervisor_graph()
    return await graph.ainvoke(initial_state, {"recursion_limit": 12})
