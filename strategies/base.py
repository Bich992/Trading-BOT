from __future__ import annotations

import dataclasses
import pandas as pd


@dataclasses.dataclass
class Signal:
    action: str  # BUY / SELL / HOLD
    stop_loss: float | None
    take_profit: float | None
    confidence: float
    symbol: str | None = None
    timeframe: str | None = None


class Strategy:
    name: str = "base"

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        raise NotImplementedError
