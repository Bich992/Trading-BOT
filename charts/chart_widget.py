from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget


class CandlestickItem(pg.GraphicsObject):
    """Lightweight candlestick item with incremental updates."""

    def __init__(self, width: float = 60):
        super().__init__()
        self._data: List[Tuple[float, float, float, float, float]] = []
        self._width = width

    def set_data(self, data: List[Tuple[float, float, float, float, float]], width: Optional[float] = None):
        if width:
            self._width = width
        self._data = data
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self):
        if not self._data:
            return pg.QtCore.QRectF()
        xs = [d[0] for d in self._data]
        lows = [d[3] for d in self._data]
        highs = [d[2] for d in self._data]
        return pg.QtCore.QRectF(min(xs) - self._width, min(lows), (max(xs) - min(xs)) + 2 * self._width, max(highs) - min(lows))

    def paint(self, painter, *_):
        w = self._width
        for t, o, h, l, c in self._data:
            color = pg.mkColor("#51cf66" if c >= o else "#ff6b6b")
            pen = pg.mkPen(color, width=1)
            painter.setPen(pen)
            painter.drawLine(pg.QtCore.QPointF(t, l), pg.QtCore.QPointF(t, h))

            body_top = max(o, c)
            body_bot = min(o, c)
            painter.fillRect(pg.QtCore.QRectF(t - w / 2, body_bot, w, body_top - body_bot if body_top != body_bot else 0.0001), color)


