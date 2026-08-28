import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, project_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[project_id].append(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        sockets = self.connections.get(project_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets and project_id in self.connections:
            del self.connections[project_id]

    async def broadcast(self, project_id: str, event_type: str, data: dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, "data": data}, default=str)
        dead: list[WebSocket] = []
        for websocket in self.connections.get(project_id, []):
            try:
                await websocket.send_text(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(project_id, websocket)


manager = ConnectionManager()
