from dataclasses import dataclass, field
from typing import List, Optional
import datetime as dt


@dataclass
class Leg:
    ts: dt.datetime
    side: str              # "long" or "short"
    qty: float             # positive qty
    entry: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    confidence: float = 0.0
    regime: str = ""
    reason: str = ""


@dataclass
class PositionBook:
    symbol: str
    legs: List[Leg] = field(default_factory=list)

    def net_qty(self) -> float:
        q = 0.0
        for l in self.legs:
            q += l.qty if l.side == "long" else -l.qty
        return q

    def avg_entry(self) -> float:
        nq = self.net_qty()
        if nq == 0:
            return 0.0
        # Weighted average for the net direction
        if nq > 0:
            total = sum(l.qty * l.entry for l in self.legs if l.side == "long")
            qty = sum(l.qty for l in self.legs if l.side == "long")
            return total / qty if qty else 0.0
        else:
            total = sum(l.qty * l.entry for l in self.legs if l.side == "short")
            qty = sum(l.qty for l in self.legs if l.side == "short")
            return total / qty if qty else 0.0

    def legs_count(self) -> int:
        # count only legs contributing to net direction (ignore fully closed = removed)
        return len(self.legs)

    def direction(self) -> str:
        nq = self.net_qty()
        if nq > 0:
            return "long"
        if nq < 0:
            return "short"
        return "flat"
