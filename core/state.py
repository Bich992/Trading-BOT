"""Shared state for portfolio, orders and risk exposure."""
from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Dict, List, Optional

from core.paper_engine import PaperPortfolio, Trade


@dataclasses.dataclass
class PositionState:
    symbol: str
    net_qty: float
    avg_entry: float
    unrealized: float


@dataclasses.dataclass
class OrderState:
    id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    submitted_at: dt.datetime


@dataclasses.dataclass
class EngineState:
    portfolio: PaperPortfolio
    open_orders: List[OrderState]
    last_prices: Dict[str, float]

    def exposure_pct(self, symbol: str) -> float:
        price = self.last_prices.get(symbol, 0.0)
        equity = self.portfolio.equity(self.last_prices)
        if equity <= 0 or price <= 0:
            return 0.0
        qty = self.portfolio.net_qty(symbol)
        return abs(qty * price) / equity

    def positions(self, prices: Dict[str, float]) -> List[PositionState]:
        res: List[PositionState] = []
        for sym, book in self.portfolio.books.items():
            nq = book.net_qty()
            if abs(nq) < 1e-9:
                continue
            price = prices.get(sym, 0.0)
            unreal = self.portfolio.unrealized_pnl(sym, price)
            res.append(
                PositionState(
                    symbol=sym,
                    net_qty=nq,
                    avg_entry=book.avg_entry(),
                    unrealized=unreal,
                )
            )
        return res
