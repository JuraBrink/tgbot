# bot/db/users_repo.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User

class UsersRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        res = await self.session.execute(select(User).where(User.tg_id == tg_id))
        return res.scalar_one_or_none()

    async def upsert_user(self, tg_id: int, username: str | None) -> User:
        user = await self.get_by_tg_id(tg_id)
        if user is None:
            user = User(tg_id=tg_id, username=username)
            self.session.add(user)
        else:
            user.username = username  # обновим при случае
        await self.session.commit()
        await self.session.refresh(user)
        return user
