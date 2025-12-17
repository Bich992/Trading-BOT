from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import datetime as dt

from .position_legs import PositionBook, Leg


@dataclass
class Trade:
    ts: dt.datetime
    symbol: str
    side: str               # "buy" or "sell"
    qty: float
    price: float
    fee: float
    order_type: str = "paper"
    pnl_realized: float = 0.0
    note: str = ""


@dataclass
class PaperPortfolio:
    cash: float = 1000.0
    fee_rate: float = 0.001
    books: Dict[str, PositionBook] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)

    def _fee(self, notional: float) -> float:
        return abs(notional) * self.fee_rate

    def get_book(self, symbol: str) -> PositionBook:
        if symbol not in self.books:
            self.books[symbol] = PositionBook(symbol=symbol)
        return self.books[symbol]

    def net_qty(self, symbol: str) -> float:
        return self.get_book(symbol).net_qty()

    def avg_entry(self, symbol: str) -> float:
        return self.get_book(symbol).avg_entry()

    def equity(self, prices: Dict[str, float]) -> float:
        eq = self.cash
        for sym, book in self.books.items():
            nq = book.net_qty()
            if nq != 0 and sym in prices:
                eq += nq * prices[sym]
        return eq

    def total_fees(self) -> float:
        return sum(t.fee for t in self.trades)

    def realized_pnl(self) -> float:
        return sum(t.pnl_realized for t in self.trades)

    def unrealized_pnl(self, symbol: str, price: float) -> float:
        book = self.get_book(symbol)
        nq = book.net_qty()
        if nq == 0:
            return 0.0
        ae = book.avg_entry()
        if nq > 0:
            return (price - ae) * nq
        return (ae - price) * abs(nq)

    # ---- Main entry points: open/add legs and close legs ----

    def open_leg(
        self,
        symbol: str,
        side: str,                 # "long" or "short"
        qty: float,
        price: float,
        ts: dt.datetime,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        confidence: float = 0.0,
        regime: str = "",
        reason: str = "",
        order_type: str = "auto"
    ) -> Trade:
        if qty <= 0:
            raise ValueError("qty must be > 0")
        notional = qty * price
        fee = self._fee(notional)

        # Paper cash model:
        # long: pay notional+fee
        # short: receive notional-fee (simplified; no margin model)
        if side == "long":
            if self.cash < notional + fee:
                raise ValueError("Not enough cash for long (incl fee).")
            self.cash -= (notional + fee)
        elif side == "short":
            self.cash += (notional - fee)
        else:
            raise ValueError("side must be 'long' or 'short'")

        book = self.get_book(symbol)
        book.legs.append(Leg(ts=ts, side=side, qty=qty, entry=price, sl=sl, tp=tp,
                            confidence=confidence, regime=regime, reason=reason))

        t = Trade(ts=ts, symbol=symbol,
                  side="buy" if side == "long" else "sell",
                  qty=qty, price=price, fee=fee, order_type=order_type,
                  pnl_realized=-fee, note=f"OPEN {side.upper()} LEG")
        self.trades.append(t)
        return t

    def close_qty_fifo(
        self,
        symbol: str,
        qty_to_close: float,
        price: float,
        ts: dt.datetime,
        order_type: str = "auto",
        note: str = ""
    ) -> Trade:
        """
        Closes qty against existing net position using FIFO on legs of that direction.
        If net long: closing = SELL qty_to_close
        If net short: closing = BUY qty_to_close
        """
        if qty_to_close <= 0:
            raise ValueError("qty_to_close must be > 0")

        book = self.get_book(symbol)
        nq = book.net_qty()
        if nq == 0:
            raise ValueError("No position to close.")

        direction = "long" if nq > 0 else "short"
        qty_avail = abs(nq)
        qty = min(qty_to_close, qty_avail)

        notional = qty * price
        fee = self._fee(notional)

        realized = 0.0
        remaining = qty

        # Cash impact:
        # closing long (sell): receive notional - fee
        # closing short (buy): pay notional + fee
        if direction == "long":
            self.cash += (notional - fee)
        else:
            if self.cash < notional + fee:
                raise ValueError("Not enough cash to cover short (incl fee).")
            self.cash -= (notional + fee)

        # FIFO close from legs of the direction
        new_legs: List[Leg] = []
        for leg in book.legs:
            if remaining <= 0:
                new_legs.append(leg)
                continue

            if leg.side != direction:
                new_legs.append(leg)
                continue

            take = min(leg.qty, remaining)
            # realized PnL for that chunk
            if direction == "long":
                realized += (price - leg.entry) * take
            else:
                realized += (leg.entry - price) * take

            leg.qty -= take
            remaining -= take

            if leg.qty > 1e-12:
                new_legs.append(leg)

        book.legs = new_legs

        realized -= fee

        t = Trade(
            ts=ts,
            symbol=symbol,
            side="sell" if direction == "long" else "buy",
            qty=qty,
            price=price,
            fee=fee,
            order_type=order_type,
            pnl_realized=realized,
            note=note or f"CLOSE {direction.upper()} FIFO"
        )
        self.trades.append(t)
        return t
