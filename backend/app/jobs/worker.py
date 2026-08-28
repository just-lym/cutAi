from arq.connections import RedisSettings

from app.config import settings


async def task_process_asset(ctx, asset_id: str, project_id: str) -> dict:
    return {"asset_id": asset_id, "project_id": project_id, "status": "handled-by-upload-mvp"}


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [task_process_asset]
    max_jobs = max(1, settings.gpu_render_concurrency * 4)
    job_timeout = 3600
