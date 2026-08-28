from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str
    width: int = 1920
    height: int = 1080
    frame_rate: float = 30.0


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: str
    name: str
    width: int
    height: int
    frame_rate: float
    duration_ms: int
    current_timeline_version: int
    status: str


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    type: str
    source_type: str
    original_name: str
    file_path: str
    proxy_path: str | None = None
    mime_type: str
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    checksum: str | None = None
    processing_status: str
    processing_step: str | None = None
    processing_error: str | None = None
    metadata_: dict[str, Any] | None = None


class TimelineRead(BaseModel):
    id: UUID
    project_id: UUID
    version: int
    parent_version_id: UUID | None = None
    timeline_json: dict[str, Any]
    change_summary: str | None = None
    created_by: str


class TimelineCommit(BaseModel):
    operations: list[dict[str, Any]] = Field(default_factory=list)
    change_summary: str = "Manual edit"


class AgentMessage(BaseModel):
    content: str


class AgentRunResponse(BaseModel):
    session_id: UUID
    reply: str
    edit_plan: dict[str, Any] | None = None
    awaiting_user: bool
    total_cost: float = 0.0


class AgentSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    user_id: str
    langgraph_thread_id: str | None = None
    status: str
    total_tokens_used: int
    total_cost_yuan: float


class ApprovalRequest(BaseModel):
    approved_indices: list[int] | None = None
    rejected_indices: list[int] | None = None


class ApprovalResponse(BaseModel):
    ok: bool
    applied_count: int
    rejected_count: int
    plan_status: str
    timeline_version: int | None = None


class SubtitleUpdate(BaseModel):
    text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None


class BrollSearchRequest(BaseModel):
    query: str
    limit: int = 6


class BrollSelectRequest(BaseModel):
    asset_id: UUID
    position_ms: int
    duration_ms: int = 4000


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    asset_id: UUID | None = None
    type: str
    status: str
    progress: float
    step: str | None = None
    error: str | None = None
    output: dict[str, Any] | None = None
