from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.api import projects as projects_api
from app.config import settings


class FakeExecuteResult:
    def __init__(self, *, items: list[Any] | None = None, rowcount: int = 1) -> None:
        self.items = items or []
        self.rowcount = rowcount

    def scalars(self) -> list[Any]:
        return self.items


class FakeSession:
    def __init__(self, project_id: Any, job_ids: list[Any]) -> None:
        self.project_id = project_id
        self.job_ids = job_ids
        self.deleted_tables: list[str] = []
        self.committed = False
        self.rolled_back = False

    async def get(self, model: Any, object_id: Any) -> Any:
        if model is projects_api.Project and object_id == self.project_id:
            return SimpleNamespace(id=object_id)
        return None

    async def execute(self, statement: Any) -> FakeExecuteResult:
        if getattr(statement, "is_select", False):
            return FakeExecuteResult(items=self.job_ids)
        self.deleted_tables.append(statement.table.name)
        return FakeExecuteResult()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_delete_project_removes_records_and_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job_ids = [uuid4(), uuid4()]
    data_root = tmp_path / "data"
    project_dir = data_root / "projects" / str(project_id)
    project_dir.mkdir(parents=True)
    (project_dir / "originals").mkdir()
    (project_dir / "originals" / "clip.mp4").write_bytes(b"video")
    monkeypatch.setattr(settings.storage, "data_root", data_root)

    cancelled_jobs: list[str] = []
    monkeypatch.setattr(projects_api, "cancel_media_job", cancelled_jobs.append)
    db = FakeSession(project_id, job_ids)

    result = await projects_api.delete_project(project_id, db)  # type: ignore[arg-type]

    assert result["ok"] is True
    assert result["storage_deleted"] is True
    assert not project_dir.exists()
    assert cancelled_jobs == [str(job_id) for job_id in job_ids]
    assert db.committed is True
    assert db.rolled_back is False
    assert db.deleted_tables == [
        "cloud_api_usage",
        "agent_sessions",
        "edit_plans",
        "jobs",
        "timeline_versions",
        "assets",
        "projects",
    ]
