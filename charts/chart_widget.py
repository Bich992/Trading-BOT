import pandas as pd
import mplfinance as mpf
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ChartWidget(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8, 6))
        super().__init__(self.fig)
        self.setParent(parent)

        self.ax_price = self.fig.add_subplot(3, 1, 1)
        self.ax_rsi = self.fig.add_subplot(3, 1, 2, sharex=self.ax_price)
        self.ax_macd = self.fig.add_subplot(3, 1, 3, sharex=self.ax_price)
        self.fig.tight_layout()

    def plot(self, df: pd.DataFrame, markers=None):
        self.ax_price.clear()
        self.ax_rsi.clear()
        self.ax_macd.clear()

        mpf.plot(
            df,
            ax=self.ax_price,
            type="candle",
            style="charles",
            mav=(20, 50, 200),
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
                        marker="^" if kind == "buy" else "v"
                    )

        rsi = self._rsi(df["Close"])
        self.ax_rsi.plot(df.index, rsi)
        self.ax_rsi.axhline(70, linestyle="--")
        self.ax_rsi.axhline(30, linestyle="--")
        self.ax_rsi.set_ylabel("RSI")

        macd, signal = self._macd(df["Close"])
        self.ax_macd.plot(df.index, macd, label="MACD")
        self.ax_macd.plot(df.index, signal, label="Signal")
        self.ax_macd.legend()
        self.ax_macd.set_ylabel("MACD")

        self.draw()

    def _rsi(self, series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _macd(self, series):
        ema12 = series.ewm(span=12).mean()
        ema26 = series.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        return macd, signal
