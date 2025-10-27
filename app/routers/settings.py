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

from sqlalchemy import select

from db.models import UserSettings  # ORM-модель

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


# ===== Утилиты формирования подписи кнопки =====

async def _get_start_label(session: "AsyncSession", tg_id: int) -> str:
    """
    Собирает подпись для кнопки Start на основе user_settings для tg_id.
    Если записи нет — возвращает дефолт "Start 00.00.0000, 00:00".
    """
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == tg_id)
    )
    row: UserSettings | None = result.scalar_one_or_none()
    if not row:
        return "Start 00.00.0000, 00:00"

    # row.baseline_date: 'YYYY-MM-DD'
    try:
        y, m, d = map(int, row.baseline_date.split("-"))
        ddmmyyyy = f"{d:02d}.{m:02d}.{y:04d}"
    except Exception:
        ddmmyyyy = "00.00.0000"

    mins = int(row.baseline_worked_min or 0)
    return f"Start {ddmmyyyy}, {mins // 60:02d}:{mins % 60:02d}"


def _kb_with_label(message_id: int, user_id: int, start_label: str):
    b = InlineKeyboardBuilder()
    b.button(
        text=start_label,
        callback_data=StartCb(action="start", mid=message_id, uid=user_id).pack(),
    )
    return b.as_markup()


async def _expire_after(bot: Bot, chat_id: int, message_id: int):
    """Через 60 секунд снимаем клавиатуру. НИЧЕГО не отправляем."""
    try:
        await asyncio.sleep(60)
        task = _tasks.pop((chat_id, message_id), None)
        if task is None:
            return
        with suppress(TelegramBadRequest):
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
    except asyncio.CancelledError:
        pass


# ===== /settings =====
@router.message(Command("settings"))
async def cmd_settings(
    message: Message,
    bot: Bot,
    session: "AsyncSession" | None = None,
    **data,
):
    """
    Рендер меню настроек с динамической подписью кнопки Start.
    Берём сессию из middleware: data["db_session"].
    """
    # Достаём сессию из data на случай другого ключа
    session = data.get("db_session")

    msg = await message.answer("Settings")

    # Собираем текст для Start
    start_label = "Start 00.00.0000, 00:00"
    if session is not None:
        try:
            start_label = await _get_start_label(session, message.from_user.id)
        except Exception:
            # В случае ошибки — дефолт
            pass

    # Навешиваем клавиатуру
    await bot.edit_message_reply_markup(
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        reply_markup=_kb_with_label(msg.message_id, message.from_user.id, start_label),
    )

    # Запускаем авто-снятие клавиатуры
    task = asyncio.create_task(_expire_after(bot, msg.chat.id, msg.message_id))
    _tasks[(msg.chat.id, msg.message_id)] = task


# ===== Нажатие на Start =====
@router.callback_query(StartCb.filter(F.action == "start"))
async def on_start_click(
    cb: CallbackQuery,
    callback_data: StartCb,
    bot: Bot,
    state: FSMContext,
):
    if cb.from_user.id != callback_data.uid:
        await cb.answer("Эта кнопка не для вас", show_alert=True)
        return

    chat_id = cb.message.chat.id
    message_id = cb.message.message_id

    # Сохраним id сообщения настроек, чтобы обновить клавиатуру после сохранения
    await state.update_data(settings_msg_id=message_id, settings_chat_id=chat_id)

    with suppress(TelegramBadRequest):
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )

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

    dd = int(dm.group(1))
    mm = int(dm.group(2))
    yy = int(dm.group(3))
    if yy < 100:
        yy += 2000

    # время — всё, что после запятой
    parts = cleaned.split(",", 1)
    if len(parts) == 1:
        raise ValueError("Не нашли время 'HH:MM' после запятой")

    tm = parts[1].strip()
    if ":" not in tm:
        raise ValueError("Ожидали формат 'HH:MM'")

    hh_s, mm_s = tm.split(":", 1)
    hh = int(hh_s)
    mn = int(mm_s)

    if not (0 <= mn < 60):
        raise ValueError("Минуты должны быть 0..59")

    # дата как date, минуты как int
    return date(yy, mm, dd), hh * 60 + mn


# ===== Сохранение =====
@router.message(BaselineStates.waiting_for_input)
async def handle_baseline_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: "AsyncSession" | None = None,
    **data,
):
    user_id = message.from_user.id

    t = _input_timeouts.pop(user_id, None)
    if t and not t.done():
        t.cancel()

    # Достаём сессию из data на случай иного ключа
    session = session or data.get("db_session") or data.get("session") or data.get("db") or data.get("sa")
    if session is None:
        await message.answer("Внутренняя ошибка: нет соединения с БД")
        await state.clear()
        return

    try:
        bdate, bmin = _parse_baseline(message.text or "")
    except Exception:
        await message.answer(
            "Неверный формат. Пример: 25.10.2025, 56:30\n"
            "Допустимы разделители даты: точка/слэш/дефис. Время строго HH:MM."
        )
        return

    # upsert по ключу user_id = tg_id
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    row: UserSettings | None = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(
            user_id=user_id,
            baseline_date=bdate.isoformat(),            # YYYY-MM-DD
            baseline_worked_min=int(bmin),             # минуты
            updated_at=UserSettings.now_iso(),         # ISO datetime
        )
        session.add(row)
    else:
        row.baseline_date = bdate.isoformat()
        row.baseline_worked_min = int(bmin)
        row.updated_at = UserSettings.now_iso()

    await session.commit()

    # Обновим клавиатуру настроек, если знаем исходное сообщение
    st_data = await state.get_data()
    chat_id = st_data.get("settings_chat_id")
    msg_id = st_data.get("settings_msg_id")
    if chat_id and msg_id:
        try:
            start_label = await _get_start_label(session, user_id)
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=_kb_with_label(msg_id, user_id, start_label),
            )
        except Exception:
            # Если сообщение уже удалили/истёк таймер — просто игнорируем
            pass

    await message.answer(
        f"Сохранил: дата {bdate.strftime('%d.%m.%Y')}, "
        f"начальное время {bmin // 60:02d}:{bmin % 60:02d}"
    )
    await state.clear()
