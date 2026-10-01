from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.station import Station


class Charger(Base):
    __tablename__ = "charger"
    __table_args__ = (
        CheckConstraint("status IN ('idle','charging','fault')", name="status_valid"),
        CheckConstraint("rated_kw > 0", name="rated_kw_positive"),
    )

    charger_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.station_id"), index=True)
    rated_kw: Mapped[float] = mapped_column(Float)
    connector_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), default="idle", server_default="idle")

    station: Mapped[Station] = relationship(back_populates="chargers")
