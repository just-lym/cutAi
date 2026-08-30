from app.agents.modes.schema import AgentMode, DelegateSpec
from app.agents.modes.vlog.director import create_vlog_director_agent
from app.agents.modes.vlog.pacing_agent import create_vlog_pacing_agent
from app.agents.specialists import (
    create_audio_agent,
    create_broll_agent,
    create_subtitle_agent,
    create_video_agent,
)

VLOG_MODE = AgentMode(
    video_type="VLOG",
    label="Vlog",
    coordinator_name="vlog_director",
    coordinator_factory=create_vlog_director_agent,
    delegates=(
        DelegateSpec(
            "delegate_to_vlog_pacing_agent",
            "vlog_pacing_agent",
            "把 Vlog 的叙事节奏、镜头密度、段落组织和粗剪任务交给 Vlog Pacing Agent。",
            create_vlog_pacing_agent,
        ),
        DelegateSpec(
            "delegate_to_broll_agent",
            "broll_agent",
            "把补充画面、覆盖素材选择和插入位置判断交给 B-roll Agent。",
            create_broll_agent,
        ),
        DelegateSpec(
            "delegate_to_audio_agent",
            "audio_agent",
            "把环境声、音乐衔接、静音、响度和淡入淡出任务交给 Audio Agent。",
            create_audio_agent,
        ),
        DelegateSpec(
            "delegate_to_subtitle_agent",
            "subtitle_agent",
            "把字幕读取、生成、纠错、翻译和时间码检查交给 Subtitle Agent。",
            create_subtitle_agent,
        ),
        DelegateSpec(
            "delegate_to_video_agent",
            "video_agent",
            "把视频截取、画幅转换、拼接、预览和 FFmpeg 输出交给 Video Agent。",
            create_video_agent,
        ),
    ),
)

__all__ = ["VLOG_MODE"]
