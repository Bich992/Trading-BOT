from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

from .indicators import ema, rsi, macd, atr
from .regime import detect_regime


@dataclass
class TradeDecision:
    action: str                 # BUY / SELL / HOLD
    symbol: str
    timeframe: str
    entry: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    confidence: float           # 0..1
    regime: str
    reasons: List[str]


class DecisionEngine:
    def __init__(self, risk_atr_mult_sl: float = 1.8, reward_r: float = 2.0):
        self.risk_atr_mult_sl = risk_atr_mult_sl
        self.reward_r = reward_r

    def decide(self, symbol: str, timeframe: str, df: pd.DataFrame) -> TradeDecision:
        close = df["Close"]
        last_close = float(close.iloc[-1])

        regime, diag = detect_regime(df)
        e20 = ema(close, 20)
        e50 = ema(close, 50)
        e200 = ema(close, 200) if len(df) >= 220 else ema(close, 100)

        r = rsi(close, 14)
        m, s, h = macd(close)

        a = atr(df, 14)
        atr_last = float(a.iloc[-1]) if len(a) else 0.0

        reasons = []
        confidence = 0.35  # baseline
        action = "HOLD"

        # Signals
        trend_up = e20.iloc[-1] > e50.iloc[-1] > e200.iloc[-1]
        trend_dn = e20.iloc[-1] < e50.iloc[-1] < e200.iloc[-1]
        macd_up = m.iloc[-1] > s.iloc[-1] and h.iloc[-1] > 0
        macd_dn = m.iloc[-1] < s.iloc[-1] and h.iloc[-1] < 0
        rsi_last = float(r.iloc[-1]) if len(r) else 50.0

        # Regime-aware rules (heuristics, explainable)
        if regime == "TREND":
            reasons.append(f"Regime TREND (slope={diag.get('slope_norm',0):.2f})")
            confidence += 0.15

            if trend_up and macd_up and rsi_last > 45:
                action = "BUY"
                confidence += 0.25
                reasons += ["EMA alignment bullish (20>50>200)", "MACD bullish", f"RSI={rsi_last:.1f} supports trend"]
            elif trend_dn and macd_dn and rsi_last < 55:
                action = "SELL"
                confidence += 0.25
                reasons += ["EMA alignment bearish (20<50<200)", "MACD bearish", f"RSI={rsi_last:.1f} supports trend"]
            else:
                reasons.append("Trend not confirmed by MACD/RSI → HOLD")
                confidence -= 0.05

        elif regime == "RANGE":
            reasons.append("Regime RANGE (mean-reversion priority)")
            confidence += 0.10

            if rsi_last < 32 and h.iloc[-1] > h.iloc[-2]:
                action = "BUY"
                confidence += 0.20
                reasons += [f"RSI oversold={rsi_last:.1f}", "MACD histogram improving"]
            elif rsi_last > 68 and h.iloc[-1] < h.iloc[-2]:
                action = "SELL"
                confidence += 0.20
                reasons += [f"RSI overbought={rsi_last:.1f}", "MACD histogram weakening"]
            else:
                reasons.append(f"RSI mid-range={rsi_last:.1f} → HOLD")
                confidence -= 0.05

        else:  # CHOP
            reasons.append("Regime CHOP (avoid trading)")
            confidence -= 0.15
            action = "HOLD"

        confidence = max(0.0, min(1.0, confidence))

        # Risk model (ATR-based SL/TP) only if trade
        entry = last_close if action in ("BUY", "SELL") else None
        if entry is not None and atr_last > 0:
            if action == "BUY":
                sl = entry - self.risk_atr_mult_sl * atr_last
                tp = entry + self.reward_r * (entry - sl)
            else:
                sl = entry + self.risk_atr_mult_sl * atr_last
                tp = entry - self.reward_r * (sl - entry)
        else:
            sl = tp = None

        if action in ("BUY", "SELL"):
            reasons.append(f"ATR={atr_last:.4f} → SL/TP computed")

        return TradeDecision(
            action=action,
            symbol=symbol,
            timeframe=timeframe,
            entry=entry,
            stop_loss=sl,
            take_profit=tp,
            confidence=confidence,
            regime=regime,
            reasons=reasons
        )
