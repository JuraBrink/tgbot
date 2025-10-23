# bot/db/middleware.py
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession
from base import session_factory
from users_repo import UsersRepo

class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Dict[str, Any], Any], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        Session = session_factory()
        async with Session() as session:  # type is AsyncSession
            data["db_session"] = session
            data["users_repo"] = UsersRepo(session)
            return await handler(event, data)
