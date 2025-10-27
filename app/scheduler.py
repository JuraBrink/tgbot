# app/scheduler.py
from __future__ import annotations
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from aiogram import Bot

_scheduler: Optional[AsyncIOScheduler] = None
_bot: Optional[Bot] = None

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    global _scheduler, _bot
    _bot = bot
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()
    return _scheduler

def get_scheduler() -> AsyncIOScheduler:
    assert _scheduler is not None, "Scheduler is not initialized. Call setup_scheduler() first."
    return _scheduler

# ===== reminders (пн–сб) =====
async def send_reminder(tg_id: int) -> None:
    assert _bot is not None, "Bot is not set"
    try:
        await _bot.send_message(chat_id=tg_id, text="Напоминание: пора отметить рабочее время.")
    except Exception:
        pass

def _rem_job_id(user_id: int) -> str:
    return f"reminder:{user_id}"

def schedule_user_reminder(user_id: int, minutes: int, tz: str) -> None:
    sched = get_scheduler()
    try:
        sched.remove_job(job_id=_rem_job_id(user_id))
    except Exception:
        pass
    if minutes <= 0:
        return
    hour = minutes // 60
    minute = minutes % 60
    trigger = CronTrigger(day_of_week="mon-sat", hour=hour, minute=minute, timezone=ZoneInfo(tz))
    sched.add_job(send_reminder, trigger=trigger, id=_rem_job_id(user_id), args=[user_id], replace_existing=True)

def remove_user_reminder(user_id: int) -> None:
    sched = get_scheduler()
    try:
        sched.remove_job(job_id=_rem_job_id(user_id))
    except Exception:
        pass

# ===== авто-скрытие инлайн-клавиатур =====
def _kb_expire_job_id(chat_id: int, message_id: int) -> str:
    return f"expire:{chat_id}:{message_id}"

async def _hide_kb(chat_id: int, message_id: int) -> None:
    assert _bot is not None
    try:
        await _bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        # сообщение могло быть удалено/уже без клавиатуры — игнор
        pass

def schedule_kb_expire(chat_id: int, message_id: int, seconds: int = 60) -> None:
    sched = get_scheduler()
    # На всякий случай удалим существующий
    try:
        sched.remove_job(job_id=_kb_expire_job_id(chat_id, message_id))
    except Exception:
        pass
    run_at = datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
    trigger = DateTrigger(run_date=run_at)
    sched.add_job(_hide_kb, trigger=trigger, id=_kb_expire_job_id(chat_id, message_id),
                  args=[chat_id, message_id], replace_existing=True)

def cancel_kb_expire(chat_id: int, message_id: int) -> None:
    sched = get_scheduler()
    try:
        sched.remove_job(job_id=_kb_expire_job_id(chat_id, message_id))
    except Exception:
        pass
