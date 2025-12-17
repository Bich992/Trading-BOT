from __future__ import annotations

import datetime as dt
from typing import Dict, List

import pandas as pd

from core.engine import TradingEngine
from core.config import EngineConfig, load_config
from backtest.metrics import equity_curve_from_trades, sharpe_ratio, max_drawdown


def run_backtest(config: EngineConfig, historical: Dict[str, pd.DataFrame]):
    engine = TradingEngine(config)
    for symbol, df in historical.items():
        for _, row in df.iterrows():
            engine.state.last_prices[symbol] = float(row["Close"])
            # reuse strategy on the fly
            strat = engine.strategy_registry.get_active_strategy(symbol)
            signal = strat.generate_signal(df.loc[:row.name])
            signal.symbol = symbol
            price = float(row["Close"])
            qty = engine.risk.sizer.size_position(
                equity=engine.broker.portfolio.equity(engine.state.last_prices),
                price=price,
                stop_loss=signal.stop_loss,
            )
            if not engine.risk.check_limits(engine.state, symbol, qty):
                continue
            engine.broker.execute(signal, qty, price)

    trades = engine.broker.portfolio.trades
    curve = equity_curve_from_trades(trades, config.paper.starting_cash)
    ret = pd.Series(curve).pct_change().fillna(0)
    return {
        "equity_curve": curve,
        "sharpe": sharpe_ratio(ret),
        "max_drawdown": max_drawdown(curve),
        "trades": trades,
    }


if __name__ == "__main__":
    cfg = load_config()
    print("Backtest stub: provide historical data to run_backtest")
