from datetime import datetime

from pydantic import BaseModel


class KpiOut(BaseModel):
    metric_key: str
    label: str
    value: float
    unit: str
    delta_pct: float | None
    up_is_good: bool
    trend: list[float]
    is_estimate: bool
    as_of: datetime
