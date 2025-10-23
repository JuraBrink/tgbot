# bot/db/base.py
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None

async def init_db(db_url: str = "sqlite+aiosqlite:///./bot.sqlite3") -> None:
    global engine, SessionLocal
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def create_tables() -> None:
    from .models import User  # noqa
    async with engine.begin() as conn:  # type: ignore[arg-type]
        await conn.run_sync(Base.metadata.create_all)

# Утилита-синглтон для выдачи сессии
def session_factory() -> async_sessionmaker[AsyncSession]:
    assert SessionLocal is not None, "DB is not initialized. Call init_db() first."
    return SessionLocal
