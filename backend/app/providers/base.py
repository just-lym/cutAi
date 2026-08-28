from pathlib import Path
from typing import Protocol


class VideoGenProvider(Protocol):
    async def generate(self, prompt: str, **kwargs: dict) -> str: ...

    async def poll_status(self, task_id: str) -> dict: ...

    async def download_result(self, task_id: str, dest: Path) -> Path: ...

    @property
    def cost_per_generation(self) -> float: ...


class NotConfiguredVideoProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    async def generate(self, prompt: str, **kwargs: dict) -> str:
        raise RuntimeError(f"Video provider {self.name} is not configured in the MVP.")

    async def poll_status(self, task_id: str) -> dict:
        return {"status": "FAILED", "error": "provider not configured"}

    async def download_result(self, task_id: str, dest: Path) -> Path:
        raise RuntimeError("No generated video is available")

    @property
    def cost_per_generation(self) -> float:
        return 0.0


def get_provider(name: str = "dashscope") -> VideoGenProvider:
    return NotConfiguredVideoProvider(name)
