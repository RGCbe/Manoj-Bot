import dataclasses

import pandas as pd
import pytest

from manoj_bot.backtest import run_backtest
from manoj_bot.config import CostConfig, RiskConfig
from manoj_bot.data import SyntheticFeed
from manoj_bot.metrics import compute_metrics
from manoj_bot.strategies import MaCrossover
from tests.helpers import ScriptedStrategy, make_bars


def test_no_signal_means_no_trades(plain_risk, no_costs):
    result = run_backtest(
        make_bars([10, 12, 9, 11]), ScriptedStrategy([]), plain_risk, no_costs, 1000
    )
    assert result.trades == []
    assert result.equity.tolist() == [1000] * 4
    assert result.metrics["total_return"] == 0


def test_signal_is_executed_at_the_next_open(plain_risk, no_costs):
    data = make_bars([10, 11, 12, 13, 14, 15])  # each open is the previous close
    result = run_backtest(data, ScriptedStrategy([0, 1, 1, 0]), plain_risk, no_costs, 1000)
    [trade] = result.trades
    assert (trade.entry_price, trade.exit_price) == (11, 13)
    assert pd.Timestamp(trade.entry_time) == data.index[2]
    assert pd.Timestamp(trade.exit_time) == data.index[4]
    assert trade.exit_reason == "signal"
    assert result.metrics["final_equity"] == pytest.approx(1000 / 11 * 13)
    assert result.equity.iloc[-1] == pytest.approx(1000 / 11 * 13)


def test_stop_loss_inside_a_bar_then_waits_for_a_fresh_signal(plain_risk, no_costs):
    risk = dataclasses.replace(plain_risk, stop_loss=0.05)
    data = make_bars([100] * 8, lows=[100, 100, 90, 100, 100, 100, 100, 100])
    signals = [1, 1, 1, 1, 0, 1, 1, 1]
    result = run_backtest(data, ScriptedStrategy(signals), risk, no_costs, 1000)
    first, second = result.trades
    assert (first.exit_reason, first.exit_price) == ("stop_loss", pytest.approx(95))
    assert pd.Timestamp(first.exit_time) == data.index[2]
    # Signal stayed 1 after the stop, so no re-entry until it went 0 (bar 4) and back to 1.
    assert pd.Timestamp(second.entry_time) == data.index[6]
    assert second.exit_reason == "end_of_data"


def test_gap_below_the_stop_exits_at_the_open(plain_risk, no_costs):
    risk = dataclasses.replace(plain_risk, stop_loss=0.05)
    data = make_bars([100, 100, 100, 80, 80], opens=[100, 100, 100, 85, 80])
    result = run_backtest(data, ScriptedStrategy([1] * 5), risk, no_costs, 1000)
    assert (result.trades[0].exit_reason, result.trades[0].exit_price) == ("stop_loss", 85)


def test_take_profit(plain_risk, no_costs):
    risk = dataclasses.replace(plain_risk, take_profit=0.10)
    data = make_bars([100, 100, 105, 105], highs=[100, 100, 115, 105])
    result = run_backtest(data, ScriptedStrategy([1] * 4), risk, no_costs, 1000)
    assert (result.trades[0].exit_reason, result.trades[0].exit_price) == (
        "take_profit",
        pytest.approx(110),
    )


def test_fees_and_slippage_are_charged(plain_risk):
    costs = CostConfig(fee_rate=0.001, slippage=0.001)
    result = run_backtest(
        make_bars([100] * 4), ScriptedStrategy([1, 1, 0]), plain_risk, costs, 1000
    )
    [trade] = result.trades
    assert trade.entry_price == pytest.approx(100.1)
    assert trade.exit_price == pytest.approx(99.9)
    assert trade.pnl < 0
    assert result.metrics["fees"] == pytest.approx(2.0, rel=0.01)
    assert result.metrics["final_equity"] == pytest.approx(1000 + trade.pnl)


def test_drawdown_halt_stops_trading(plain_risk, no_costs):
    risk = dataclasses.replace(plain_risk, max_drawdown=0.2)
    data = make_bars([100, 100, 90, 75, 70, 100, 120])
    result = run_backtest(data, ScriptedStrategy([1] * 7), risk, no_costs, 1000)
    [trade] = result.trades
    assert (trade.exit_reason, trade.exit_price) == ("drawdown_halt", 75)
    assert result.metrics["final_equity"] == pytest.approx(750)


def test_whole_shares_only(plain_risk, no_costs):
    risk = dataclasses.replace(plain_risk, lot_size=1)
    result = run_backtest(make_bars([300] * 3), ScriptedStrategy([1] * 3), risk, no_costs, 1000)
    assert result.trades[0].quantity == 3
    # A share costs more than the cash: nothing to buy.
    result = run_backtest(make_bars([1500] * 3), ScriptedStrategy([1] * 3), risk, no_costs, 1000)
    assert result.trades == []


def test_metrics():
    index = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    equity = pd.Series([100.0, 120, 90, 130], index=index)
    prices = pd.Series([10.0, 11, 12, 15], index=index)
    metrics = compute_metrics(equity, [], prices, capital=100, exposure=0.5, fees=1.0)
    assert metrics["max_drawdown"] == pytest.approx(-0.25)
    assert metrics["total_return"] == pytest.approx(0.30)
    assert metrics["buy_and_hold_return"] == pytest.approx(0.5)
    assert metrics["trades"] == 0
    assert metrics["sharpe"] > 0


def test_full_run_on_synthetic_data():
    data = SyntheticFeed(seed=3).history("X", "1h", end="2024-06-01", limit=1500)
    result = run_backtest(data, MaCrossover(), RiskConfig(), CostConfig(), 1000)
    assert len(result.equity) == len(data)
    assert result.metrics["trades"] == len(result.trades) > 0
    assert result.metrics["final_equity"] == pytest.approx(result.equity.iloc[-1])
    assert result.metrics["max_drawdown"] <= 0
    assert 0 < result.metrics["exposure"] < 1
    frame = result.trades_frame()
    assert list(frame.columns)[:2] == ["entry_time", "exit_time"]
    assert frame["pnl"].sum() == pytest.approx(result.metrics["final_equity"] - 1000)
    assert "Total return" in result.summary()
