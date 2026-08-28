from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

sync_db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
sync_engine = create_engine(sync_db_url, echo=False)
SyncSession = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    session = SyncSession()
    try:
        yield session
    finally:
        session.close()


async def init_db() -> None:
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