class ChartWidget(QWidget):
    """Real-time candlestick view with trade markers and volume bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._candles: List[Tuple[float, float, float, float, float]] = []
        self._volumes: List[Tuple[float, float]] = []
        self._markers_payload: List[Dict] = []
        self._ema_periods = (20, 50, 200)
        self._show_ema = False
        self._show_rsi = False
        self._show_macd = False

        self._ema_lines: Dict[str, pg.PlotDataItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        pg.setConfigOptions(foreground="#dee2e6", background="#0b0d11")

        self.graphics = pg.GraphicsLayoutWidget()
        layout.addWidget(self.graphics)

        # Use separate axis instances per plot to avoid sharing the same AxisItem object,
        # which pyqtgraph disallows across multiple plots.
        self._price_time_axis = pg.graphicsItems.DateAxisItem.DateAxisItem()
        self.price_plot = self.graphics.addPlot(row=0, col=0, axisItems={"bottom": self._price_time_axis})
        self.price_plot.showGrid(x=True, y=True, alpha=0.18)
        self.price_plot.setLabel("left", "Price")
        self.price_plot.getAxis("right").setStyle(showValues=False)
        self.price_plot.showAxis("right")
        self.price_plot.setMenuEnabled(False)
        self.price_plot.hideButtons()

        self._volume_time_axis = pg.graphicsItems.DateAxisItem.DateAxisItem()
        self.volume_plot = self.graphics.addPlot(row=1, col=0, axisItems={"bottom": self._volume_time_axis})
        self.volume_plot.setXLink(self.price_plot)
        self.volume_plot.showGrid(x=True, y=True, alpha=0.12)
        self.volume_plot.setLabel("left", "Volume")
        self.volume_plot.setMenuEnabled(False)
        self.volume_plot.hideButtons()
        self.volume_plot.setMaximumHeight(140)

        self.candles_item = CandlestickItem()
        self.price_plot.addItem(self.candles_item)
        self.volume_item = pg.BarGraphItem(x=[], height=[], width=30, brush="#495057")
        self.volume_plot.addItem(self.volume_item)

        self.marker_item = pg.ScatterPlotItem(size=12, pen=pg.mkPen("#0b0d11", width=1.2))
        self.price_plot.addItem(self.marker_item)

        self._last_width = 60

    def set_indicators(self, ema_periods=(20, 50, 200), rsi_period=14, macd_params=(12, 26, 9),
                       show_ema=False, show_rsi=False, show_macd=False):
        self._ema_periods = ema_periods
        self._show_ema = show_ema
        self._show_rsi = show_rsi
        self._show_macd = show_macd

    def update_snapshot(self, df: pd.DataFrame, markers: Optional[List[Dict]] = None, title: Optional[str] = None):
        if df is None or df.empty:
            return

        df = df.tail(600)
        times = df.index.map(pd.Timestamp.timestamp).to_numpy()
        width = self._estimate_width(df.index)
        candles = list(zip(times, df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values))
        volumes = list(zip(times, df.get("Volume", pd.Series([0] * len(df))).values))

        if not self._candles:
            self._candles = candles
            self._volumes = volumes
        else:
            last_ts = self._candles[-1][0]
            if candles[-1][0] > last_ts:
                self._candles.append(candles[-1])
                self._volumes.append(volumes[-1])
            else:
                self._candles[-1] = candles[-1]
                self._volumes[-1] = volumes[-1]
            if len(self._candles) > 800:
                self._candles = self._candles[-800:]
                self._volumes = self._volumes[-800:]

        self._last_width = width
        self.candles_item.set_data(self._candles, width=width)
        self._update_volume_bars()
        self._update_markers(markers or [])
        self._update_ema(df)

        if title:
            self.price_plot.setTitle(title, color="#e9ecef")

    def _update_volume_bars(self):
        if not self._volumes:
            return
        xs, vols = zip(*self._volumes)
        brushes = []
        for (_, _), (_, open_, _, _, close) in zip(self._volumes, self._candles):
            brushes.append(pg.mkBrush("#4dabf7" if close >= open_ else "#ff6b6b"))
        self.volume_item.setOpts(x=xs, height=vols, width=self._last_width * 0.8, brushes=brushes)

    def _update_markers(self, markers: Iterable[Dict]):
        points = []
        for m in markers:
            ts = pd.Timestamp(m.get("ts")).timestamp()
            price = float(m.get("price", 0))
            side = m.get("side", "")
            color = "#51cf66" if side.lower().startswith("b") else "#ff6b6b"
            symbol = "triangle" if side.lower().startswith("b") else "t"
            tooltip = self._marker_tooltip(m)
            payload = {**m, "tip": tooltip}
            points.append({
                "pos": (ts, price),
                "data": payload,
                "brush": pg.mkBrush(color),
                "symbol": symbol,
                "size": 14,
                "pen": pg.mkPen(pg.mkColor(color), width=1.2),
            })
        self.marker_item.setData(points)
        for spot in self.marker_item.points():
            payload = spot.data()
            if isinstance(payload, dict):
                spot.setToolTip(payload.get("tip", ""))

    def _marker_tooltip(self, m: Dict) -> str:
        ts = pd.Timestamp(m.get("ts")).strftime("%Y-%m-%d %H:%M:%S")
        side = m.get("side", "").upper()
        lines = [
            f"{ts}",
            f"{m.get('symbol', '')} {side}",
            f"Qty: {m.get('qty', 0):.4f}",
            f"Price: {m.get('price', 0):.4f}",
            f"Fee: {m.get('fee', 0):.4f}",
            f"PnL: {m.get('pnl', 0):.2f} ({m.get('pnl_pct', 0):.2f}%)",
            f"Status: {m.get('status', '')}",
        ]
        if m.get("exit"):
            lines.append(f"Exit @ {m['exit']:.4f}")
        return "\n".join(lines)

    def _update_ema(self, df: pd.DataFrame):
        if not self._show_ema:
            for line in self._ema_lines.values():
                self.price_plot.removeItem(line)
            self._ema_lines = {}
            return

        closes = df["Close"]
        ema_vals = {f"ema_{p}": closes.ewm(span=p).mean() for p in self._ema_periods}
        colors = ["#ffd43b", "#82c91e", "#4dabf7"]
        for (name, series), color in zip(ema_vals.items(), colors):
            x = series.index.map(pd.Timestamp.timestamp).to_numpy()
            if name not in self._ema_lines:
                line = self.price_plot.plot(x=x, y=series.values, pen=pg.mkPen(color, width=1.2))
                self._ema_lines[name] = line
            else:
                self._ema_lines[name].setData(x=x, y=series.values)

    def _estimate_width(self, index: Sequence[pd.Timestamp]) -> float:
        if len(index) < 2:
            return 60
        diffs = (index[-1] - index[-2]).total_seconds()
        return max(5.0, diffs * 0.6)
