# app/routers/settings.py
from __future__ import annotations

import re
from typing import Optional
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession

from db.settings_repo import SettingsRepo
from db.users_repo import UsersRepo
from db.models import UserSettings
from app.scheduler import (
    schedule_user_reminder,
    remove_user_reminder,
    schedule_kb_expire,
    cancel_kb_expire,
)

router = Router(name="settings")

# ====== Callback data ======
class SettingsCb(CallbackData, prefix="settings"):
    # без msg_id — всегда используем cb.message.message_id
    action: str  # 'start' | 'reminder' | 'timezone' | 'cancel'

# ====== FSM ======
class SettingsFSM(StatesGroup):
    waiting_start = State()
    waiting_reminder = State()
    waiting_timezone = State()

# ====== Helpers ======
_TIME_RE_REMINDER = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")  # 00:00..23:59
# для Start: часы = отработанные часы за месяц, могут быть > 23
_TIME_RE_START = re.compile(r"^(\d{1,3}|\d{1,2}|\d+):([0-5]\d)$")
_DATE_TIME_RE_START = re.compile(
    r"""^\s*
    (?P<d>\d{1,2})[.\-\/](?P<m>\d{1,2})[.\-\/](?P<y>\d{4})
    \s*,\s*
    (?P<h>\d+):(?P<min>[0-5]\d)
    \s*$""",
    re.VERBOSE,
)


def _fmt_hhmm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _start_label(us: Optional[UserSettings]) -> str:
    if not us:
        return "Start 00.00.0000, 00:00"
    # baseline_date: YYYY-MM-DD -> DD.MM.YYYY
    try:
        y, m, d = us.baseline_date.split("-")
        baseline_date_fmt = f"{d}.{m}.{y}"
    except Exception:
        baseline_date_fmt = "00.00.0000"
    try:
        worked_fmt = _fmt_hhmm(us.baseline_worked_min)
    except Exception:
        worked_fmt = "00:00"
    return f"Start {baseline_date_fmt}, {worked_fmt}"


def _reminder_label(us: Optional[UserSettings]) -> str:
    if not us or us.reminder_minutes == 0:
        return "Reminder OFF"
    return f"Reminder {_fmt_hhmm(us.reminder_minutes)}"


def _timezone_label(us: Optional[UserSettings]) -> str:
    if not us or not us.timezone:
        return "Timezone OFF"
    return f"Timezone {us.timezone}"


