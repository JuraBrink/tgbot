from __future__ import annotations
from datetime import datetime, date, timezone
from typing import Dict, Tuple, Iterable, List
from zoneinfo import ZoneInfo
import re

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.kb import build_work_kb
from app.parse import parse_input, fmt_hhmm, ParsedDayOff
from db.work_repo import WorkRepo
from db.settings_repo import SettingsRepo
from db.middleware import session_factory
from app.scheduler import schedule_kb_expire, cancel_kb_expire
from html import escape

router = Router(name="main_router")

PROMPT_TEXT = "Укажите время работы:"
HELP_TEXT = (
    "Укажите время работы:\n"
    "вида: \"Дата\" \"Начало\"-\"Окончание\"(-\"Обед\")\n"
    "где \"Дата\" DD/MM/YYYY вида: 3.7.25 или 03-07-2025\n"
    "время HH:MM вида: 7, 07, 7:5, 07:05"
)

REPORT_PROMPT_TEXT = "Укажите период отчета: (Дата начала - Дата окончания)"

# Храним последний показанный промпт пользователя: user_id -> (chat_id, message_id)
LAST_PROMPT: Dict[int, Tuple[int, int]] = {}

# ==== Утилиты для отчета ====

_DOW_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

PERIOD_RE = re.compile(
    r"""
    ^\s*
    (?P<d1>\d{1,2})[./-](?P<m1>\d{1,2})[./-](?P<y1>\d{2}|\d{4})
    \s*-\s*
    (?P<d2>\d{1,2})[./-](?P<m2>\d{1,2})[./-](?P<y2>\d{2}|\d{4})
    \s*$
    """,
    re.VERBOSE,
)

def _norm_year(y: int) -> int:
    return 2000 + y if y < 100 else y

def _parse_period(text: str) -> tuple[date, date] | None:
    m = PERIOD_RE.match(text)
    if not m:
        return None
    d1 = int(m.group("d1")); m1 = int(m.group("m1")); y1 = _norm_year(int(m.group("y1")))
    d2 = int(m.group("d2")); m2 = int(m.group("m2")); y2 = _norm_year(int(m.group("y2")))
    try:
        start = date(y1, m1, d1)
        end = date(y2, m2, d2)
    except ValueError:
        return None
    if start > end:
        return None
    return start, end

def _build_report_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Текущий месяц", callback_data="rep:cur")
    kb.button(text="Прошлый месяц", callback_data="rep:prev")
    kb.adjust(2)
    return kb.as_markup()

async def _hide_last_prompt_kb(user_id: int, bot) -> None:
    pair = LAST_PROMPT.pop(user_id, None)
    if not pair:
        return
    chat_id, message_id = pair
    cancel_kb_expire(chat_id, message_id)
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        pass

async def _send_prompt(message: Message, session) -> None:
    user_id = message.from_user.id
    wr = WorkRepo(session)
    templates = await wr.get_templates(user_id)
    msg = await message.answer(PROMPT_TEXT, reply_markup=build_work_kb(templates, include_help=True))
    LAST_PROMPT[user_id] = (msg.chat.id, msg.message_id)
    schedule_kb_expire(msg.chat.id, msg.message_id, seconds=60)

async def _send_report_prompt(message: Message) -> None:
    msg = await message.answer(REPORT_PROMPT_TEXT, reply_markup=_build_report_kb())
    # фикс: запоминаем и отчётный промпт, чтобы потом убирать его клавиатуру
    LAST_PROMPT[message.from_user.id] = (msg.chat.id, msg.message_id)
    schedule_kb_expire(msg.chat.id, msg.message_id, seconds=60)

async def _fetch_entries(session, user_id: int, start: date, end: date) -> List[tuple[str,int,int,int]]:
    """
    Возвращает список (work_date_iso, start_min, end_min, break_min) отсортированный по дате.
    """
    from sqlalchemy import text as sqltext
    res = await session.execute(
        sqltext("""
            SELECT work_date, start_min, end_min, break_min
            FROM work_entries
            WHERE user_id=:uid AND work_date BETWEEN :s AND :e
            ORDER BY work_date ASC
        """),
        {"uid": user_id, "s": start.isoformat(), "e": end.isoformat()},
    )
    return [(r[0], r[1], r[2], r[3]) for r in res.fetchall()]

def _format_report_rows(rows: List[tuple[str,int,int,int]]) -> tuple[str, int]:
    """
    Формирует текст отчета в код-блоке. Возвращает (текст, total_min).
    """
    total_min = 0
    lines: List[str] = []
    lines.append("Дата        │ День │ Время работы           │ Отработано")
    lines.append("────────────┼──────┼────────────────────────┼───────────")

    for iso, start_min, end_min, break_min in rows:
        day = datetime.strptime(iso, "%Y-%m-%d").date()
        dow = _DOW_RU[day.weekday()]
        work_str = f"{fmt_hhmm(start_min)}–{fmt_hhmm(end_min)}" + (f"-{fmt_hhmm(break_min)}" if break_min else "")
        worked = (end_min - start_min) - break_min
        total_min += worked
        date_str = day.strftime("%d.%m.%Y")
        lines.append(f"{date_str:12}│ {dow:4} │ {work_str:22} │ {fmt_hhmm(worked):>9}")

    body = "\n".join(lines)
    return body, total_min

