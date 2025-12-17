from __future__ import annotations

import datetime as dt
from typing import Optional

from core.config import PaperConfig
from core.paper_engine import PaperPortfolio
from execution.fees import FeeModel
from execution.orders import Fill
from strategies.base import Signal


class PaperBroker:
    def __init__(self, cfg: PaperConfig):
        self.cfg = cfg
        self.fees = FeeModel(
            maker_fee=cfg.maker_fee,
            taker_fee=cfg.taker_fee,
            slippage_bps=cfg.slippage_bps,
        )
        self.portfolio = PaperPortfolio(
            cash=cfg.starting_cash,
            fee_rate=cfg.fee_rate,
            slippage_bps=cfg.slippage_bps,
            simulate_latency_ms=cfg.simulate_latency_ms,
        )

    def execute(self, signal: Signal, qty: float, price: float) -> Optional[Fill]:
        if signal.action == "HOLD" or qty <= 0:
            return None
        side = "long" if signal.action == "BUY" else "short"
        price_exec = self.fees.apply_slippage(price, signal.action.lower())
        fee = self.fees.fee(qty * price_exec)
        ts = dt.datetime.utcnow()
        if signal.action == "BUY":
            self.portfolio.open_leg(
                signal.symbol if hasattr(signal, "symbol") else "asset",
                side,
                qty,
                price,
                ts,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                confidence=signal.confidence,
                order_type="paper",
            )
        else:
            self.portfolio.open_leg(
                signal.symbol if hasattr(signal, "symbol") else "asset",
                side,
                qty,
                price,
                ts,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                confidence=signal.confidence,
                order_type="paper",
            )
        return Fill(price=price_exec, qty=qty, fee=fee, ts=ts, latency_ms=self.cfg.simulate_latency_ms)
