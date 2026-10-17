import numpy as np
import pandas as pd
import pytest

from manoj_bot.data import SyntheticFeed
from manoj_bot.strategies import STRATEGIES, MaCrossover, RsiReversion, build_strategy
from tests.helpers import make_bars


@pytest.fixture(scope="module")
def market():
    return SyntheticFeed(seed=7).history("X", "1h", end="2024-06-01", limit=600)


@pytest.mark.parametrize(
    "strategy",
    [
        MaCrossover(fast=5, slow=20),
        MaCrossover(fast=5, slow=20, kind="ema"),
        RsiReversion(),
        RsiReversion(trend=50),
    ],
    ids=repr,
)
def test_signals_never_look_ahead(market, strategy):
    full = strategy.generate_signals(market)
    assert set(full.unique()) <= {0, 1}
    for end in range(strategy.warmup, len(market), 37):
        prefix = strategy.generate_signals(market.iloc[: end + 1])
        assert prefix.iloc[-1] == full.iloc[end], f"signal at bar {end} changed with future data"


def test_ma_crossover_goes_long_after_an_uptrend_starts():
    closes = np.r_[np.linspace(100, 80, 30), np.linspace(80, 120, 30)]
    signals = MaCrossover(fast=3, slow=10).generate_signals(make_bars(closes))
    assert signals.iloc[:30].eq(0).all()
    assert signals.iloc[-1] == 1


def test_rsi_reversion_buys_the_dip_and_exits_on_recovery():
    closes = np.r_[np.full(20, 100.0), np.linspace(100, 70, 10), np.linspace(70, 100, 15)]
    signals = RsiReversion(period=5, oversold=30, exit_level=60).generate_signals(make_bars(closes))
    assert signals.iloc[:20].eq(0).all()
    assert signals.iloc[20:30].eq(1).any()
    assert signals.iloc[-1] == 0


def test_build_strategy():
    assert build_strategy("ma_crossover", {"fast": 3, "slow": 9}) == MaCrossover(fast=3, slow=9)
    assert set(STRATEGIES) == {"ma_crossover", "rsi_reversion"}


@pytest.mark.parametrize(
    ("name", "params", "message"),
    [
        ("nope", {}, "Unknown strategy"),
        ("ma_crossover", {"speed": 3}, "Unknown parameter"),
        ("ma_crossover", {"fast": 50, "slow": 20}, "smaller than slow"),
        ("ma_crossover", {"kind": "wma"}, "kind"),
        ("ma_crossover", {"fast": 2.5}, "integer"),
        ("rsi_reversion", {"oversold": 70, "exit_level": 50}, "oversold < exit_level"),
    ],
)
def test_build_strategy_rejects_bad_input(name, params, message):
    with pytest.raises(ValueError, match=message):
        build_strategy(name, params)


def test_signals_are_aligned_with_the_data(market):
    signals = RsiReversion().generate_signals(market)
    assert isinstance(signals, pd.Series)
    assert signals.index.equals(market.index)
