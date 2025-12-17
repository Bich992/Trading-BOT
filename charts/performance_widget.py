from __future__ import annotations

from typing import Iterable, List

import pandas as pd
import pyqtgraph as pg
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.paper_engine import Trade


class PerformanceWidget(QWidget):
    """Equity + PnL panel similar to a strategy report."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._percent_mode = False
        self._per_period = "trade"
        self._starting_cash = 0.0
        self._last_trades: List[Trade] = []
        self._last_equity = 0.0

        pg.setConfigOptions(foreground="#dee2e6", background="#0b0d11")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.stats_grid = self._build_stats()
        layout.addLayout(self.stats_grid)

        toggle_row = QHBoxLayout()
        toggle_row.addStretch()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Assoluto", "Percentuale"])
        self.cmb_mode.currentIndexChanged.connect(self._switch_mode)
        toggle_row.addWidget(QLabel("Scala"))
        toggle_row.addWidget(self.cmb_mode)

        self.cmb_period = QComboBox()
        self.cmb_period.addItems(["Per trade", "Per giorno"])
        self.cmb_period.currentIndexChanged.connect(self._switch_period)
        toggle_row.addWidget(QLabel("Bucket"))
        toggle_row.addWidget(self.cmb_period)
        layout.addLayout(toggle_row)

        self.graphics = pg.GraphicsLayoutWidget()
        layout.addWidget(self.graphics, 1)

        self.equity_plot = self.graphics.addPlot(row=0, col=0)
        self.equity_plot.showGrid(x=True, y=True, alpha=0.15)
        self.equity_plot.setLabel("left", "Equity")
        self.equity_line = self.equity_plot.plot(pen=pg.mkPen("#12b886", width=2))

        self.pnl_plot = self.graphics.addPlot(row=1, col=0)
        self.pnl_plot.showGrid(x=True, y=True, alpha=0.12)
        self.pnl_plot.setLabel("left", "PnL")
        self.pnl_plot.setXLink(self.equity_plot)
        self.pnl_bars = pg.BarGraphItem(x=[], height=[], width=0.8)
        self.pnl_plot.addItem(self.pnl_bars)

    def _build_stats(self):
        grid = QGridLayout()
        labels = [
            ("PnL totale", "--"),
            ("Max drawdown", "--"),
            ("Operazioni", "0"),
            ("Win rate", "--"),
            ("Profit factor", "--"),
            ("Fee totali", "--"),
        ]
        self.stat_labels = {}
        for i, (title, value) in enumerate(labels):
            name = QLabel(title)
            name.setStyleSheet("color:#adb5bd;font-size:12px;")
            val = QLabel(value)
            val.setStyleSheet("font-size:15px;font-weight:700;")
            grid.addWidget(name, 0, i)
            grid.addWidget(val, 1, i)
            self.stat_labels[title] = val
        return grid

    def update_performance(self, trades: Iterable[Trade], starting_cash: float, now_equity: float):
        trades_sorted = sorted(list(trades), key=lambda t: t.ts)
        self._last_trades = trades_sorted
        self._last_equity = now_equity
        self._starting_cash = starting_cash
        if not trades_sorted:
            self._render_empty(now_equity)
            return

        df = pd.DataFrame(trades_sorted)
        df["Timestamp"] = pd.to_datetime(df["ts"])
        df.sort_values("Timestamp", inplace=True)
        df["pnl_net"] = df["pnl_realized"]
        df["fee"] = df["fee"].abs()

        if self._percent_mode:
            df["pnl_display"] = (df["pnl_net"] / starting_cash) * 100
        else:
            df["pnl_display"] = df["pnl_net"]

        if self._per_period == "day":
            grouped = df.set_index("Timestamp").resample("1D").agg({"pnl_net": "sum", "pnl_display": "sum"})
            grouped["ts"] = grouped.index
            df_display = grouped.reset_index(drop=True)
        else:
            df_display = df

        df_display["equity"] = starting_cash + df_display["pnl_net"].cumsum()
        df_display.loc[df_display.index[-1], "equity"] = now_equity

        self._plot_equity(df_display)
        self._plot_bars(df_display)
        self._update_stats(df_display, df)

    def _plot_equity(self, df: pd.DataFrame):
        x = df.get("ts", df.get("Timestamp", pd.Series(range(len(df)))))
        if hasattr(x, "dtype") and str(x.dtype).startswith("datetime"):
            xs = pd.to_datetime(x).map(pd.Timestamp.timestamp)
            self.equity_plot.setLabel("bottom", "Timestamp")
        else:
            xs = range(len(df))
            self.equity_plot.setLabel("bottom", "Trade #")
        self.equity_line.setData(x=xs, y=df["equity"].values)

    def _plot_bars(self, df: pd.DataFrame):
        x = df.get("ts", df.get("Timestamp", pd.Series(range(len(df)))))
        if hasattr(x, "dtype") and str(x.dtype).startswith("datetime"):
            xs = pd.to_datetime(x).map(pd.Timestamp.timestamp)
        else:
            xs = range(len(df))
        heights = df["pnl_display"].values
        brushes = [pg.mkBrush("#51cf66") if h >= 0 else pg.mkBrush("#ff6b6b") for h in heights]
        self.pnl_bars.setOpts(x=xs, height=heights, width=0.8, brushes=brushes)

    def _update_stats(self, df_display: pd.DataFrame, df_raw: pd.DataFrame):
        pnl_total = df_raw["pnl_net"].sum()
        max_eq = df_display["equity"].cummax()
        drawdown = ((df_display["equity"] - max_eq) / max_eq) * 100
        max_dd = drawdown.min() if len(drawdown) else 0
        trades_count = len(df_raw)
        win_rate = (df_raw[df_raw["pnl_net"] > 0].shape[0] / trades_count * 100) if trades_count else 0
        profit_factor = self._profit_factor(df_raw["pnl_net"].tolist())
        fees = df_raw["fee"].sum()

        fmt_pnl = f"{pnl_total/self._starting_cash*100:.2f}%" if self._percent_mode else f"{pnl_total:.2f}"
        self.stat_labels["PnL totale"].setText(fmt_pnl)
        self.stat_labels["Max drawdown"].setText(f"{max_dd:.2f}%")
        self.stat_labels["Operazioni"].setText(str(trades_count))
        self.stat_labels["Win rate"].setText(f"{win_rate:.1f}%")
        self.stat_labels["Profit factor"].setText(f"{profit_factor:.2f}")
        self.stat_labels["Fee totali"].setText(f"{fees:.4f}")

    def _profit_factor(self, pnls: List[float]) -> float:
        gains = sum(p for p in pnls if p > 0)
        losses = sum(abs(p) for p in pnls if p < 0)
        if losses == 0:
            return float("inf") if gains > 0 else 0
        return gains / losses

    def _render_empty(self, now_equity: float):
        self.equity_line.setData([0, 1], [self._starting_cash, now_equity])
        self.pnl_bars.setOpts(x=[], height=[])
        for label in self.stat_labels.values():
            label.setText("--")

    def _switch_mode(self, idx: int):
        self._percent_mode = idx == 1
        self._replot_last()

    def _switch_period(self, idx: int):
        self._per_period = "day" if idx == 1 else "trade"
        self._replot_last()

    def _replot_last(self):
        if not self._last_trades and self._last_equity == 0:
            return
        self.update_performance(self._last_trades, self._starting_cash, self._last_equity)
