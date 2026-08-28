from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://aicut:aicut@localhost:5432/aicut"
    redis_url: str = "redis://localhost:6379/0"

    dashscope_api_key: str = ""
    dashscope_workspace_id: str = ""

    video_gen_provider: str = "dashscope"
    runway_api_key: str = ""
    pika_api_key: str = ""
    kling_api_key: str = ""

    monthly_budget_yuan: float = 100.0
    daily_budget_yuan: float = 10.0

    data_root: Path = Path("/data/aicut")
    ffmpeg_hwaccel: str = ""
    gpu_render_concurrency: int = 1

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def projects_root(self) -> Path:
        return self.data_root / "projects"


settings = Settings()
