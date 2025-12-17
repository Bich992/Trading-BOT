from __future__ import annotations

import dataclasses
import pandas as pd

from strategies.base import Signal, Strategy
from strategies import indicators as ind


@dataclasses.dataclass
class ExampleParams:
    fast: int = 20
    slow: int = 50
    atr_mult: float = 1.5


class ExampleStrategy(Strategy):
    name = "ema_rsi_mix"

    def __init__(self, params: ExampleParams | None = None):
        self.params = params or ExampleParams()

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        close = df["Close"]
        e_fast = ind.ema(close, self.params.fast)
        e_slow = ind.ema(close, self.params.slow)
        r = ind.rsi(close, 14)
        a = ind.atr(df, 14)

        action = "HOLD"
        confidence = 0.25
        if e_fast.iloc[-1] > e_slow.iloc[-1] and r.iloc[-1] > 55:
            action = "BUY"
            confidence = 0.65
        elif e_fast.iloc[-1] < e_slow.iloc[-1] and r.iloc[-1] < 45:
            action = "SELL"
            confidence = 0.65

        atr_last = float(a.iloc[-1]) if len(a) else 0.0
        entry = float(close.iloc[-1])
        sl = tp = None
        if atr_last > 0 and action != "HOLD":
            if action == "BUY":
                sl = entry - self.params.atr_mult * atr_last
                tp = entry + 2 * (entry - sl)
            else:
                sl = entry + self.params.atr_mult * atr_last
                tp = entry - 2 * (sl - entry)

        return Signal(action=action, stop_loss=sl, take_profit=tp, confidence=confidence)
