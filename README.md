# AICut

AI multi-agent video editing platform MVP generated from the project prompt.

## What Works

- Docker runs only dependency services: PostgreSQL and Redis.
- Backend and frontend run locally for easier development.
- Project creation and timeline initialization.
- Asset upload into the configured Docker data directory.
- FFprobe metadata extraction for video/audio uploads.
- SRT import into the script/timeline view.
- Deterministic MVP Agent that creates approval-ready edit plans.
- Partial approval/rejection and timeline version creation.
- WebSocket refresh events for timeline and job updates.

## Required Docker Path

Docker service data is strictly stored under:

```text
D:\MyProgramFiles\docker\app\cutAi
```

Data binds are fixed in `docker-compose.yml`:

```text
D:\MyProgramFiles\docker\app\cutAi\data\postgres
D:\MyProgramFiles\docker\app\cutAi\data\redis
D:\MyProgramFiles\docker\app\cutAi\data\aicut
```

The backend local `.env` uses the same media data path:

```text
DATA_ROOT=D:/MyProgramFiles/docker/app/cutAi/data/aicut
```

## Start Dependency Services

```powershell
.\start.ps1
```

This starts only PostgreSQL and Redis with Docker.

## Start Backend Locally

```powershell
.\start-backend.ps1
```

The script creates `backend\.env` from `backend\.env.example`, creates a virtual environment if needed, installs the backend package, and starts FastAPI at:

```text
http://localhost:8000/api/health
```

## Start Frontend Locally

```powershell
.\start-frontend.ps1
```

Open:

```text
http://localhost:5173
```

## Stop

```powershell
.\stop.ps1
```

## Notes

Because the backend now runs locally, real video/audio probing needs a local `ffmpeg`/`ffprobe` executable on `PATH`. If you do not install FFmpeg locally, the app still starts, but video/audio metadata processing will fail for uploaded media. A later worker-container mode can move FFmpeg processing back into Docker while keeping the web backend local.

Cloud ASR, B-roll generation, Chroma semantic search, and real render export are scaffolded as integration points. The current goal is a stable local development MVP that uses Docker only for dependency services before wiring paid external APIs.
