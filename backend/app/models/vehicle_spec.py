from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VehicleSpec(Base):
    """Vehicle master. Values are seeded demo assumptions, not manufacturer data."""

    __tablename__ = "vehicle_spec"

    vehicle_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), unique=True)
    battery_kwh: Mapped[float] = mapped_column(Float)
    max_dc_kw: Mapped[float] = mapped_column(Float)
    max_ac_kw: Mapped[float] = mapped_column(Float)
    taper_start_soc: Mapped[float] = mapped_column(Float, default=80, server_default="80")
    taper_min_ratio: Mapped[float] = mapped_column(Float, default=0.2, server_default="0.2")
    efficiency: Mapped[float] = mapped_column(Float, default=0.92, server_default="0.92")
