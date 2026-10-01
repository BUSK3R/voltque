from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChargeSession(Base):
    """Waiting queue and active charging unified in one table (PRD 6)."""

    __tablename__ = "charge_session"
    __table_args__ = (
        CheckConstraint("soc_start BETWEEN 0 AND 100", name="soc_start_range"),
        CheckConstraint("soc_target BETWEEN 0 AND 100", name="soc_target_range"),
        CheckConstraint(
            "soc_current IS NULL OR soc_current BETWEEN 0 AND 100", name="soc_current_range"
        ),
        CheckConstraint("soc_start < soc_target", name="soc_start_lt_target"),
        CheckConstraint(
            "status IN ('waiting','called','charging','done','cancelled','no_show')",
            name="status_valid",
        ),
        Index("ix_charge_session_charger_status_queue", "charger_id", "status", "queue_pos"),
    )

    session_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey("charger.charger_id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle_spec.vehicle_id"))
    anon_user_id: Mapped[str] = mapped_column(String(64))  # anonymous session id only
    soc_start: Mapped[float] = mapped_column(Numeric(5, 2))
    soc_target: Mapped[float] = mapped_column(Numeric(5, 2))
    soc_current: Mapped[float | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(12))
    queue_pos: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alloc_kw: Mapped[float | None] = mapped_column(Numeric(6, 1))
    calc_minutes: Mapped[float | None] = mapped_column(Numeric(7, 2))
    calc_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
