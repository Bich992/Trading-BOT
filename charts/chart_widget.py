from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from matplotlib import dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle


class ChartWidget(FigureCanvas):
    """
    Candlestick widget optimised for incremental updates.

    The widget keeps matplotlib artists for each candle/marker so that a UI timer
    can call ``update_snapshot`` every 100–250ms without re-plotting the entire
    figure. Indicators are optional and disabled by default to keep the render
    light for live feeds.
    """

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(9, 7), tight_layout=True, facecolor="#0b0d11")
        super().__init__(self.fig)
        self.setParent(parent)

        self.ax_price = self.fig.add_subplot(2, 1, 1)
        self.ax_indic = self.fig.add_subplot(2, 1, 2, sharex=self.ax_price)

        self.mpl_connect("scroll_event", self._on_scroll)
        self.mpl_connect("pick_event", self._on_pick)

        for ax in (self.ax_price, self.ax_indic):
            ax.set_facecolor("#0f1116")
            ax.tick_params(colors="#dee2e6")
            for spine in ax.spines.values():
                spine.set_edgecolor("#1f2933")

        self._candles: List[Dict] = []
        self._ema_lines: Dict[str, object] = {}
        self._rsi_line = None
        self._macd_lines: Tuple[object, object, object] = (None, None, None)
        self._marker_scatter = None
        self._marker_payload: List[Dict] = []
        self._hover_label = self.ax_price.annotate(
            "",
            xy=(0, 0),
            xytext=(15, 15),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="#0f1116", ec="#1f2933", lw=0.8),
            arrowprops=dict(arrowstyle="->", color="#adb5bd"),
        )
        self._hover_label.set_visible(False)

        self._last_xlim: Optional[Tuple[float, float]] = None
        self._ema_periods = (20, 50, 200)
        self._rsi_period = 14
        self._macd_params = (12, 26, 9)
        self._show_ema = False
        self._show_rsi = False
        self._show_macd = False
        self._latest_df = pd.DataFrame()

        self._init_axes()

    def _init_axes(self):
        self.ax_price.grid(True, linestyle=":", alpha=0.25, color="#1f2933")
        self.ax_price.set_title("Live price", loc="left")
        self.ax_indic.grid(True, linestyle=":", alpha=0.25, color="#1f2933")
        self.ax_indic.set_ylabel("Indicators")
        self.ax_indic.set_ylim(0, 100)
        self.fig.tight_layout()
        self.draw_idle()

    def set_indicators(self, ema_periods=(20, 50, 200), rsi_period=14, macd_params=(12, 26, 9),
                       show_ema=False, show_rsi=False, show_macd=False):
        self._ema_periods = ema_periods
        self._rsi_period = rsi_period
        self._macd_params = macd_params
        self._show_ema = show_ema
        self._show_rsi = show_rsi
        self._show_macd = show_macd

    def update_snapshot(self, df: pd.DataFrame, markers: Optional[List[Dict]] = None,
                        title: Optional[str] = None):
        if df is None or df.empty:
            return

        df = df.tail(400)  # keep view light
        changed = self._latest_df.empty or (df.index[-1] != self._latest_df.index[-1])
        self._latest_df = df
        self.ax_price.set_title(title or "Live price", loc="left")
        self._update_candles(df)

        if self._show_ema:
            self._update_ema(df)
        else:
            self._clear_ema()

        self._update_indicator_panel(df)
        self._update_markers(df, markers or [])

        if self._last_xlim:
            self.ax_price.set_xlim(*self._last_xlim)
        self.fig.canvas.draw_idle()

        if changed:
            self.flush_events()

    # -------- Candles --------
    def _update_candles(self, df: pd.DataFrame):
        ohlc = df.reset_index()[["Timestamp", "Open", "High", "Low", "Close"]]
        ohlc["x"] = ohlc["Timestamp"].map(mdates.date2num)

        if not self._candles:
            self.ax_price.cla()
            self._init_axes()
            self._candles = []
            for _, row in ohlc.iterrows():
                self._draw_single_candle(row)
            self.ax_price.relim()
            self.ax_price.autoscale_view()
            return

        last_known = self._candles[-1]["x"] if self._candles else None
        for _, row in ohlc.tail(3).iterrows():
            if last_known is None or row["x"] > last_known + 1e-9:
                self._draw_single_candle(row)
                last_known = row["x"]
            elif abs(row["x"] - last_known) < 1e-9:
                self._update_last_candle(row)

        self.ax_price.relim()
        self.ax_price.autoscale_view()

    def _draw_single_candle(self, row):
        width = 0.0008
        color = "#51cf66" if row["Close"] >= row["Open"] else "#ff6b6b"
        rect = Rectangle((row["x"] - width / 2, min(row["Open"], row["Close"])),
                         width, abs(row["Close"] - row["Open"]),
                         facecolor=color, edgecolor="#0b0d11", linewidth=0.6)
        wick = LineCollection([[(row["x"], row["Low"]), (row["x"], row["High"])]],
                               colors=color, linewidths=0.9)
        self.ax_price.add_patch(rect)
        self.ax_price.add_collection(wick)
        self._candles.append({"rect": rect, "wick": wick, "x": row["x"]})

    def _update_last_candle(self, row):
        candle = self._candles[-1]
        rect: Rectangle = candle["rect"]
        wick: LineCollection = candle["wick"]
        rect.set_y(min(row["Open"], row["Close"]))
        rect.set_height(abs(row["Close"] - row["Open"]))
        color = "#51cf66" if row["Close"] >= row["Open"] else "#ff6b6b"
        rect.set_facecolor(color)
        rect.set_edgecolor("#0b0d11")
        wick.set_color(color)
        wick.set_segments([[(row["x"], row["Low"]), (row["x"], row["High"])]])

    # -------- Indicators --------
    def _update_indicator_panel(self, df: pd.DataFrame):
        self.ax_indic.cla()
        self.ax_indic.grid(True, linestyle=":", alpha=0.25, color="#1f2933")
        if self._show_rsi:
            rsi = self._rsi(df["Close"], period=self._rsi_period)
            self.ax_indic.plot(df.index, rsi, color="#4dabf7", linewidth=1.1, label=f"RSI {self._rsi_period}")
            self.ax_indic.fill_between(df.index, rsi, 50, color="#4dabf7", alpha=0.12)
            self.ax_indic.axhline(70, linestyle="--", color="#ff6b6b", alpha=0.7)
            self.ax_indic.axhline(30, linestyle="--", color="#69db7c", alpha=0.7)
            self.ax_indic.set_ylim(0, 100)
        elif self._show_macd:
            macd, signal = self._macd(df["Close"], self._macd_params)
            hist = macd - signal
            self.ax_indic.bar(df.index, hist, color="#748ffc", alpha=0.45, width=0.8, label="Hist")
            self.ax_indic.plot(df.index, macd, label="MACD", color="#9775fa")
            self.ax_indic.plot(df.index, signal, label="Signal", color="#f783ac")
            self.ax_indic.set_ylabel("MACD")
            self.ax_indic.legend(loc="upper left")
        else:
            self.ax_indic.set_ylabel("Indicators (OFF)")
        self.fig.tight_layout()

    def _update_ema(self, df: pd.DataFrame):
        closes = df["Close"]
        ema_values = {f"ema_{p}": closes.ewm(span=p).mean() for p in self._ema_periods}
        if not self._ema_lines:
            colors = ["#ffd43b", "#82c91e", "#4dabf7"]
            for (name, series), color in zip(ema_values.items(), colors):
                line, = self.ax_price.plot(series.index, series.values, color=color, linewidth=1.1, label=name.upper())
                self._ema_lines[name] = line
            self.ax_price.legend(loc="upper left")
            return

        for name, series in ema_values.items():
            if name in self._ema_lines:
                line = self._ema_lines[name]
                line.set_data(series.index, series.values)
            else:
                line, = self.ax_price.plot(series.index, series.values, linewidth=1.1)
                self._ema_lines[name] = line

    def _clear_ema(self):
        if not self._ema_lines:
            return
        for line in self._ema_lines.values():
            try:
                line.remove()
            except ValueError:
                pass
        self._ema_lines = {}
        self.ax_price.legend().set_visible(False) if self.ax_price.legend_ else None

    # -------- Trades/markers --------
    def _update_markers(self, df: pd.DataFrame, markers: Iterable[Dict]):
        if not markers:
            if self._marker_scatter:
                self._marker_scatter.remove()
                self._marker_scatter = None
                self._marker_payload = []
            return

        xs, ys, colors, shapes = [], [], [], []
        payload = []
        for m in markers:
            ts = pd.Timestamp(m["ts"])
            if ts not in df.index:
                continue
            xs.append(ts.to_pydatetime())
            ys.append(m["price"])
            colors.append("#51cf66" if m.get("pnl", 0) >= 0 else "#ff6b6b")
            shapes.append("^" if m.get("side", "buy") == "buy" else "v")
            payload.append(m)

        if not xs:
            return

        if self._marker_scatter is None:
            self._marker_scatter = self.ax_price.scatter(
                xs, ys, c=colors, marker="o", s=70, edgecolors="#0b0d11", linewidths=0.8,
                alpha=0.9, picker=5
            )
        else:
            self._marker_scatter.set_offsets(pd.DataFrame({"x": xs, "y": ys})[["x", "y"]].values)
            self._marker_scatter.set_color(colors)
        self._marker_payload = payload

    def _on_pick(self, event):
        if event.artist != self._marker_scatter or not self._marker_payload:
            return
        ind = event.ind[0]
        if ind >= len(self._marker_payload):
            return
        m = self._marker_payload[ind]
        self._hover_label.xy = (mdates.date2num(pd.Timestamp(m["ts"])) , m["price"])
        note = (
            f"{m.get('symbol', '')} {m.get('side','').upper()}\n"
            f"Qty: {m.get('qty','-')}\nEntry: {m.get('entry','-')}\n"
            f"Exit: {m.get('exit', m.get('price','-'))}\nFee: {m.get('fee','-')}\n"
            f"PnL: {m.get('pnl','-')} ({m.get('pnl_pct','-')}%)\n"
            f"{m.get('ts')}"
        )
        self._hover_label.set_text(note)
        self._hover_label.set_visible(True)
        self.draw_idle()

    # -------- Utils --------
    def _rsi(self, series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _macd(self, series, params=(12, 26, 9)):
        fast, slow, signal_span = params
        ema_fast = series.ewm(span=fast).mean()
        ema_slow = series.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=signal_span).mean()
        return macd, signal

    def _on_scroll(self, event):
        if event.inaxes not in {self.ax_price, self.ax_indic}:
            return

        base_scale = 1.2
        scale_factor = 1 / base_scale if event.button == "up" else base_scale

        x_left, x_right = self.ax_price.get_xlim()
        x_range = (x_right - x_left) * scale_factor

        xdata = event.xdata if event.xdata is not None else (x_left + x_right) / 2
        new_left = xdata - x_range / 2
        new_right = xdata + x_range / 2

        for ax in (self.ax_price, self.ax_indic):
            ax.set_xlim(new_left, new_right)

        self._last_xlim = (new_left, new_right)
        self.fig.canvas.draw_idle()