def _kb(us: Optional[UserSettings]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=_start_label(us), callback_data=SettingsCb(action="start").pack())],
        [
            InlineKeyboardButton(text=_reminder_label(us), callback_data=SettingsCb(action="reminder").pack()),
            InlineKeyboardButton(text=_timezone_label(us), callback_data=SettingsCb(action="timezone").pack()),
        ],
        [InlineKeyboardButton(text="✖️ Cancel", callback_data=SettingsCb(action="cancel").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _ensure_user(session: AsyncSession, tg_id: int, username: str | None) -> None:
    # поддержим логику UsersRepo (создаст/обновит пользователя)
    await UsersRepo(session).upsert_user(tg_id=tg_id, username=username)


async def _send_settings_and_arm_timer(message: Message, repo: SettingsRepo, state: FSMContext) -> None:
    """
    Отправить новое сообщение "Настройки:" с актуальной инлайн-клавиатурой и поставить авто-скрытие на 60 секунд.
    """
    tg_id = message.from_user.id
    us = await repo.get_or_create(tg_id)
    msg = await message.answer("Настройки:", reply_markup=_kb(us))
    # Сохраняем link на сообщение с клавиатурой для /cancel
    await state.update_data(kb_chat=msg.chat.id, kb_msg=msg.message_id)
    # Планируем автоскрытие через 60 сек
    schedule_kb_expire(chat_id=msg.chat.id, message_id=msg.message_id, seconds=60)


async def _hide_kb_now(bot: Bot, chat_id: int, message_id: int) -> None:
    """
    Мгновенно скрыть инлайн-клавиатуру у сообщения + отменить таймер авто-скрытия.
    """
    try:
        cancel_kb_expire(chat_id, message_id)
    except Exception:
        pass
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        # сообщение уже удалено или клавиатура спрятана — игнорируем
        pass


def _today_in_tz(tz_name: str) -> datetime.date:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/Warsaw")
    return datetime.now(tz).date()


# ====== /settings ======
@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext, db_session: AsyncSession):
    tg_id = message.from_user.id
    await _ensure_user(db_session, tg_id, message.from_user.username)
    repo = SettingsRepo(db_session)
    await _send_settings_and_arm_timer(message, repo, state)
    await state.clear()  # убедимся, что вне состояний


# ====== Кнопка Start: спрячь клавиатуру и запроси ввод стартовой точки ======
@router.callback_query(SettingsCb.filter(F.action == "start"))
async def on_click_start(cb: CallbackQuery, state: FSMContext, db_session: AsyncSession, bot: Bot):
    await cb.answer()
    if cb.message:
        await _hide_kb_now(bot, cb.message.chat.id, cb.message.message_id)

    repo = SettingsRepo(db_session)
    # сохраним ids, чтобы /cancel мог скрыть клавиатуру при необходимости
    if cb.message:
        await state.update_data(kb_chat=cb.message.chat.id, kb_msg=cb.message.message_id)
    await state.set_state(SettingsFSM.waiting_start)

    # пример: 25.10.2025, 56:30 — где 56:30 это отработано за месяц (часы>23 допустимы)
    await cb.message.answer(  # type: ignore[union-attr]
        "Пришлите начальную дату и отработанное время за месяц в формате DD.MM.YYYY, HH:MM "
        "(например, 25.10.2025, 56:30). /cancel"
    )


@router.message(SettingsFSM.waiting_start)
async def on_start_input(message: Message, state: FSMContext, db_session: AsyncSession):
    text = (message.text or "").strip()
    m = _DATE_TIME_RE_START.match(text)
    if not m:
        await message.answer(
            "Неверный формат. Пришлите как DD.MM.YYYY, HH:MM (например, 25.10.2025, 56:30). /cancel"
        )
        return

    d = int(m.group("d"))
    mo = int(m.group("m"))
    y = int(m.group("y"))
    hours = int(m.group("h"))
    mins = int(m.group("min"))

    # базовая проверка даты
    try:
        from datetime import date
        provided_date = date(y, mo, d)
    except Exception:
        await message.answer("Некорректная дата. Проверьте день, месяц и год. /cancel")
        return

    # получим таймзону пользователя, чтобы сравнить с локальным «сегодня»
    repo = SettingsRepo(db_session)
    tg_id = message.from_user.id
    us = await repo.get_or_create(tg_id)
    today_tz = _today_in_tz(us.timezone or "Europe/Warsaw")
    if provided_date > today_tz:
        await message.answer(
            f"Дата не может быть в будущем. Сегодня: {today_tz.strftime('%d.%m.%Y')}. /cancel"
        )
        return

    # минуты отработки за месяц (часы могут быть > 23)
    worked_minutes = hours * 60 + mins
    baseline_date_iso = provided_date.isoformat()

    us = await repo.set_baseline(tg_id, baseline_date_iso, worked_minutes)

    await message.answer(
        f"Сохранил начальную точку: {provided_date.strftime('%d.%m.%Y')}, {_fmt_hhmm(worked_minutes)}"
    )

    # Новое сообщение с клавиатурой + таймер 60с
    await _send_settings_and_arm_timer(message, repo, state)
    await state.clear()


# ====== Кнопка Cancel: спрятать клавиатуру и сбросить состояния ======
@router.callback_query(SettingsCb.filter(F.action == "cancel"))
async def on_click_cancel(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cb.answer("Отменено.")
    if cb.message:
        await _hide_kb_now(bot, cb.message.chat.id, cb.message.message_id)
    await state.clear()


# ====== Reminder flow ======
@router.callback_query(SettingsCb.filter(F.action == "reminder"))
async def on_click_reminder(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cb.answer()
    if cb.message:
        # мгновенно спрячем клавиатуру у старого сообщения
        await _hide_kb_now(bot, cb.message.chat.id, cb.message.message_id)

    await state.set_state(SettingsFSM.waiting_reminder)
    # сохраним ids, чтобы /cancel мог скрыть клавиатуру при необходимости
    if cb.message:
        await state.update_data(kb_chat=cb.message.chat.id, kb_msg=cb.message.message_id)

    await cb.message.answer(  # type: ignore[union-attr]
        "Пришлите время напоминания в формате HH:MM (например, 09:30) или off для выключения. /cancel"
    )


@router.message(SettingsFSM.waiting_reminder)
async def on_reminder_input(message: Message, state: FSMContext, db_session: AsyncSession):
    text = (message.text or "").strip().lower()
    repo = SettingsRepo(db_session)
    tg_id = message.from_user.id

    if text in ("off", "00:00"):
        minutes = 0
    else:
        m = _TIME_RE_REMINDER.match(text)
        if not m:
            await message.answer("Неверный формат. Пришлите время как HH:MM (например, 09:30) или off. /cancel")
            return
        minutes = int(m.group(1)) * 60 + int(m.group(2))

    us = await repo.set_reminder_minutes(tg_id, minutes)
    if minutes > 0:
        schedule_user_reminder(tg_id, minutes, us.timezone)
        await message.answer(f"Сохранил время напоминания: {_fmt_hhmm(minutes)}")
    else:
        remove_user_reminder(tg_id)
        await message.answer("Выключил напоминание.")

    # Новое сообщение с клавиатурой + таймер 60с
    await _send_settings_and_arm_timer(message, repo, state)
    await state.clear()


# ====== Timezone flow ======
@router.callback_query(SettingsCb.filter(F.action == "timezone"))
async def on_click_timezone(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cb.answer()
    if cb.message:
        await _hide_kb_now(bot, cb.message.chat.id, cb.message.message_id)

    await state.set_state(SettingsFSM.waiting_timezone)
    if cb.message:
        await state.update_data(kb_chat=cb.message.chat.id, kb_msg=cb.message.message_id)

    await cb.message.answer(  # type: ignore[union-attr]
        "Пришлите таймзону в формате IANA, например: Europe/Warsaw. /cancel"
    )


@router.message(SettingsFSM.waiting_timezone)
async def on_timezone_input(message: Message, state: FSMContext, db_session: AsyncSession):
    tg_id = message.from_user.id
    text = (message.text or "").strip()
    # строгая проверка IANA
    try:
        ZoneInfo(text)
    except Exception:
        await message.answer("Таймзона не распознана. Пример: Europe/Warsaw. /cancel")
        return

    repo = SettingsRepo(db_session)
    us = await repo.set_timezone(tg_id, text)

    # если есть активное напоминание — пересоздадим с новой TZ
    if us.reminder_minutes > 0:
        schedule_user_reminder(tg_id, us.reminder_minutes, us.timezone)

    await message.answer(f"Сохранил таймзону: {text}")
    await _send_settings_and_arm_timer(message, repo, state)
    await state.clear()


# ====== Команда /cancel: спрятать клавиатуру (если есть), сбросить FSM ======
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    kb_chat = data.get("kb_chat")
    kb_msg = data.get("kb_msg")
    if kb_chat and kb_msg:
        try:
            cancel_kb_expire(kb_chat, kb_msg)
        except Exception:
            pass
        try:
            await bot.edit_message_reply_markup(chat_id=kb_chat, message_id=kb_msg, reply_markup=None)
        except Exception:
            pass
    await state.clear()
    await message.answer("Отменено.")
