import datetime as dt

from sqlalchemy import Date, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KpiDaily(Base):
    __tablename__ = "kpi_daily"

    station_id: Mapped[int] = mapped_column(ForeignKey("station.station_id"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    avg_wait_min: Mapped[float] = mapped_column(Float, default=0)
    load_factor: Mapped[float] = mapped_column(Float, default=0)
    peak_reduction_kw: Mapped[float] = mapped_column(Float, default=0)
