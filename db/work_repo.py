
from __future__ import annotations
from typing import List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

class WorkRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_entry(self, user_id: int, date_iso: str, start_min: int, end_min: int, break_min: int) -> None:
        await self.session.execute(text("""
            INSERT INTO work_entries (user_id, work_date, start_min, end_min, break_min, updated_at)
            VALUES (:uid, :d, :s, :e, :b, strftime('%Y-%m-%dT%H:%M:%S','now'))
            ON CONFLICT(user_id, work_date) DO UPDATE SET
                start_min=excluded.start_min,
                end_min=excluded.end_min,
                break_min=excluded.break_min,
                updated_at=excluded.updated_at
        """), {"uid": user_id, "d": date_iso, "s": start_min, "e": end_min, "b": break_min})
        await self.session.commit()

    async def delete_entry(self, user_id: int, date_iso: str) -> None:
        await self.session.execute(text("DELETE FROM work_entries WHERE user_id=:uid AND work_date=:d"),
                                   {"uid": user_id, "d": date_iso})
        await self.session.commit()

    async def touch_template(self, user_id: int, start_min: int, end_min: int, break_min: int) -> None:
        await self.session.execute(text("""
            INSERT INTO work_templates (user_id, start_min, end_min, break_min, last_used_at)
            VALUES (:uid, :s, :e, :b, strftime('%Y-%m-%dT%H:%M:%S','now'))
            ON CONFLICT(user_id, start_min, end_min, break_min) DO UPDATE SET
                last_used_at=excluded.last_used_at
        """), {"uid": user_id, "s": start_min, "e": end_min, "b": break_min})
        # leave only 4 most recent
        await self.session.execute(text("""
            DELETE FROM work_templates
            WHERE user_id=:uid AND rowid NOT IN (
                SELECT rowid FROM work_templates
                WHERE user_id=:uid
                ORDER BY last_used_at DESC
                LIMIT 4
            )
        """), {"uid": user_id})
        await self.session.commit()

    async def get_templates(self, user_id: int) -> List[Tuple[int,int,int]]:
        res = await self.session.execute(text("""
            SELECT start_min, end_min, break_min
            FROM work_templates
            WHERE user_id=:uid
            ORDER BY last_used_at DESC
            LIMIT 4
        """), {"uid": user_id})
        return [(r[0], r[1], r[2]) for r in res.fetchall()]
