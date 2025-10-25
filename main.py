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
from db.base import init_db, create_tables
from aiogram.client.default import DefaultBotProperties

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "")
if not TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher(storage=MemoryStorage())

async def on_startup():
    # Создаём таблицы, включаем WAL и FK
    await init_db("sqlite+aiosqlite:///./bot.sqlite3")
    await create_tables()
    await setup_commands(bot)

async def main():
    # DB middleware должен идти раньше AuthMiddleware
    dp.update.middleware(DbSessionMiddleware())
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
