import os
import asyncio
from aiogram import Bot, Dispatcher
from app.handlers import router as other_router
from dotenv import load_dotenv  # <-- импортируем
from app.commands import setup_commands, delete_commands
from app.routers.user import router as user_router
from db.middleware import DbSessionMiddleware
from db.base import init_db, create_tables

load_dotenv()  # загружаем переменные из .env

TOKEN = os.getenv("BOT_TOKEN", "")
bot = Bot(token = TOKEN) # @testmyaiogram_bot
dp = Dispatcher()


async def on_startup(dispatcher: Dispatcher):
    # Регистрируем команды (можно оставить try/except вокруг scope=chat как обсуждали раньше)
    #await delete_commands(bot)
    await setup_commands(bot)


async def main():

    await init_db()
    await create_tables()

    dp.update.middleware(DbSessionMiddleware())  # обязательно до старта поллинга
    
    dp.startup.register(on_startup)

    dp.include_router(user_router)
    dp.include_router(other_router)

    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt: 
        print('Bot stopped')