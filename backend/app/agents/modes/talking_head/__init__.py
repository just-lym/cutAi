from app.agents.modes.schema import AgentMode, DelegateSpec
from app.agents.modes.talking_head.director import create_talking_head_director_agent
from app.agents.modes.talking_head.speech_agent import create_speech_edit_agent
from app.agents.specialists import (
    create_audio_agent,
    create_broll_agent,
    create_subtitle_agent,
    create_video_agent,
)

TALKING_HEAD_MODE = AgentMode(
    video_type="TALKING_HEAD",
    label="口播",
    coordinator_name="talking_head_director",
    coordinator_factory=create_talking_head_director_agent,
    delegates=(
        DelegateSpec(
            "delegate_to_speech_edit_agent",
            "speech_edit_agent",
            "把口播语义精剪、重说、填充词、句间停顿和开头结尾清理交给 Speech Edit Agent。",
            create_speech_edit_agent,
        ),
        DelegateSpec(
            "delegate_to_subtitle_agent",
            "subtitle_agent",
            "把口播字幕、断句、纠错、双语和时间码任务交给 Subtitle Agent。",
            create_subtitle_agent,
        ),
        DelegateSpec(
            "delegate_to_audio_agent",
            "audio_agent",
            "把人声响度、静音、降噪前置分析和淡入淡出任务交给 Audio Agent。",
            create_audio_agent,
        ),
        DelegateSpec(
            "delegate_to_broll_agent",
            "broll_agent",
            "把解释性 B-roll 的素材选择、覆盖位置和预览任务交给 B-roll Agent。",
            create_broll_agent,
        ),
        DelegateSpec(
            "delegate_to_video_agent",
            "video_agent",
            "把画幅、截取、硬字幕预览和 FFmpeg 输出任务交给 Video Agent。",
            create_video_agent,
        ),
    ),
)

__all__ = ["TALKING_HEAD_MODE"]
