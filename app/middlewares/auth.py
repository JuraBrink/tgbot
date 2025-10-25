# app/middlewares/auth.py
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware, types
from aiogram import Bot
from db.users_repo import UsersRepo

# ВАЖНО: укажи реальный ID админа (не 86269683200 — это слишком длинный!)
ADMIN_ID = 86269683200

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Dict[str, Any], Any], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        bot: Bot = data["bot"]                           # бот всегда есть в data
        user: types.User | None = data.get("event_from_user")
        chat: types.Chat | None = data.get("event_chat")

        # Если апдейт не от пользователя (например, service update) — пропускаем
        if user is None:
            return await handler(event, data)

        users_repo: UsersRepo | None = data.get("users_repo")
        if users_repo is None:
            return await handler(event, data)

        # Админ — всегда разрешён и апсертим запись
        if user.id == ADMIN_ID:
            await users_repo.upsert_user(tg_id=user.id, username=user.username)
            return await handler(event, data)

        # Проверяем доступ обычного пользователя
        db_user = await users_repo.get_by_tg_id(user.id)
        if db_user is None:
            text = (
               f"Hello {user.full_name}. "
               f"Please send your ID: {user.id} to the administrator."
            )
            # Куда отвечать: в чат апдейта, иначе — в личку пользователю
            target_chat_id = chat.id if chat else user.id
            await bot.send_message(target_chat_id, text)
            return  # прерываем цепочку

        # Всё ок — продолжаем обработку
        return await handler(event, data)

