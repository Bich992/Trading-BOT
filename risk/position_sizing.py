from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SizeConfig:
    fixed_notional: float = 100.0
    risk_per_trade_pct: float = 0.01


class PositionSizer:
    def __init__(self, cfg: SizeConfig | None = None):
        self.cfg = cfg or SizeConfig()

    def size_position(self, equity: float, price: float, stop_loss: float | None) -> float:
        if price <= 0:
            return 0.0
        if stop_loss is None or stop_loss == price:
            return max(self.cfg.fixed_notional, 0) / price
        risk_amt = max(equity * self.cfg.risk_per_trade_pct, 0)
        stop_dist = abs(price - stop_loss)
        if stop_dist <= 0:
            return max(self.cfg.fixed_notional, 0) / price
        return max(risk_amt / stop_dist, 0)
