"""Point-in-time KPI observations for the dashboard (e.g. flights_airborne, fx_usd_try, oil_brent)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPrimaryKeyMixin


class KPI(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "kpis"
    __table_args__ = (Index("ix_kpis_metric_as_of", "metric_key", "as_of"),)

    metric_key: Mapped[str] = mapped_column(String(50))  # e.g. "flights_airborne", "oil_brent_usd"
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(100), default="")
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)  # true = licensed-data placeholder
