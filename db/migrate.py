# bot/db/migrate.py
from sqlalchemy import text
from db.base import session_factory

async def ensure_user_settings_columns() -> None:
    """
    Мягкая миграция SQLite: добьём недостающие колонки в user_settings,
    не опираясь на глобальный engine.
    """
    Session = session_factory()
    async with Session() as session:
        async with session.begin():
            # Узнаём существующие колонки
            res = await session.execute(text("PRAGMA table_info(user_settings)"))
            cols = [row[1] for row in res.fetchall()]  # row[1] = имя поля

            if "reminder_minutes" not in cols:
                await session.execute(
                    text("ALTER TABLE user_settings ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 0")
                )

            if "timezone" not in cols:
                await session.execute(
                    text("ALTER TABLE user_settings ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Europe/Warsaw'")
                )
