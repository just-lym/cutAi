from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMessageRecord, AgentSession, AgentSessionStatus


async def get_or_create_agent_session(db: AsyncSession, project_id: UUID) -> AgentSession:
    result = await db.execute(
        select(AgentSession)
        .where(
            AgentSession.project_id == project_id,
            AgentSession.status == AgentSessionStatus.ACTIVE,
        )
        .order_by(AgentSession.updated_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        session = AgentSession(project_id=project_id)
        db.add(session)
        await db.flush()
    return session


async def load_agent_history(
    db: AsyncSession,
    session_id: UUID,
    limit: int = 30,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AgentMessageRecord)
        .where(AgentMessageRecord.session_id == session_id)
        .order_by(AgentMessageRecord.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    records = list(reversed(list(result.scalars())))
    return [
        {
            "role": record.role,
            "content": record.content,
            "metadata": record.metadata_ or {},
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
        for record in records
    ]


def record_agent_message(
    db: AsyncSession,
    session: AgentSession,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> AgentMessageRecord:
    record = AgentMessageRecord(
        session_id=session.id,
        project_id=session.project_id,
        role=role,
        content=content,
        metadata_=metadata or {},
    )
    db.add(record)
    return record
