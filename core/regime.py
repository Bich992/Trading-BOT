import pandas as pd
from .indicators import ema, atr


def detect_regime(df: pd.DataFrame) -> tuple[str, dict]:
    """
    Returns: (regime, diagnostics)
    Regime:
      - TREND: directional + strong slope
      - RANGE: low directional strength + oscillatory
      - CHOP: high volatility but unclear direction
    """
    close = df["Close"]
    e20 = ema(close, 20)
    e50 = ema(close, 50)

    # Trend strength proxy: slope of EMA50 vs ATR
    slope = e50.diff(10) / (atr(df, 14) + 1e-9)
    slope_last = float(slope.iloc[-1]) if len(slope) else 0.0

    # Volatility proxy
    a = atr(df, 14)
    atr_last = float(a.iloc[-1]) if len(a) else 0.0

    # Direction proxy
    dir_bias = float((e20.iloc[-1] - e50.iloc[-1]) / (atr_last + 1e-9))

    # Heuristics
    if abs(slope_last) > 0.8 and abs(dir_bias) > 0.4:
        regime = "TREND"
    elif atr_last > 0 and abs(slope_last) < 0.35 and abs(dir_bias) < 0.25:
        regime = "RANGE"
    else:
        regime = "CHOP"

    diag = {
        "slope_norm": slope_last,
        "atr": atr_last,
        "dir_bias": dir_bias,
    }
    return regime, diag
