# AICut Local Development

This project runs backend/frontend locally. Docker is only used for dependency services if you want local PostgreSQL and Redis without manual installation.

## 1. Config File

Backend config lives here:

```text
backend\config.local.toml
```

Edit that file directly. Project settings are not read from `.env`. `backend\config.local.toml` is local-only and ignored by Git; commit changes to `backend\config.example.toml` when changing defaults.

## 2. Start Docker Services

```powershell
.\start.ps1
```

This starts:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

Data stays under:

```text
D:\MyProgramFiles\docker\app\cutAi\data
```

## 3. Start Backend Locally

```powershell
.\start-backend.ps1
```

Backend URL:

```text
http://localhost:8000/api/health
```

## 4. Start Frontend Locally

```powershell
.\start-frontend.ps1
```

Frontend URL:

```text
http://localhost:5173
```

## FFmpeg

FFmpeg is configured in `backend\config.local.toml`:

```toml
[ffmpeg]
bin_dir = "D:/software/ffmpeg/bin"
```

With this setting, the backend can use `D:\software\ffmpeg\bin\ffmpeg.exe` and `ffprobe.exe` without requiring system `Path` changes.

