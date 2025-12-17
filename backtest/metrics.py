from __future__ import annotations

import math
from typing import List

import pandas as pd

from core.paper_engine import Trade


def equity_curve_from_trades(trades: List[Trade], starting_cash: float) -> List[float]:
    equity = starting_cash
    curve = [equity]
    for t in trades:
        equity += t.pnl_realized
        curve.append(equity)
    return curve


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    if returns.std(ddof=0) == 0:
        return 0.0
    return (returns.mean() - risk_free) / returns.std(ddof=0) * math.sqrt(252)


def max_drawdown(curve: List[float]) -> float:
    peak = -float("inf")
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd
