import json

import pandas as pd
import pytest

from manoj_bot.brokers import PaperBroker
from manoj_bot.config import BotConfig, CostConfig, RiskConfig
from manoj_bot.data import DataFeed
from manoj_bot.engine import BotState, TradingBot, save_state
from tests.helpers import ConstantStrategy, make_bars


class FakeFeed(DataFeed):
    def __init__(self, closes):
        self.set_prices(closes)

    def set_prices(self, closes):
        self.data = make_bars(closes, freq="1h")

    def history(self, symbol, timeframe, *, start=None, end=None, limit=None):
        return self.data.tail(limit) if limit else self.data


def make_bot(tmp_path, closes=(100,) * 10, value=1, capital=1000.0, **risk):
    settings = {
        "position_size": 1.0,
        "stop_loss": None,
        "max_drawdown": None,
        "min_trade_value": 10,
        **risk,
    }
    config = BotConfig(
        symbol="TEST",
        timeframe="1h",
        capital=capital,
        state_file=str(tmp_path / "state.json"),
        risk=RiskConfig(**settings),
        costs=CostConfig(fee_rate=0, slippage=0),
    )
    feed = FakeFeed(list(closes))

    def clock():
        # Half way through the newest bar, so that bar is still in progress.
        return feed.data.index[-1] + pd.Timedelta(minutes=30)

    strategy = ConstantStrategy(value)
    bot = TradingBot(config, strategy, feed, PaperBroker(config.costs, clock=clock), clock=clock)
    return bot, feed, strategy


def test_buys_holds_and_sells_on_signal(tmp_path):
    bot, feed, strategy = make_bot(tmp_path)
    assert bot.step() == "buy"
    assert bot.state.portfolio.quantity == pytest.approx(10)
    assert bot.step() == "hold"

    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["portfolio"]["quantity"] == pytest.approx(10)

    feed.set_prices([100] * 9 + [110])
    strategy.value = 0
    assert bot.step() == "sell:signal"
    [trade] = bot.state.trades
    assert trade.pnl == pytest.approx(100)
    assert bot.state.portfolio.cash == pytest.approx(1100)
    assert bot.step() == "flat"


def test_state_survives_a_restart(tmp_path):
    bot, _, _ = make_bot(tmp_path)
    bot.step()
    restarted, _, _ = make_bot(tmp_path)
    assert restarted.state == bot.state
    assert restarted.step() == "hold"


def test_only_closed_bars_reach_the_strategy(tmp_path):
    bot, _, strategy = make_bot(tmp_path, closes=[100] * 10)
    bot.step()
    assert strategy.bars_seen == 9


def test_waits_for_enough_data(tmp_path):
    bot, _, _ = make_bot(tmp_path, closes=[100] * 3)
    assert bot.step() == "warming-up"
    assert bot.state.portfolio.quantity == 0


def test_stop_loss_then_wait_for_a_fresh_signal(tmp_path):
    bot, feed, strategy = make_bot(tmp_path, stop_loss=0.05)
    assert bot.step() == "buy"
    feed.set_prices([100] * 9 + [94])
    assert bot.step() == "sell:stop_loss"
    assert bot.step() == "waiting-for-reset"
    strategy.value = 0
    assert bot.step() == "flat"
    strategy.value = 1
    assert bot.step() == "buy"


def test_take_profit(tmp_path):
    bot, feed, _ = make_bot(tmp_path, take_profit=0.1)
    bot.step()
    feed.set_prices([100] * 9 + [111])
    assert bot.step() == "sell:take_profit"


def test_drawdown_halts_trading(tmp_path):
    bot, feed, _ = make_bot(tmp_path, max_drawdown=0.2)
    bot.step()
    feed.set_prices([100] * 9 + [75])
    assert bot.step() == "sell:drawdown_halt"
    assert bot.step() == "halted"
    assert bot.state.halted


def test_skips_orders_below_the_minimum(tmp_path):
    bot, _, _ = make_bot(tmp_path, capital=5)
    assert bot.step() == "too-small"


def test_trades_with_no_minimum_order_value(tmp_path):
    bot, _, strategy = make_bot(tmp_path, min_trade_value=0, lot_size=1)
    strategy.value = 0
    assert bot.step() == "flat"
    strategy.value = 1
    assert bot.step() == "buy"
    assert bot.state.portfolio.quantity == 10
    strategy.value = 0
    assert bot.step() == "sell:signal"


def test_lot_size_larger_than_cash_is_too_small(tmp_path):
    bot, _, _ = make_bot(tmp_path, capital=50, min_trade_value=0, lot_size=1)
    assert bot.step() == "too-small"


def test_state_file_for_another_symbol_is_rejected(tmp_path):
    bot, _, _ = make_bot(tmp_path)
    other = BotState.new(bot.config)
    other.symbol = "OTHER"
    save_state(tmp_path / "state.json", other)
    with pytest.raises(ValueError, match="belongs to OTHER"):
        make_bot(tmp_path)


def test_run_keeps_going_after_errors(tmp_path):
    bot, _, _ = make_bot(tmp_path)
    sleeps = []
    bot._sleep = sleeps.append

    def broken(*args, **kwargs):
        raise ConnectionError("exchange down")

    bot.feed.history = broken
    bot.run(iterations=3)
    assert sleeps == [60.0, 60.0]
