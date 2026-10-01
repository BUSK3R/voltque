from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.charger import Charger


class Station(Base):
    __tablename__ = "station"

    station_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    contract_kw: Mapped[float] = mapped_column(Float)
    limit_ratio: Mapped[float] = mapped_column(Float, default=0.9, server_default="0.9")

    chargers: Mapped[list[Charger]] = relationship(back_populates="station")
