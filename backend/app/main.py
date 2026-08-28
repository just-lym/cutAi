from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, assets, broll, projects, render, subtitles, timelines, usage
from app.config import settings
from app.database import init_db
from app.ws.events import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.projects_root.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(title="AICut", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(assets.router, prefix="/api", tags=["assets"])
app.include_router(timelines.router, prefix="/api", tags=["timelines"])
app.include_router(agents.router, prefix="/api", tags=["agents"])
app.include_router(subtitles.router, prefix="/api", tags=["subtitles"])
app.include_router(broll.router, prefix="/api", tags=["broll"])
app.include_router(render.router, prefix="/api", tags=["render"])
app.include_router(usage.router, prefix="/api", tags=["usage"])


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/projects/{project_id}")
async def project_events(websocket: WebSocket, project_id: str) -> None:
    await manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)
