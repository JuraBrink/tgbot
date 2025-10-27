# db/settings_repo.py
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import UserSettings
from datetime import date

class SettingsRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> Optional[UserSettings]:
        res = await self.session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
        return res.scalar_one_or_none()

    async def get_or_create(self, user_id: int) -> UserSettings:
        us = await self.get(user_id)
        if us is None:
            today = date.today().isoformat()
            us = UserSettings(
                user_id=user_id,
                baseline_date=today,
                baseline_worked_min=0,
                updated_at=UserSettings.now_iso(),
                reminder_minutes=0,
                timezone="Europe/Warsaw",
            )
            self.session.add(us)
            await self.session.commit()
            await self.session.refresh(us)
        return us

    async def set_baseline(self, user_id: int, baseline_date_iso: str, worked_minutes: int) -> UserSettings:
        us = await self.get_or_create(user_id)
        us.baseline_date = baseline_date_iso  # YYYY-MM-DD
        us.baseline_worked_min = worked_minutes
        us.updated_at = UserSettings.now_iso()
        await self.session.commit()
        return us

    async def set_reminder_minutes(self, user_id: int, minutes: int) -> UserSettings:
        us = await self.get_or_create(user_id)
        us.reminder_minutes = minutes  # 0..1439; 0 = OFF
        us.updated_at = UserSettings.now_iso()
        await self.session.commit()
        return us

    async def set_timezone(self, user_id: int, tz: str) -> UserSettings:
        us = await self.get_or_create(user_id)
        us.timezone = tz  # строго IANA
        us.updated_at = UserSettings.now_iso()
        await self.session.commit()
        return us
