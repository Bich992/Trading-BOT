import pandas as pd
import mplfinance as mpf
from typing import Optional
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ChartWidget(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(9, 7), tight_layout=True, facecolor="#0b0d11")
        super().__init__(self.fig)
        self.setParent(parent)

        self.ax_price = self.fig.add_subplot(3, 1, 1)
        self.ax_rsi = self.fig.add_subplot(3, 1, 2, sharex=self.ax_price)
        self.ax_macd = self.fig.add_subplot(3, 1, 3, sharex=self.ax_price)

        # Enable smooth mouse-wheel zooming over the charts.
        self.mpl_connect("scroll_event", self._on_scroll)

        for ax in (self.ax_price, self.ax_rsi, self.ax_macd):
            ax.set_facecolor("#0f1116")
            ax.tick_params(colors="#dee2e6")
            for spine in ax.spines.values():
                spine.set_edgecolor("#1f2933")

    def plot(
        self,
        df: pd.DataFrame,
        markers=None,
        ema_list=(20, 50, 200),
        rsi_period=14,
        macd_params=(12, 26, 9),
        title: Optional[str] = None,
    ):
        """Render OHLC candles with indicators and optional markers."""
        self.ax_price.clear()
        self.ax_rsi.clear()
        self.ax_macd.clear()

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mpf.make_marketcolors(
                up="#51cf66", down="#ff6b6b", edge="inherit", wick="inherit"
            ),
            gridcolor="#1f2933",
        )

        mpf.plot(
            df,
            ax=self.ax_price,
            type="candle",
            style=style,
            mav=ema_list,
            volume=False,
            show_nontrading=True
        )

        if markers:
            for m in markers:
                ts = m["ts"]
                price = m["price"]
                kind = m["kind"]
                if ts in df.index:
                    self.ax_price.scatter(
                        [ts], [price],
                        marker="^" if kind == "buy" else "v",
                        color="green" if kind == "buy" else "red",
                        s=60,
                        alpha=0.9,
                        edgecolor="black",
                        linewidth=0.6,
                    )

        self.ax_price.grid(True, linestyle=":", alpha=0.25, color="#1f2933")
        self.ax_price.set_title(title or "Price / EMA (sim)", loc="left")

        rsi = self._rsi(df["Close"], period=rsi_period)
        self.ax_rsi.plot(df.index, rsi, color="#4dabf7", linewidth=1.2)
        self.ax_rsi.fill_between(df.index, rsi, 50, color="#4dabf7", alpha=0.12)
        self.ax_rsi.axhline(70, linestyle="--", color="#ff6b6b", alpha=0.7)
        self.ax_rsi.axhline(30, linestyle="--", color="#69db7c", alpha=0.7)
        self.ax_rsi.set_ylabel(f"RSI ({rsi_period})")
        self.ax_rsi.grid(True, linestyle=":", alpha=0.25, color="#1f2933")

        macd, signal = self._macd(df["Close"], macd_params)
        hist = macd - signal
        self.ax_macd.bar(df.index, hist, color="#748ffc", alpha=0.45, width=0.8, label="Hist")
        self.ax_macd.plot(df.index, macd, label="MACD", color="#9775fa")
        self.ax_macd.plot(df.index, signal, label="Signal", color="#f783ac")
        self.ax_macd.legend(loc="upper left")
        self.ax_macd.set_ylabel("MACD")
        self.ax_macd.grid(True, linestyle=":", alpha=0.25, color="#1f2933")

        self.fig.tight_layout()
        self.draw()

    def _rsi(self, series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
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
        if event.inaxes not in {self.ax_price, self.ax_rsi, self.ax_macd}:
            return

        base_scale = 1.2
        scale_factor = 1 / base_scale if event.button == "up" else base_scale

        x_left, x_right = self.ax_price.get_xlim()
        x_range = (x_right - x_left) * scale_factor

        xdata = event.xdata if event.xdata is not None else (x_left + x_right) / 2
        new_left = xdata - x_range / 2
        new_right = xdata + x_range / 2

        for ax in (self.ax_price, self.ax_rsi, self.ax_macd):
            ax.set_xlim(new_left, new_right)

        # Limit zoom level to a sensible range to avoid blank charts.
        self.fig.canvas.draw_idle()
