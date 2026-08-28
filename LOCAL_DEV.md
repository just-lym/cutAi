# AICut Local Development

This project runs dependency services with Docker and runs backend/frontend locally.

## 1. Start Docker Services

Docker files are also copied to:

```text
D:\MyProgramFiles\docker\app\cutAi
```

From this repository:

```powershell
.\start.ps1
```

Or from the Docker directory:

```powershell
cd D:\MyProgramFiles\docker\app\cutAi
.\start-services.ps1
```

This starts:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

Data stays under:

```text
D:\MyProgramFiles\docker\app\cutAi\data
```

## 2. Start Backend Locally

```powershell
.\start-backend.ps1
```

Backend URL:

```text
http://localhost:8000/api/health
```

The backend writes media files to:

```text
D:\MyProgramFiles\docker\app\cutAi\data\aicut
```

## 3. Start Frontend Locally

```powershell
.\start-frontend.ps1
```

Frontend URL:

```text
http://localhost:5173
```

## FFmpeg Note

PostgreSQL and Redis do not require local installs. Because the backend now runs locally, media probing needs local `ffmpeg` and `ffprobe` on `PATH`. The app can still start without FFmpeg, but video/audio uploads will show metadata processing errors until FFmpeg is available.
