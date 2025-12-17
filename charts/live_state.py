from dataclasses import dataclass
from threading import Lock
from typing import Dict, Iterable, List, Optional

import pandas as pd


@dataclass
class TradeRender:
    ts: pd.Timestamp
    symbol: str
    side: str
    qty: float
    price: float
    entry: float
    exit: Optional[float]
    fee: float
    pnl: float
    pnl_pct: float
    status: str

    def to_marker(self) -> Dict:
        return {
            "ts": self.ts,
            "price": self.price,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "entry": self.entry,
            "exit": self.exit or self.price,
            "fee": round(self.fee, 6),
            "pnl": round(self.pnl, 6),
            "pnl_pct": round(self.pnl_pct, 4),
            "status": self.status,
        }


class LiveStateBuffer:
    """Thread-safe buffer for chart + trade overlays.

    Producer threads push candle snapshots and trade renders. The UI thread reads
    immutable snapshots via :meth:`snapshot` during a lightweight QTimer tick.
    """

    def __init__(self):
        self._lock = Lock()
        self._df = pd.DataFrame()
        self._markers: List[Dict] = []
        self._last_price: Optional[float] = None

    def push_frame(self, df: pd.DataFrame):
        with self._lock:
            self._df = df.copy()
            if not df.empty:
                self._last_price = float(df["Close"].iloc[-1])

    def push_marker(self, marker: Dict):
        with self._lock:
            self._markers.append(marker)
            self._markers = self._markers[-300:]

    def extend_markers(self, markers: Iterable[Dict]):
        with self._lock:
            self._markers.extend(list(markers))
            self._markers = self._markers[-300:]

    def clear_markers(self):
        with self._lock:
            self._markers = []

    def snapshot(self):
        with self._lock:
            return self._df.copy(), list(self._markers), self._last_price
