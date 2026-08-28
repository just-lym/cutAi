from pathlib import Path
from typing import Any
import tomllib

from pydantic import BaseModel


BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG_PATH = BACKEND_ROOT / "config.local.toml"
EXAMPLE_CONFIG_PATH = BACKEND_ROOT / "config.example.toml"


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://aicut:aicut@localhost:5432/aicut"


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"


class StorageConfig(BaseModel):
    data_root: Path = Path("D:/MyProgramFiles/docker/app/cutAi/data/aicut")


class CloudConfig(BaseModel):
    dashscope_api_key: str = ""
    dashscope_workspace_id: str = ""
    video_gen_provider: str = "dashscope"
    runway_api_key: str = ""
    pika_api_key: str = ""
    kling_api_key: str = ""


class BudgetConfig(BaseModel):
    monthly_budget_yuan: float = 100.0
    daily_budget_yuan: float = 10.0


class FFmpegConfig(BaseModel):
    bin_dir: Path = Path("D:/software/ffmpeg/bin")
    hwaccel: str = ""
    gpu_render_concurrency: int = 1

    @property
    def ffmpeg_path(self) -> Path:
        return self.bin_dir / "ffmpeg.exe"

    @property
    def ffprobe_path(self) -> Path:
        return self.bin_dir / "ffprobe.exe"


class Settings(BaseModel):
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    storage: StorageConfig = StorageConfig()
    cloud: CloudConfig = CloudConfig()
    budget: BudgetConfig = BudgetConfig()
    ffmpeg: FFmpegConfig = FFmpegConfig()

    @property
    def database_url(self) -> str:
        return self.database.url

    @property
    def redis_url(self) -> str:
        return self.redis.url

    @property
    def data_root(self) -> Path:
        return self.storage.data_root

    @property
    def projects_root(self) -> Path:
        return self.storage.data_root / "projects"

    @property
    def monthly_budget_yuan(self) -> float:
        return self.budget.monthly_budget_yuan

    @property
    def daily_budget_yuan(self) -> float:
        return self.budget.daily_budget_yuan

    @property
    def gpu_render_concurrency(self) -> int:
        return self.ffmpeg.gpu_render_concurrency


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_settings() -> Settings:
    config_path = LOCAL_CONFIG_PATH if LOCAL_CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    return Settings.model_validate(_load_toml(config_path))


settings = load_settings()
