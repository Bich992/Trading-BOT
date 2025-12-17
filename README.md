# Trading-BOT (production-grade foundation)

Opinionated refactor inspired by Freqtrade/Hummingbot/Backtrader patterns. Focused on paper-first safety with risk controls, recap, and tuning hooks.

## Requirements
- Python 3.11
- Poetry/pip supported; on Windows use `python -m venv .venv` then activate.
- Dependencies: `pip install -r requirements.txt` (Qt UI needs a display).

## Setup
1. Copy `.env.example` to `.env` and fill exchange credentials only when running live (not required for paper/backtest).
2. Copy `config.example.yaml` to `config.yaml` and adjust assets, risk, and paper settings.
3. Ensure `.venv/` and `.env` are not committed (already in `.gitignore`).

### Windows notes
- Use `python -m pip install -r requirements.txt`.
- If running the Qt desktop UI, install platform Qt dependencies. Start via `python desktop_app.py` from an activated venv.

## Running paper mode
- Default engine is paper-only; live requires `enable_live: true` in config (keep false for safety).
- Launch the desktop UI: `python desktop_app.py`.
- Or run the headless engine loop:
  ```bash
  python - <<'PY'
  import asyncio
  from core.config import load_config
  from core.engine import TradingEngine

  cfg = load_config()
  engine = TradingEngine(cfg)
  asyncio.run(engine.run_loop(iterations=2, sleep_s=5))
  print(engine.recap())
  PY
  ```

### Desktop UI overview
- **Theme**: dark, high-contrast dashboard with status top bar, navigation sidebar, and split panels for charts, controls, and analytics.
- **Top bar**: mode (PAPER/LIVE), bot state (learning/trading), active timeframes, equity and drawdown gauges, and alert badge.
- **Navigation**: sidebar sections for Dashboard, Markets, Strategies, Risk Control, Trades, Analytics, Recap & Reports, and Settings.
- **Main panel**: TradingView-style chart (candles + EMA/RSI/MACD overlays) with zoom/pan, live timeframe selector, and configurable AUTO multi-asset controls.
- **Right analytics**: bot thoughts, trade history, and recap performance widget.
- **Bottom tape**: structured bot log and trade tape for quick scanning without blocking the main view.
- **Shortcuts**: scroll to zoom charts, drag to pan via toolbar, and use the timeframe combo box for quick switching.
- **Screenshot placeholder**: add updated UI captures to `docs/ui_dashboard_dark.png` once available.

## Backtest
Provide historical data frames and call `backtest.runner.run_backtest`.
Example stub:
```python
from backtest.runner import run_backtest
from core.config import load_config
import yfinance as yf

cfg = load_config()
data = {"BTC/USDT": yf.download("BTC-USD", period="1mo", interval="1h")}
print(run_backtest(cfg, data))
```

## Recap generation
- Paper trades are written inside the in-memory `PaperPortfolio` with fees/slippage/latency.
- Generate a recap HTML: use `reports.recap.generate_recap(trades, starting_cash, Path('reports'))`.
- Output file is `reports/recap_YYYYMMDD_HHMMSS.html` and includes fee/slippage-aware PnL and risk metrics.

## Live safety
- Live trading is disabled unless `enable_live: true` in config. Keep paper mode for testing.
- Checklist before setting live:
  - `.env` contains API keys.
  - `enable_live: true` explicitly set.
  - Risk limits in config are non-zero.
  - Run `pytest` to validate sizing/fees/metrics.

## Auto tuning hooks
- Config `tuning` block enables storage of best parameters at `reports/best_params.json` (walk-forward ready).
- Strategies can load/swap params via `strategies.registry` and `ExampleStrategy` shows the pattern.

## Quick files map
- `core/engine.py`: event loop orchestrating data → signal → risk → execution.
- `core/config.py`: validated settings (paper, risk, tuning, assets).
- `core/state.py`: positions/exposure snapshot helpers.
- `data/feed.py`: CCXT OHLCV fetcher.
- `execution/broker.py`: paper broker with slippage/fee model.
- `risk/position_sizing.py`, `risk/limits.py`: sizing + limit guards.
- `backtest/runner.py` / `backtest/metrics.py`: simulation metrics.
- `reports/recap.py`: fee/slippage-aware recap export.
- `strategies/example_strategy.py`: baseline EMA/RSI strategy API.
