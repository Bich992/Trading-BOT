from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeeModel:
    maker_fee: float = 0.0002
    taker_fee: float = 0.0006
    slippage_bps: float = 1.5

    def apply_slippage(self, price: float, side: str) -> float:
        if self.slippage_bps <= 0:
            return price
        slip = price * (self.slippage_bps / 10_000)
        return price + slip if side.lower() == "buy" else price - slip

    def fee(self, notional: float, taker: bool = True) -> float:
        rate = self.taker_fee if taker else self.maker_fee
        return abs(notional) * rate
