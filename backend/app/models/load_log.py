from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoadLog(Base):
    __tablename__ = "load_log"
    __table_args__ = (
        CheckConstraint("mode IN ('baseline','controlled')", name="mode_valid"),
        Index("ix_load_log_station_mode_ts", "station_id", "mode", "ts"),
    )

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.station_id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_kw: Mapped[float] = mapped_column(Float)
    contract_kw: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(12))
