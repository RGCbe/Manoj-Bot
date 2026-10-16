import pytest

from manoj_bot.brokers import PaperBroker, simulate_fill
from manoj_bot.config import CostConfig, RiskConfig
from manoj_bot.portfolio import Fill, Portfolio
from manoj_bot.risk import drawdown_breached, exit_levels, position_quantity


def test_position_size_leaves_room_for_costs():
    costs = CostConfig(fee_rate=0.001, slippage=0.001)
    quantity = position_quantity(1000, 1000, 10.0, RiskConfig(position_size=0.5), costs)
    fill = simulate_fill("buy", quantity, 10.0, costs, "t")
    assert fill.quantity * fill.price + fill.fee == pytest.approx(500)


def test_risk_per_trade_caps_the_position(no_costs):
    risk = RiskConfig(position_size=1.0, risk_per_trade=0.01, stop_loss=0.05)
    # Losing 5% on a 200 position costs 10 = 1% of 1000.
    assert position_quantity(1000, 1000, 2.0, risk, no_costs) == pytest.approx(100)


def test_position_size_is_limited_by_cash_and_lot_size(no_costs):
    risk = RiskConfig(position_size=1.0)
    assert position_quantity(300, 1000, 10.0, risk, no_costs) == pytest.approx(30)
    assert position_quantity(1000, 1000, 0.0, risk, no_costs) == 0
    whole = RiskConfig(position_size=1.0, lot_size=1)
    assert position_quantity(1000, 1000, 300.0, whole, no_costs) == 3
    lots = RiskConfig(position_size=1.0, lot_size=0.001)
    assert position_quantity(3, 3, 1.0, lots, no_costs) == pytest.approx(3.0)


def test_exit_levels_and_drawdown():
    assert exit_levels(100, RiskConfig(stop_loss=0.05, take_profit=0.1)) == pytest.approx((95, 110))
    assert exit_levels(100, RiskConfig(stop_loss=None, take_profit=None)) == (None, None)
    risk = RiskConfig(max_drawdown=0.2)
    assert not drawdown_breached(81, 100, risk)
    assert drawdown_breached(80, 100, risk)
    assert not drawdown_breached(1, 100, RiskConfig(max_drawdown=None))


def test_fills_move_against_us_and_pay_fees():
    costs = CostConfig(fee_rate=0.01, slippage=0.02)
    buy = PaperBroker(costs).buy("X", 2, 100)
    sell = PaperBroker(costs).sell("X", 2, 100)
    assert (buy.price, buy.fee) == pytest.approx((102, 2.04))
    assert (sell.price, sell.fee) == pytest.approx((98, 1.96))


def test_round_trip_bookkeeping():
    portfolio = Portfolio(cash=1000)
    portfolio.apply_buy(Fill("buy", 10, 50, 1.0, "t0"))
    assert portfolio.cash == pytest.approx(499)
    assert portfolio.equity(60) == pytest.approx(1099)

    trade = portfolio.apply_sell(Fill("sell", 10, 60, 1.0, "t1"), "signal")
    assert trade.pnl == pytest.approx(98)
    assert trade.return_pct == pytest.approx(98 / 501)
    assert (trade.entry_time, trade.exit_time) == ("t0", "t1")
    assert portfolio == Portfolio(cash=1098)


def test_partial_sell_keeps_the_rest_of_the_position():
    portfolio = Portfolio(cash=1000)
    portfolio.apply_buy(Fill("buy", 10, 50, 0.0, "t0"))
    trade = portfolio.apply_sell(Fill("sell", 4, 55, 0.0, "t1"), "signal")
    assert trade.pnl == pytest.approx(20)
    assert portfolio.quantity == pytest.approx(6)
    assert portfolio.entry_cost == pytest.approx(300)
    with pytest.raises(ValueError):
        Portfolio(cash=1).apply_sell(Fill("sell", 1, 1, 0, "t"), "signal")
