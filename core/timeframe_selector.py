from dataclasses import dataclass
import pandas as pd
from .regime import detect_regime


@dataclass
class TFScore:
    timeframe: str
    regime: str
    score: float
    diag: dict


def choose_best_timeframe(
    frames: dict[str, pd.DataFrame],
    prefer_trend_for: bool = True
) -> TFScore:
    """
    frames: { "1m": df, "5m": df, ... } all with OHLCV
    score model:
      - prefer TREND for trend-following assets (default)
      - penalize CHOP
      - reward clean RANGE if not trending
    """
    best = None

    for tf, df in frames.items():
        if df is None or len(df) < 80:
            continue

        regime, diag = detect_regime(df)
        slope = abs(diag["slope_norm"])
        dirb = abs(diag["dir_bias"])

        # Base score
        score = 0.0

        if regime == "TREND":
            score += 1.0 + 0.6 * min(slope, 2.0) + 0.4 * min(dirb, 2.0)
        elif regime == "RANGE":
            score += 0.9 + 0.3 * (1.0 - min(slope, 1.0))
        else:  # CHOP
            score -= 0.6 + 0.3 * min(slope, 2.0)

        # Slight preference for mid timeframes (reduce noise)
        if tf in ("5m", "15m"):
            score += 0.15
        if tf == "1m":
            score -= 0.10

        cur = TFScore(timeframe=tf, regime=regime, score=score, diag=diag)
        if best is None or cur.score > best.score:
            best = cur

    if best is None:
        return TFScore(timeframe="5m", regime="CHOP", score=-999, diag={})
    return best
