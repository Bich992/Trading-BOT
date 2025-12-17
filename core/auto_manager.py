from dataclasses import dataclass
from typing import Dict, List, Optional
import datetime as dt
import pandas as pd

from .decision_engine import DecisionEngine
from .paper_engine import PaperPortfolio
from .indicators import atr
from .timeframe_selector import TFScore


@dataclass
class AutoConfig:
    interval_sec: int = 10
    conf_entry: float = 0.70
    conf_add: float = 0.80
    max_open_assets: int = 6

    # legs
    max_legs_per_asset: int = 3
    add_mode: str = "PYRAMID"  # OFF | PYRAMID | MEANREV
    allow_short: bool = True

    # sizing
    size_mode: str = "FIXED"   # FIXED | AUTO_RISK
    fixed_notional: float = 50.0
    risk_per_trade_pct: float = 0.01  # 1%

    # controls
    cooldown_sec: int = 120
    pyramiding_atr: float = 0.8   # add after move in favor >= 0.8 ATR
    meanrev_rsi_add: float = 28.0 # add long if RSI <= 28 (range)
    meanrev_rsi_add_short: float = 72.0 # add short if RSI >= 72 (range)


class AutoManager:
    def __init__(self, engine: DecisionEngine, portfolio: PaperPortfolio):
        self.engine = engine
        self.portfolio = portfolio
        self.last_trade_time: Dict[str, dt.datetime] = {}  # per symbol

    def _cooldown_ok(self, symbol: str, now: dt.datetime, cooldown_sec: int) -> bool:
        t = self.last_trade_time.get(symbol)
        if not t:
            return True
        return (now - t).total_seconds() >= cooldown_sec

    def _position_count(self) -> int:
        n = 0
        for sym in list(self.portfolio.books.keys()):
            if abs(self.portfolio.net_qty(sym)) > 0:
                n += 1
        return n

    def _compute_qty(self, symbol: str, price: float, sl: Optional[float], cfg: AutoConfig, equity: float) -> float:
        if cfg.size_mode == "FIXED":
            notional = max(0.0, cfg.fixed_notional)
            return notional / price if price > 0 else 0.0

        # AUTO_RISK sizing (risk amount / stop distance)
        # If no SL, fallback to fixed notional
        if sl is None or sl == price:
            notional = max(0.0, cfg.fixed_notional)
            return notional / price if price > 0 else 0.0

        risk_amount = max(0.0, equity * cfg.risk_per_trade_pct)
        stop_dist = abs(price - sl)
        if stop_dist <= 0:
            notional = max(0.0, cfg.fixed_notional)
            return notional / price if price > 0 else 0.0

        qty = risk_amount / stop_dist
        # limit by cash realistically for long
        return max(0.0, qty)

    def step(
        self,
        watchlist: List[str],
        ohlc_by_symbol: Dict[str, pd.DataFrame],
        now: dt.datetime,
        cfg: AutoConfig,
        best_timeframes: Optional[Dict[str, TFScore]] = None,
    ) -> List[str]:
        """
        Returns log lines about actions taken.
        """
        logs: List[str] = []

        best_timeframes = best_timeframes or {}

        # build prices for equity
        prices = {}
        for s, df in ohlc_by_symbol.items():
            if df is not None and not df.empty:
                prices[s] = float(df["Close"].iloc[-1])
        equity = self.portfolio.equity(prices)

        # Global cap: max open assets
        open_assets = self._position_count()

        for symbol in watchlist:
            df = ohlc_by_symbol.get(symbol)
            if df is None or df.empty or len(df) < 120:
                continue

            price = float(df["Close"].iloc[-1])
            a = atr(df, 14).iloc[-1]
            a = float(a) if a == a else 0.0  # NaN guard

            nq = self.portfolio.net_qty(symbol)
            direction = "flat"
            if nq > 0:
                direction = "long"
            elif nq < 0:
                direction = "short"

            # Cooldown prevents overtrading
            if not self._cooldown_ok(symbol, now, cfg.cooldown_sec):
                continue

            # Decision (use your DecisionEngine)
            tf_choice = best_timeframes.get(symbol)
            timeframe_used = tf_choice.timeframe if tf_choice else "auto"
            d = self.engine.decide(symbol, timeframe_used, df)
            tf_note = f"tf={timeframe_used}"

            # 1) If position exists: focus on exits first
            if direction != "flat":
                # Exit rule (simple, risk-reducing):
                # - if DecisionEngine flips opposite with good confidence → reduce / close
                # - if CHOP → reduce risk (partial close)
                if d.action == "HOLD":
                    continue

                # Opposite signal: close part or all
                if (direction == "long" and d.action == "SELL") or (direction == "short" and d.action == "BUY"):
                    qty_to_close = abs(nq) * 0.50  # scale-out 50%
                    t = self.portfolio.close_qty_fifo(symbol, qty_to_close, price, now, order_type="auto",
                                                      note="Signal flip → scale-out 50%")
                    self.last_trade_time[symbol] = now
                    logs.append(f"{symbol}: SCALE-OUT 50% on flip | pnlR={t.pnl_realized:.4f} | {tf_note} reg={d.regime}")
                    continue

                # Same-direction add logic (legs)
                if cfg.add_mode == "OFF":
                    continue

                # cap legs
                legs_count = self.portfolio.get_book(symbol).legs_count()
                if legs_count >= cfg.max_legs_per_asset:
                    continue

                # decide if add is allowed
                if cfg.add_mode == "PYRAMID":
                    # add only if moved in favor >= pyramiding_atr * ATR and confidence high
                    avg = self.portfolio.avg_entry(symbol)
                    if a <= 0:
                        continue

                    moved_ok = False
                    if direction == "long":
                        moved_ok = (price - avg) >= cfg.pyramiding_atr * a
                        want_action = (d.action == "BUY" and d.confidence >= cfg.conf_add)
                        if moved_ok and want_action:
                            qty = self._compute_qty(symbol, price, d.stop_loss, cfg, equity)
                            if qty > 0:
                                t = self.portfolio.open_leg(symbol, "long", qty, price, now, d.stop_loss, d.take_profit,
                                                            d.confidence, d.regime, "PYRAMID add", order_type="auto")
                                self.last_trade_time[symbol] = now
                                logs.append(f"{symbol}: PYRAMID ADD LONG | qty={qty:.6f} | {tf_note} reg={d.regime}")
                    else:
                        moved_ok = (avg - price) >= cfg.pyramiding_atr * a
                        want_action = (d.action == "SELL" and d.confidence >= cfg.conf_add)
                        if moved_ok and want_action and cfg.allow_short:
                            qty = self._compute_qty(symbol, price, d.stop_loss, cfg, equity)
                            if qty > 0:
                                t = self.portfolio.open_leg(symbol, "short", qty, price, now, d.stop_loss, d.take_profit,
                                                            d.confidence, d.regime, "PYRAMID add", order_type="auto")
                                self.last_trade_time[symbol] = now
                                logs.append(f"{symbol}: PYRAMID ADD SHORT | qty={qty:.6f} | {tf_note} reg={d.regime}")

                elif cfg.add_mode == "MEANREV":
                    # Add only in RANGE and with strong mean-reversion conditions
                    if d.regime != "RANGE":
                        continue

                    # Use RSI from DecisionEngine’s close? (we keep it simple: approximate via decision reasons)
                    # Here: only allow add when confidence high and action same direction
                    if direction == "long":
                        if d.action == "BUY" and d.confidence >= cfg.conf_add:
                            qty = self._compute_qty(symbol, price, d.stop_loss, cfg, equity) * 0.6
                            if qty > 0:
                                self.portfolio.open_leg(symbol, "long", qty, price, now, d.stop_loss, d.take_profit,
                                                        d.confidence, d.regime, "MEANREV add", order_type="auto")
                                self.last_trade_time[symbol] = now
                                logs.append(f"{symbol}: MEANREV ADD LONG | qty={qty:.6f} | {tf_note} reg={d.regime}")
                    else:
                        if d.action == "SELL" and d.confidence >= cfg.conf_add and cfg.allow_short:
                            qty = self._compute_qty(symbol, price, d.stop_loss, cfg, equity) * 0.6
                            if qty > 0:
                                self.portfolio.open_leg(symbol, "short", qty, price, now, d.stop_loss, d.take_profit,
                                                        d.confidence, d.regime, "MEANREV add", order_type="auto")
                                self.last_trade_time[symbol] = now
                                logs.append(f"{symbol}: MEANREV ADD SHORT | qty={qty:.6f} | {tf_note} reg={d.regime}")

                continue  # done managing existing position

            # 2) If no position: consider entry
            if open_assets >= cfg.max_open_assets:
                continue

            if d.action == "HOLD":
                continue

            if d.confidence < cfg.conf_entry:
                continue

            # Entry side
            if d.action == "BUY":
                qty = self._compute_qty(symbol, price, d.stop_loss, cfg, equity)
                if qty > 0:
                    self.portfolio.open_leg(symbol, "long", qty, price, now, d.stop_loss, d.take_profit,
                                            d.confidence, d.regime, "ENTRY", order_type="auto")
                    self.last_trade_time[symbol] = now
                    open_assets += 1
                    logs.append(f"{symbol}: ENTRY LONG | qty={qty:.6f} conf={d.confidence:.2f} regime={d.regime} {tf_note}")
            elif d.action == "SELL" and cfg.allow_short:
                qty = self._compute_qty(symbol, price, d.stop_loss, cfg, equity)
                if qty > 0:
                    self.portfolio.open_leg(symbol, "short", qty, price, now, d.stop_loss, d.take_profit,
                                            d.confidence, d.regime, "ENTRY", order_type="auto")
                    self.last_trade_time[symbol] = now
                    open_assets += 1
                    logs.append(f"{symbol}: ENTRY SHORT | qty={qty:.6f} conf={d.confidence:.2f} regime={d.regime} {tf_note}")

        return logs
