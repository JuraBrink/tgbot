# app/middlewares/auth.py
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware, types
from db.users_repo import UsersRepo

ADMIN_ID = 86269683299 # "Юра Бринкевич"

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Dict[str, Any], Any], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        # Middleware должен работать и для сообщений, и для колбэков
        tg_obj = None
        if isinstance(event, types.Message):
            tg_obj = event
        elif isinstance(event, types.CallbackQuery):
            tg_obj = event
        else:
            # Другие апдейты пропускаем
            return await handler(event, data)

        user = tg_obj.from_user
        # Админу даём проход всегда
        if user and user.id == ADMIN_ID:
            return await handler(event, data)

        users_repo: UsersRepo = data["users_repo"]
        db_user = await users_repo.get_by_tg_id(user.id)

        if db_user is None:
            text = (
                f"Hello {user.full_name}. "
                f"Please send your ID: {user.id} to the administrator."
            )
            if isinstance(tg_obj, types.Message):
                await tg_obj.answer(text)
            else:
                # CallbackQuery
                await tg_obj.message.answer(text)
            return  # ВАЖНО: останавливаем дальнейшую обработку апдейта

        # Пользователь есть — пропускаем дальше
        return await handler(event, data)
