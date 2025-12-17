from __future__ import annotations

import dataclasses
import datetime as dt


@dataclasses.dataclass
class Fill:
    price: float
    qty: float
    fee: float
    ts: dt.datetime
    latency_ms: int
    order_type: str = "market"
