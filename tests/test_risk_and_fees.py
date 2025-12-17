import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from execution.fees import FeeModel
from risk.position_sizing import PositionSizer, SizeConfig
from backtest.metrics import equity_curve_from_trades, max_drawdown
from core.paper_engine import Trade


def test_position_sizer_fixed():
    sizer = PositionSizer(SizeConfig(fixed_notional=100, risk_per_trade_pct=0.01))
    qty = sizer.size_position(equity=1000, price=10, stop_loss=None)
    assert abs(qty - 10) < 1e-6


def test_position_sizer_risk_based():
    sizer = PositionSizer(SizeConfig(fixed_notional=100, risk_per_trade_pct=0.02))
    qty = sizer.size_position(equity=2000, price=20, stop_loss=19)
    # risk = 40, stop_dist=1 -> qty=40
    assert abs(qty - 40) < 1e-6


def test_fee_model_slippage_and_fee():
    fm = FeeModel(maker_fee=0.001, taker_fee=0.002, slippage_bps=10)
    price = fm.apply_slippage(100, "buy")
    assert price > 100
    fee = fm.fee(1000)
    assert abs(fee - 2) < 1e-9


def test_equity_and_drawdown():
    trades = [
        Trade(ts=dt.datetime.utcnow(), symbol="A", side="buy", qty=1, price=10, fee=0, pnl_realized=10),
        Trade(ts=dt.datetime.utcnow(), symbol="A", side="sell", qty=1, price=12, fee=0, pnl_realized=-5),
    ]
    curve = equity_curve_from_trades(trades, starting_cash=100)
    assert curve[-1] == 105
    dd = max_drawdown(curve)
    assert dd >= 0
