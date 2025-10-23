
from __future__ import annotations
from typing import Iterable
from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
)
from aiogram.exceptions import TelegramBadRequest
import logging

def base_commands() -> list[BotCommand]:
    return [
        BotCommand(command="mark", description="Mark work time or day of"),
        BotCommand(command="report",  description="Show timesheet"),
        BotCommand(command="settings", description="Bot settings"),
        BotCommand(command="user", description="Add new user to bot"),
    ]

async def setup_commands(bot: Bot) -> None:
 
    #await bot.delete_my_commands(scope=BotCommandScopeDefault())
    await bot.set_my_commands(base_commands(), scope=BotCommandScopeDefault())

async def delete_commands(bot: Bot) -> None:
    # 1) Сносим всё лишнее, чтобы не «подмешивалось»
    for scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ):
        try:
            # Без языка
            await bot.delete_my_commands(scope=scope)
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=862696832))
            # Языковые варианты, если раньше выставлялись
            for lang in ("ru", "en"):
                await bot.delete_my_commands(scope=scope, language_code=lang)
                await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=862696832), language_code=lang)
        except TelegramBadRequest:
            pass  # если ничего не было — ок

