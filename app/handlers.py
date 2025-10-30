from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Tuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.kb import build_work_kb
from app.parse import parse_input, fmt_hhmm, ParsedDayOff
from db.work_repo import WorkRepo
from db.settings_repo import SettingsRepo
from db.middleware import session_factory
from app.scheduler import schedule_kb_expire, cancel_kb_expire

router = Router(name="main_router")

PROMPT_TEXT = "Укажите время работы:"
HELP_TEXT = (
    "Укажите время работы:\n"
    "вида: \"Дата\" \"Начало\"-\"Окончание\"(-\"Обед\")\n"
    "где \"Дата\" DD/MM/YYYY вида: 3.7.25 или 03-07-2025\n"
    "время HH:MM вида: 7, 07, 7:5, 07:05"
)

# Храним последний показанный промпт пользователя: user_id -> (chat_id, message_id)
LAST_PROMPT: Dict[int, Tuple[int, int]] = {}

async def _send_prompt(message: Message, session) -> None:
    user_id = message.from_user.id
    wr = WorkRepo(session)
    templates = await wr.get_templates(user_id)
    msg = await message.answer(PROMPT_TEXT, reply_markup=build_work_kb(templates, include_help=True))
    # сохраняем ссылку на последний промпт и ставим автоскрытие на 60 сек
    LAST_PROMPT[user_id] = (msg.chat.id, msg.message_id)
    schedule_kb_expire(msg.chat.id, msg.message_id, seconds=60)

async def _hide_last_prompt_kb(user_id: int, bot) -> None:
    """Скрыть инлайн-клавиатуру у последнего служебного сообщения пользователя."""
    pair = LAST_PROMPT.pop(user_id, None)
    if not pair:
        return
    chat_id, message_id = pair
    # отменяем джоб автоскрытия, чтобы потом не пытался редактировать
    cancel_kb_expire(chat_id, message_id)
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        # если сообщение уже удалено/изменено — просто игнорируем
        pass

@router.message(Command('mark'))
async def cmd_mark(message: Message):
    Session = session_factory()
    async with Session() as session:
        await _send_prompt(message, session)

@router.message(Command('report'))
async def cmd_report(message: Message):
    await message.answer('Report is showed')

@router.message(Command('settings'))
async def cmd_settings(message: Message):
    await message.answer('Settings are saved')

@router.message(F.text)
async def on_text(message: Message):
    user_id = message.from_user.id
    Session = session_factory()
    async with Session() as session:
        srepo = SettingsRepo(session)
        s = await srepo.get_or_create(user_id)
        parsed = parse_input(message.text or "", s.timezone, now_utc=datetime.now(timezone.utc))
        if parsed is None:
            await message.answer("Не понял ввод. Нажмите help для формата или выберите шаблон.")
            await _send_prompt(message, session)
            return

        wr = WorkRepo(session)
        if isinstance(parsed, ParsedDayOff):
            # выходной = удаляем запись за дату
            await wr.delete_entry(user_id, parsed.date.isoformat())
            # прячем клавиатуру у последнего промпта
            await _hide_last_prompt_kb(message.from_user.id, message.bot)
            await message.answer(f"Отметил: выходной {parsed.date.strftime('%d.%m.%Y')}")
            return

        # сохраняем рабочее время
        await wr.upsert_entry(user_id, parsed.date.isoformat(), parsed.start_min, parsed.end_min, parsed.break_min)
        # пополняем шаблоны только если введено без даты
        if getattr(parsed, "from_template_candidate", False):
            await wr.touch_template(user_id, parsed.start_min, parsed.end_min, parsed.break_min)

        # формируем ответ и скрываем клавиатуру у служебного сообщения
        total = (parsed.end_min - parsed.start_min) - parsed.break_min
        if parsed.break_min:
            txt = (f"Записал: {parsed.date.strftime('%d.%m.%Y')} "
                   f"{fmt_hhmm(parsed.start_min)}–{fmt_hhmm(parsed.end_min)}-{fmt_hhmm(parsed.break_min)} (итого {fmt_hhmm(total)})")
        else:
            txt = (f"Записал: {parsed.date.strftime('%d.%m.%Y')} "
                   f"{fmt_hhmm(parsed.start_min)}–{fmt_hhmm(parsed.end_min)} (итого {fmt_hhmm(total)})")

        await _hide_last_prompt_kb(message.from_user.id, message.bot)
        await message.answer(txt)
        # ВАЖНО: промпт ПОВТОРНО НЕ показываем.

@router.callback_query(F.data == "dayoff")
async def on_dayoff(cb: CallbackQuery):
    # сразу скрываем клавиатуру у этого сообщения
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    cancel_kb_expire(cb.message.chat.id, cb.message.message_id)

    user_id = cb.from_user.id
    Session = session_factory()
    async with Session() as session:
        srepo = SettingsRepo(session)
        s = await srepo.get_or_create(user_id)
        from zoneinfo import ZoneInfo
        now = datetime.now(timezone.utc).astimezone(ZoneInfo(s.timezone))
        d = now.date()
        wr = WorkRepo(session)
        await wr.delete_entry(user_id, d.isoformat())
    await cb.answer()
    await cb.message.answer(f"Отметил: выходной {d.strftime('%d.%m.%Y')}")

@router.callback_query(F.data == "help")
async def on_help(cb: CallbackQuery):
    user_id = cb.from_user.id
    Session = session_factory()
    async with Session() as session:
        wr = WorkRepo(session)
        templates = await wr.get_templates(user_id)
        try:
            await cb.message.edit_text(HELP_TEXT, reply_markup=build_work_kb(templates, include_help=False))
        except Exception:
            pass
    # обновляем таймер автоскрытия на 60 сек
    cancel_kb_expire(cb.message.chat.id, cb.message.message_id)
    schedule_kb_expire(cb.message.chat.id, cb.message.message_id, seconds=60)
    await cb.answer()

@router.callback_query(F.data.startswith("tpl:"))
async def on_tpl(cb: CallbackQuery):
    # сразу скрываем клавиатуру у сообщения с кнопками
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    cancel_kb_expire(cb.message.chat.id, cb.message.message_id)

    user_id = cb.from_user.id
    parts = cb.data.split(":", 3)
    start = int(parts[1]); end = int(parts[2]); brk = int(parts[3])

    Session = session_factory()
    async with Session() as session:
        srepo = SettingsRepo(session)
        s = await srepo.get_or_create(user_id)
        from zoneinfo import ZoneInfo
        now = datetime.now(timezone.utc).astimezone(ZoneInfo(s.timezone))
        d = now.date()
        wr = WorkRepo(session)
        await wr.upsert_entry(user_id, d.isoformat(), start, end, brk)

    total = (end - start) - brk
    if brk:
        txt = (f"Записал: {d.strftime('%d.%m.%Y')} "
               f"{fmt_hhmm(start)}–{fmt_hhmm(end)}-{fmt_hhmm(brk)} (итого {fmt_hhmm(total)})")
    else:
        txt = (f"Записал: {d.strftime('%d.%m.%Y')} "
               f"{fmt_hhmm(start)}–{fmt_hhmm(end)} (итого {fmt_hhmm(total)})")
    await cb.answer()
    await cb.message.answer(txt)
