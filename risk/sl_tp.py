from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StopLossTakeProfit:
    stop_loss: Optional[float]
    take_profit: Optional[float]
    trailing: Optional[float] = None

    def should_exit(self, price: float) -> bool:
        if self.stop_loss is not None and price <= self.stop_loss:
            return True
        if self.take_profit is not None and price >= self.take_profit:
            return True
        return False
