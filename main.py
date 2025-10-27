import os
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from app.handlers import router as other_router
from app.routers.user import router as user_router
from app.routers.settings import router as settings_router
from app.commands import setup_commands
from app.middlewares.auth import AuthMiddleware
from db.middleware import DbSessionMiddleware
from db.base import init_db, create_tables, session_factory
from db.migrate import ensure_user_settings_columns
from aiogram.client.default import DefaultBotProperties

from app.scheduler import setup_scheduler, schedule_user_reminder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import UserSettings

load_dotenv()

async def on_startup(bot: Bot):
    await setup_commands(bot)
    # Инициализируем планировщик
    setup_scheduler(bot)
    # Поднимем все напоминания из БД
    Session = session_factory()
    async with Session() as session:
        res = await session.execute(select(UserSettings))
        for us in res.scalars():
            if us.reminder_minutes and us.reminder_minutes > 0:
                schedule_user_reminder(us.user_id, us.reminder_minutes, us.timezone)

async def main():
    await init_db(os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///./bot.sqlite3'))
    await create_tables()
    await ensure_user_settings_columns()

    bot = Bot(token=os.getenv('BOT_TOKEN'), default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher(storage=MemoryStorage())

    # Мидлвари
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.update.middleware(AuthMiddleware())

    dp.startup.register(on_startup)

    # Роутеры
    dp.include_router(user_router)
    dp.include_router(settings_router)
    dp.include_router(other_router)

    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Bot stopped')
