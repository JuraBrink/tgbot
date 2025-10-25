# bot/db/models.py
from datetime import datetime
from sqlalchemy import Integer, BigInteger, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from db.base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)  # Telegram user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UserSettings(Base):
    """
    user_settings: базовая точка для расчёта отчетов по пользователю.
    baseline_date хранится в ISO (YYYY-MM-DD) строкой, чтобы не зависеть от TZ.
    updated_at — ISO с точностью до секунд.
    """
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    baseline_date: Mapped[str] = mapped_column(String, nullable=False)        # YYYY-MM-DD
    baseline_worked_min: Mapped[int] = mapped_column(Integer, nullable=False) # минуты
    updated_at: Mapped[str] = mapped_column(String, nullable=False)           # ISO datetime

    @staticmethod
    def now_iso() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")