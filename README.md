# AICut

AI multi-agent video editing platform MVP generated from the project prompt.

## What Works

- Backend and frontend run locally for easier development.
- Docker can still run dependency services: PostgreSQL and Redis.
- Project creation and timeline initialization.
- Asset upload into the configured data directory.
- FFprobe metadata extraction for video/audio uploads.
- SRT import into the script/timeline view.
- Deterministic MVP Agent that creates approval-ready edit plans.
- Partial approval/rejection and timeline version creation.
- WebSocket refresh events for timeline and job updates.

## Local Config File

Backend configuration is stored in:

```text
backend\config.local.toml
```

Edit this file directly. The backend does not require `.env` or system environment variables for project settings. `backend\config.local.toml` is local-only and ignored by Git; commit changes to `backend\config.example.toml` when changing defaults.

Default config:

```toml
[database]
url = "postgresql+asyncpg://aicut:aicut@localhost:5432/aicut"

[redis]
url = "redis://localhost:6379/0"

[storage]
data_root = "D:/MyProgramFiles/docker/app/cutAi/data/aicut"

[cloud]
dashscope_api_key = ""
dashscope_workspace_id = ""
video_gen_provider = "dashscope"
runway_api_key = ""
pika_api_key = ""
kling_api_key = ""

[budget]
monthly_budget_yuan = 100.0
daily_budget_yuan = 10.0

[ffmpeg]
bin_dir = "D:/software/ffmpeg/bin"
hwaccel = ""
gpu_render_concurrency = 1
```

## Data Path

The default media/data path is:

```text
D:\MyProgramFiles\docker\app\cutAi\data\aicut
```

## Start Dependency Services With Docker

```powershell
.\start.ps1
```

This starts only PostgreSQL and Redis with Docker.

## Start Backend Locally

```powershell
.\start-backend.ps1
```

Backend URL:

```text
http://localhost:8000/api/health
```

## Start Frontend Locally

```powershell
.\start-frontend.ps1
```

Frontend URL:

```text
http://localhost:5173
```

## Stop Docker Services

```powershell
.\stop.ps1
```

## FFmpeg

FFmpeg is configured through `backend\config.local.toml`:

```toml
[ffmpeg]
bin_dir = "D:/software/ffmpeg/bin"
```

The backend first tries that directory, then falls back to `ffmpeg`/`ffprobe` on `PATH`.

## Notes

Cloud ASR, B-roll generation, Chroma semantic search, and real render export are scaffolded as integration points. The current goal is a stable local development MVP before wiring paid external APIs.

