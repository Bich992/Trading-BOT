from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Dict, Iterable, List, Optional

import pandas as pd

from core.config import EngineConfig
from core.state import EngineState
from data.feed import DataFeed
from execution.broker import PaperBroker
from risk.limits import RiskManager
from strategies.registry import StrategyRegistry
from backtest.metrics import equity_curve_from_trades

logger = logging.getLogger(__name__)


class TradingEngine:
    """Event-driven engine inspired by Freqtrade/Hummingbot patterns."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.feed = DataFeed(config)
        self.strategy_registry = StrategyRegistry()
        self.broker = PaperBroker(config.paper)
        self.risk = RiskManager(config.risk)
        self.state = EngineState(self.broker.portfolio, [], {})

    async def run_step(self):
        # 1) fetch data for all assets/timeframes
        ohlc_by_symbol: Dict[str, pd.DataFrame] = {}
        for asset in self.config.assets:
            df = await self.feed.latest_ohlc(asset.symbol, asset.timeframes[0])
            if df is not None:
                ohlc_by_symbol[asset.symbol] = df
                self.state.last_prices[asset.symbol] = float(df["Close"].iloc[-1])

        # 2) strategy signals
        actions: List[str] = []
        for asset in self.config.assets:
            df = ohlc_by_symbol.get(asset.symbol)
            if df is None or len(df) < 50:
                continue
            strat = self.strategy_registry.get_active_strategy(asset.symbol)
            signal = strat.generate_signal(df)
            signal.symbol = asset.symbol
            signal.timeframe = asset.timeframes[0]
            qty = self.risk.sizer.size_position(
                equity=self.broker.portfolio.equity(self.state.last_prices),
                price=float(df["Close"].iloc[-1]),
                stop_loss=signal.stop_loss,
            )
            # 3) risk checks
            if not self.risk.check_limits(self.state, asset.symbol, qty):
                actions.append(f"{asset.symbol}: blocked by risk limits")
                continue
            # 4) paper execution
            fill = self.broker.execute(signal, qty, float(df["Close"].iloc[-1]))
            if fill:
                actions.append(f"{asset.symbol}: {signal.action} qty={qty:.6f} price={fill.price:.4f}")

        return actions

    async def run_loop(self, iterations: Optional[int] = None, sleep_s: int = 5):
        i = 0
        while iterations is None or i < iterations:
            actions = await self.run_step()
            for a in actions:
                logger.info(a)
            await asyncio.sleep(sleep_s)
            i += 1

    def recap(self) -> Dict[str, float]:
        trades = self.broker.portfolio.trades
        equity = equity_curve_from_trades(trades, self.broker.portfolio.cash)
        return {
            "trades": len(trades),
            "fees": self.broker.portfolio.total_fees(),
            "realized": self.broker.portfolio.realized_pnl(),
            "equity": equity[-1] if equity else self.broker.portfolio.cash,
        }