def _clip_telegram(text: str, budget: int = 3900) -> str:
    if len(text) <= budget:
        return text
    return text[:budget - 1]

async def _send_report_text(message: Message, session, start: date, end: date, user_id: int) -> None:
    """
    ВНИМАНИЕ: user_id передаём снаружи (message.from_user в коллбэке = бот, а не человек).
    """
    rows = await _fetch_entries(session, user_id, start, end)
    body, total_min = _format_report_rows(rows)
    footer = f"\n\nИтого: {fmt_hhmm(total_min)}"
    # code = f"```\n{body}{footer}\n```"
    code = f"{body}{footer}"
    code = _clip_telegram(code)
    code = f"<pre>{escape(code)}</pre>"    
    await message.answer(code)

# ==== Команды ====

@router.message(Command('mark'))
async def cmd_mark(message: Message):
    Session = session_factory()
    async with Session() as session:
        await _send_prompt(message, session)

@router.message(Command('report'))
async def cmd_report(message: Message):
    await _send_report_prompt(message)

@router.message(Command('settings'))
async def cmd_settings(message: Message):
    await message.answer('Settings are saved')

# ==== Текстовый ввод ====

@router.message(F.text)
async def on_text(message: Message):
    user_id = message.from_user.id
    text_in = message.text or ""
    Session = session_factory()
    async with Session() as session:
        # 1) Период отчета "Дата-Дата"
        period = _parse_period(text_in)
        if period:
            await _hide_last_prompt_kb(user_id, message.bot)
            await _send_report_text(message, session, period[0], period[1], user_id)
            return

        # 2) Ввод рабочего времени
        srepo = SettingsRepo(session)
        s = await srepo.get_or_create(user_id)
        parsed = parse_input(text_in, s.timezone, now_utc=datetime.now(timezone.utc))
        if parsed is None:
            await message.answer("Не понял ввод. Нажмите help для формата или выберите шаблон.")
            await _send_prompt(message, session)
            return

        wr = WorkRepo(session)
        if isinstance(parsed, ParsedDayOff):
            await wr.delete_entry(user_id, parsed.date.isoformat())
            await _hide_last_prompt_kb(user_id, message.bot)
            await message.answer(f"Отметил: выходной {parsed.date.strftime('%d.%m.%Y')}")
            return

        await wr.upsert_entry(user_id, parsed.date.isoformat(), parsed.start_min, parsed.end_min, parsed.break_min)
        if getattr(parsed, "from_template_candidate", False):
            await wr.touch_template(user_id, parsed.start_min, parsed.end_min, parsed.break_min)

        total = (parsed.end_min - parsed.start_min) - parsed.break_min
        if parsed.break_min:
            txt = (f"Записал: {parsed.date.strftime('%d.%m.%Y')} "
                   f"{fmt_hhmm(parsed.start_min)}–{fmt_hhmm(parsed.end_min)}-{fmt_hhmm(parsed.break_min)} (итого {fmt_hhmm(total)})")
        else:
            txt = (f"Записал: {parsed.date.strftime('%d.%m.%Y')} "
                   f"{fmt_hhmm(parsed.start_min)}–{fmt_hhmm(parsed.end_min)} (итого {fmt_hhmm(total)})")

        await _hide_last_prompt_kb(user_id, message.bot)
        await message.answer(txt)

# ==== Коллбеки отчета ====

def _month_bounds(dt: date) -> tuple[date, date]:
    start = dt.replace(day=1)
    if start.month == 12:
        next_start = date(start.year + 1, 1, 1)
    else:
        next_start = date(start.year, start.month + 1, 1)
    from datetime import timedelta
    return start, next_start - timedelta(days=1)

def _prev_month_bounds(dt: date) -> tuple[date, date]:
    if dt.month == 1:
        y, m = dt.year - 1, 12
    else:
        y, m = dt.year, dt.month - 1
    from datetime import timedelta
    start = date(y, m, 1)
    if m == 12:
        next_m_start = date(y + 1, 1, 1)
    else:
        next_m_start = date(y, m + 1, 1)
    return start, next_m_start - timedelta(days=1)

@router.callback_query(F.data == "rep:cur")
async def on_rep_cur(cb: CallbackQuery):
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
        now_local = datetime.now(timezone.utc).astimezone(ZoneInfo(s.timezone)).date()
        start, end = _month_bounds(now_local)
        await _send_report_text(cb.message, session, start, end, user_id)
    await cb.answer()

@router.callback_query(F.data == "rep:prev")
async def on_rep_prev(cb: CallbackQuery):
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
        now_local = datetime.now(timezone.utc).astimezone(ZoneInfo(s.timezone)).date()
        start, end = _prev_month_bounds(now_local)
        await _send_report_text(cb.message, session, start, end, user_id)
    await cb.answer()

# ==== Коллбеки существующих кнопок ====

@router.callback_query(F.data == "dayoff")
async def on_dayoff(cb: CallbackQuery):
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
    cancel_kb_expire(cb.message.chat.id, cb.message.message_id)
    schedule_kb_expire(cb.message.chat.id, cb.message.message_id, seconds=60)
    await cb.answer()

@router.callback_query(F.data.startswith("tpl:"))
async def on_tpl(cb: CallbackQuery):
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
