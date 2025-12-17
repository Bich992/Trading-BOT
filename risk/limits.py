from __future__ import annotations

from dataclasses import dataclass

from core.state import EngineState
from risk.position_sizing import PositionSizer
from core.config import RiskConfig


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.sizer = PositionSizer()

    def check_limits(self, state: EngineState, symbol: str, qty: float) -> bool:
        if qty <= 0:
            return False
        exposure = state.exposure_pct(symbol)
        if exposure >= self.cfg.max_drawdown_pct:
            return False
        if len(state.portfolio.trades) >= self.cfg.max_trades:
            return False
        # simple kill switch based on equity drop
        equity = state.portfolio.equity(state.last_prices)
        if equity <= (1 - self.cfg.kill_switch_loss_pct) * state.portfolio.cash:
            return False
        # concurrent legs guard
        if state.portfolio.get_book(symbol).legs_count() >= self.cfg.max_concurrent_legs:
            return False
        return True
