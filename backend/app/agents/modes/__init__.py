from app.agents.modes.interview import INTERVIEW_MODE
from app.agents.modes.schema import AgentMode
from app.agents.modes.talking_head import TALKING_HEAD_MODE
from app.agents.modes.vlog import VLOG_MODE

AGENT_MODES: dict[str, AgentMode] = {
    mode.video_type: mode
    for mode in (VLOG_MODE, TALKING_HEAD_MODE, INTERVIEW_MODE)
}


def get_agent_mode(video_type: str) -> AgentMode:
    return AGENT_MODES.get(str(video_type).upper(), TALKING_HEAD_MODE)


__all__ = ["AGENT_MODES", "AgentMode", "get_agent_mode"]
