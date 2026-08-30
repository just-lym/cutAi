from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DelegateSpec:
    tool_name: str
    agent_name: str
    description: str
    factory: Callable[[Any], Any]


@dataclass(frozen=True)
class AgentMode:
    video_type: str
    label: str
    coordinator_name: str
    coordinator_factory: Callable[[list[Any]], Any]
    delegates: tuple[DelegateSpec, ...]

    @property
    def team(self) -> tuple[str, ...]:
        return (self.coordinator_name, *(delegate.agent_name for delegate in self.delegates), "review")
