import ccxt
import pandas as pd


class BinanceProvider:
    def __init__(self):
        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"}
        })

    def fetch_ohlc(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        ohlc = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(
            ohlc,
            columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"]
        )
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="ms")
        df.set_index("Timestamp", inplace=True)
        return df
