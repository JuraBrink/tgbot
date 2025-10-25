# app/routers/settings.py
from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from datetime import date
from typing import TYPE_CHECKING

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import UserSettings  # <-- используем ORM-модель

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="settings")

# Таймер снятия клавиатуры: (chat_id, message_id) -> asyncio.Task
_tasks: dict[tuple[int, int], asyncio.Task] = {}
# Таймеры ожидания ввода baseline: user_id -> asyncio.Task
_input_timeouts: dict[int, asyncio.Task] = {}


class StartCb(CallbackData, prefix="settings"):
    action: str  # "start"
    mid: int     # message_id управляемого сообщения
    uid: int     # инициатор


class BaselineStates(StatesGroup):
    waiting_for_input = State()


def _kb(message_id: int, user_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="Start",
             callback_data=StartCb(action="start", mid=message_id, uid=user_id).pack())
    return b.as_markup()


async def _expire_after(bot: Bot, chat_id: int, message_id: int):
    """Через 60 секунд снимаем клавиатуру. НИЧЕГО не отправляем."""
    try:
        await asyncio.sleep(60)
        task = _tasks.pop((chat_id, message_id), None)
        if task is None:
            return
        with suppress(TelegramBadRequest):
            await bot.edit_message_reply_markup(chat_id=chat_id,
                                                message_id=message_id,
                                                reply_markup=None)
    except asyncio.CancelledError:
        pass


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot):
    msg = await message.answer("Settings")
    await bot.edit_message_reply_markup(chat_id=msg.chat.id,
                                        message_id=msg.message_id,
                                        reply_markup=_kb(msg.message_id, message.from_user.id))
    task = asyncio.create_task(_expire_after(bot, msg.chat.id, msg.message_id))
    _tasks[(msg.chat.id, msg.message_id)] = task


@router.callback_query(StartCb.filter(F.action == "start"))
async def on_start_click(cb: CallbackQuery, callback_data: StartCb, bot: Bot, state: FSMContext):
    if cb.from_user.id != callback_data.uid:
        await cb.answer("Эта кнопка не для вас", show_alert=True)
        return

    chat_id = cb.message.chat.id
    message_id = cb.message.message_id

    with suppress(TelegramBadRequest):
        await bot.edit_message_reply_markup(chat_id=chat_id,
                                            message_id=message_id,
                                            reply_markup=None)

    task = _tasks.pop((chat_id, message_id), None)
    if task and not task.done():
        task.cancel()

    old = _input_timeouts.pop(cb.from_user.id, None)
    if old and not old.done():
        old.cancel()
    await state.clear()

    await cb.answer()
    await cb.message.answer("Введите начальную дату и начальное время (пример: 25.10.2025, 56:30)")

    await state.set_state(BaselineStates.waiting_for_input)

    async def _input_timeout():
        try:
            await asyncio.sleep(60)
            with suppress(Exception):
                await state.clear()
        except asyncio.CancelledError:
            pass
        finally:
            _input_timeouts.pop(cb.from_user.id, None)

    _input_timeouts[cb.from_user.id] = asyncio.create_task(_input_timeout())


# ===== Парсинг ввода =====
_DATE_RX = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})\b")


def _parse_baseline(text: str) -> tuple[date, int]:
    cleaned = (text or "").strip()

    dm = _DATE_RX.search(cleaned)
    if not dm:
        raise ValueError("Неверный формат даты")
    d, m, y = map(int, dm.groups())
    if y < 100:
        y += 2000
    baseline_date = date(y, m, d)

    tm = re.search(r"(\d{1,3})\s*:\s*(\d{2})", cleaned)  # H+:MM
    if not tm:
        raise ValueError("Неверный формат времени")
    hh, mm = map(int, tm.groups())
    if mm >= 60:
        raise ValueError("Минуты должны быть 00..59")
    baseline_minutes = hh * 60 + mm

    return baseline_date, baseline_minutes


# ===== Сохранение =====
@router.message(BaselineStates.waiting_for_input)
async def handle_baseline_input(
    message: Message,
    state: FSMContext,
    session: "AsyncSession" | None = None,
    **data,
):
    user_id = message.from_user.id

    t = _input_timeouts.pop(user_id, None)
    if t and not t.done():
        t.cancel()

    # Достаём сессию из data на случай иного ключа
    session = session or data.get("session") or data.get("db") or data.get("sa")
    if session is None:
        await message.answer("Внутренняя ошибка: нет соединения с БД")
        await state.clear()
        return

    try:
        bdate, bmin = _parse_baseline(message.text or "")
    except Exception:
        await message.answer(
            "Неверный формат. Пример: 25.10.2025, 56:30\n"
            "Допустимые разделители даты: '.', '/', '-'"
        )
        async def _retry_timeout():
            try:
                await asyncio.sleep(60)
                with suppress(Exception):
                    await state.clear()
            except asyncio.CancelledError:
                pass
            finally:
                _input_timeouts.pop(user_id, None)
        _input_timeouts[user_id] = asyncio.create_task(_retry_timeout())
        return

    # ORM upsert: get → insert/update
    row = await session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(
            user_id=user_id,
            baseline_date=bdate.isoformat(),
            baseline_worked_min=int(bmin),
            updated_at=UserSettings.now_iso(),
        )
        session.add(row)
    else:
        row.baseline_date = bdate.isoformat()
        row.baseline_worked_min = int(bmin)
        row.updated_at = UserSettings.now_iso()

    await session.commit()

    await message.answer(
        f"Сохранил: дата {bdate.strftime('%d.%m.%Y')}, "
        f"начальное время {bmin // 60:02d}:{bmin % 60:02d}"
    )
    await state.clear()
