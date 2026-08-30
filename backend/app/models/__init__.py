import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    READY = "READY"
    EXPORTING = "EXPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class VideoType(str, enum.Enum):
    VLOG = "VLOG"
    TALKING_HEAD = "TALKING_HEAD"
    INTERVIEW = "INTERVIEW"


class AssetType(str, enum.Enum):
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    IMAGE = "IMAGE"
    SUBTITLE = "SUBTITLE"
    TRANSCRIPT = "TRANSCRIPT"
    OTHER = "OTHER"


class AssetSourceType(str, enum.Enum):
    USER_UPLOAD = "USER_UPLOAD"
    AI_GENERATED = "AI_GENERATED"
    LICENSED_WEB = "LICENSED_WEB"
    SYSTEM_GENERATED = "SYSTEM_GENERATED"


class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentSessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EditPlanStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    WAITING_USER = "WAITING_USER"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class JobType(str, enum.Enum):
    MEDIA_PROBE = "MEDIA_PROBE"
    PROXY_GENERATION = "PROXY_GENERATION"
    THUMBNAIL_GENERATION = "THUMBNAIL_GENERATION"
    AUDIO_EXTRACTION = "AUDIO_EXTRACTION"
    SPEECH_RECOGNITION = "SPEECH_RECOGNITION"
    EMBEDDING_GENERATION = "EMBEDDING_GENERATION"
    PREVIEW_RENDER = "PREVIEW_RENDER"
    FINAL_RENDER = "FINAL_RENDER"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    name: Mapped[str] = mapped_column(String(255))
    video_type: Mapped[str] = mapped_column(
        String(32), default=VideoType.TALKING_HEAD.value, server_default=VideoType.TALKING_HEAD.value
    )
    width: Mapped[int] = mapped_column(Integer, default=1920)
    height: Mapped[int] = mapped_column(Integer, default=1080)
    frame_rate: Mapped[float] = mapped_column(Float, default=30.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    current_timeline_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), default=ProjectStatus.DRAFT, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    assets: Mapped[list["Asset"]] = relationship(back_populates="project")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    type: Mapped[AssetType] = mapped_column(Enum(AssetType))
    source_type: Mapped[AssetSourceType] = mapped_column(
        Enum(AssetSourceType), default=AssetSourceType.USER_UPLOAD
    )
    original_name: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(1024))
    proxy_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.PENDING, index=True
    )
    processing_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="assets")


class TimelineVersion(Base):
    __tablename__ = "timeline_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    timeline_json: Mapped[dict] = mapped_column(JSONB)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(64), default="local")
    langgraph_thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[AgentSessionStatus] = mapped_column(
        Enum(AgentSessionStatus), default=AgentSessionStatus.ACTIVE, index=True
    )
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class EditPlan(Base):
    __tablename__ = "edit_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    base_timeline_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[EditPlanStatus] = mapped_column(
        Enum(EditPlanStatus), default=EditPlanStatus.WAITING_USER, index=True
    )
    operations: Mapped[list] = mapped_column(JSONB)
    conflicts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_by_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    type: Mapped[JobType] = mapped_column(Enum(JobType))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CloudAPIUsage(Base):
    __tablename__ = "cloud_api_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(64))
    service: Mapped[str] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    audio_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def empty_timeline(width: int = 1920, height: int = 1080, frame_rate: float = 30.0) -> dict:
    return {
        "duration_ms": 0,
        "width": width,
        "height": height,
        "frame_rate": frame_rate,
        "tracks": [
            {"id": "video-main", "type": "VIDEO_MAIN", "name": "Main Video", "clips": []},
            {"id": "video-broll", "type": "VIDEO_BROLL", "name": "B-roll", "clips": []},
            {"id": "subtitles", "type": "SUBTITLE", "name": "Subtitles", "cues": []},
            {"id": "audio-original", "type": "AUDIO_ORIGINAL", "name": "Original Audio", "clips": []},
            {"id": "audio-music", "type": "AUDIO_MUSIC", "name": "Music", "clips": []},
        ],
        "volume_changes": [],
    }
