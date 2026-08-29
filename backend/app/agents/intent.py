from typing import Any

INTENT_AGENT_MAP: dict[str, str] = {
    "UPDATE_SUBTITLE": "subtitle_agent",
    "CREATE_SUBTITLE": "subtitle_agent",
    "DELETE_RANGE": "audio_agent",
    "SET_VOLUME": "audio_agent",
    "FADE_IN": "audio_agent",
    "FADE_OUT": "audio_agent",
    "INSERT_BROLL_OVERLAY": "broll_agent",
    "GENERATE_BROLL": "broll_agent",
    "CUT_SEGMENT": "video_agent",
    "EXPORT_VIDEO": "video_agent",
}


INTENT_KEYWORDS: list[tuple[str, list[str], list[str]]] = [
    ("UPDATE_SUBTITLE", ["字幕", "错字", "文案", "断句", "标点", "翻译", "subtitle"], ["检查字幕"]),
    ("CREATE_SUBTITLE", ["转写", "识别语音", "生成字幕", "asr", "transcribe"], ["生成字幕"]),
    ("DELETE_RANGE", ["静音", "停顿", "空白", "删掉停顿", "silence"], ["删除静音"]),
    ("SET_VOLUME", ["音量", "声音", "太小", "太大", "volume"], ["调整音量"]),
    ("FADE_IN", ["淡入", "fade in"], ["淡入"]),
    ("FADE_OUT", ["淡出", "fade out"], ["淡出"]),
    ("INSERT_BROLL_OVERLAY", ["b-roll", "broll", "素材", "插入", "覆盖画面", "镜头"], ["插入 B-roll"]),
    ("GENERATE_BROLL", ["生成视频", "生成素材", "画面提示词", "prompt"], ["生成 B-roll"]),
    ("CUT_SEGMENT", ["截取", "裁剪", "剪出", "剪一段", "cut", "trim"], ["截取片段"]),
    ("EXPORT_VIDEO", ["导出", "输出视频", "生成文件", "render", "export"], ["导出视频"]),
]


QUESTION_KEYWORDS = ["怎么", "如何", "为什么", "能不能", "是否", "介绍", "解释", "分析一下", "?", "？"]


def recognize_intent(request: str) -> dict[str, Any]:
    text = request.lower()
    matched_keywords: list[str] = []
    operation_types: list[str] = []
    labels: list[str] = []

    for operation_type, keywords, operation_labels in INTENT_KEYWORDS:
        matched = [keyword for keyword in keywords if keyword.lower() in text or keyword in request]
        if not matched:
            continue
        matched_keywords.extend(matched)
        if operation_type not in operation_types:
            operation_types.append(operation_type)
        for label in operation_labels:
            if label not in labels:
                labels.append(label)

    specialist_agents: list[str] = []
    for operation_type in operation_types:
        agent = INTENT_AGENT_MAP.get(operation_type)
        if agent and agent not in specialist_agents:
            specialist_agents.append(agent)

    is_question = any(keyword in request or keyword.lower() in text for keyword in QUESTION_KEYWORDS)
    requires_edit_plan = bool(operation_types) and not (is_question and not specialist_agents)
    category = "edit" if requires_edit_plan else "respond"
    if not operation_types and is_question:
        category = "question"
    elif not operation_types:
        category = "unknown"

    confidence = 0.25
    if operation_types:
        confidence = min(0.95, 0.55 + len(operation_types) * 0.1)
    elif is_question:
        confidence = 0.65

    return {
        "category": category,
        "operation_types": operation_types,
        "operation_labels": labels,
        "specialist_agents": specialist_agents,
        "requires_edit_plan": requires_edit_plan,
        "confidence": confidence,
        "matched_keywords": matched_keywords,
        "reason": "、".join(labels) if labels else "未识别到明确剪辑操作",
    }
