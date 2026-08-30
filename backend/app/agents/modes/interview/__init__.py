from app.agents.modes.interview.dialogue_agent import create_dialogue_edit_agent
from app.agents.modes.interview.director import create_interview_director_agent
from app.agents.modes.schema import AgentMode, DelegateSpec
from app.agents.specialists import create_audio_agent, create_subtitle_agent, create_video_agent

INTERVIEW_MODE = AgentMode(
    video_type="INTERVIEW",
    label="访谈",
    coordinator_name="interview_director",
    coordinator_factory=create_interview_director_agent,
    delegates=(
        DelegateSpec(
            "delegate_to_dialogue_edit_agent",
            "dialogue_edit_agent",
            "把问题与回答结构、说话人轮次、主题段落和访谈停顿交给 Dialogue Edit Agent。",
            create_dialogue_edit_agent,
        ),
        DelegateSpec(
            "delegate_to_subtitle_agent",
            "subtitle_agent",
            "把说话人字幕、断句、纠错、翻译和时间码任务交给 Subtitle Agent。",
            create_subtitle_agent,
        ),
        DelegateSpec(
            "delegate_to_audio_agent",
            "audio_agent",
            "把多人音量一致性、静音、响度和淡入淡出任务交给 Audio Agent。",
            create_audio_agent,
        ),
        DelegateSpec(
            "delegate_to_video_agent",
            "video_agent",
            "把多机位素材检查、截取、拼接、预览和 FFmpeg 输出交给 Video Agent。",
            create_video_agent,
        ),
    ),
)

__all__ = ["INTERVIEW_MODE"]
