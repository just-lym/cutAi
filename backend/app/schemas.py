from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import VideoType


class ProjectCreate(BaseModel):
    name: str
    video_type: VideoType = VideoType.TALKING_HEAD
    width: int = 1920
    height: int = 1080
    frame_rate: float = 30.0


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: str
    name: str
    video_type: VideoType
    width: int
    height: int
    frame_rate: float
    duration_ms: int
    current_timeline_version: int
    status: str


class ProjectUpdate(BaseModel):
    video_type: VideoType


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
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")


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


class AgentSelection(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    asset_id: UUID | None = None
    clip_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> "AgentSelection":
        if self.end_ms <= self.start_ms:
            raise ValueError("selection.end_ms must be greater than selection.start_ms")
        return self


class AgentMessage(BaseModel):
    content: str
    selection: AgentSelection | None = None


class ApprovalRequest(BaseModel):
    approved_indices: list[int] | None = None
    rejected_indices: list[int] | None = None
    feedback_note: str | None = None
    render_after_apply: bool = True


class ApprovalResponse(BaseModel):
    ok: bool
    applied_count: int
    rejected_count: int
    plan_status: str
    timeline_version: int | None = None
    render_job_id: UUID | None = None
    render_status: str | None = None


class AgentHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: str
    content: str
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime


class SubtitleUpdate(BaseModel):
    text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    style: dict[str, Any] | None = None


class BrollSearchRequest(BaseModel):
    query: str
    limit: int = 6


class BrollSelectRequest(BaseModel):
    asset_id: UUID
    position_ms: int
    duration_ms: int = 4000


class RenderRequest(BaseModel):
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    output_path: str | None = None


class RenderPathRequest(BaseModel):
    default_name: str = "final.mp4"


class RenderPathResponse(BaseModel):
    path: str | None = None


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
