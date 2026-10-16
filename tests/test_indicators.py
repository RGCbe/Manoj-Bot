import numpy as np
import pandas as pd
import pytest

from manoj_bot.indicators import ema, rsi, sma


def test_sma():
    values = sma(pd.Series([1.0, 2, 3, 4, 5]), 3)
    assert values.isna().sum() == 2
    assert values.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_ema_starts_after_span_and_tracks_prices():
    values = ema(pd.Series(np.arange(1.0, 21.0)), 5)
    assert values.iloc[:4].isna().all()
    assert values.iloc[-1] == pytest.approx(18.0, abs=0.5)


def test_rsi_extremes():
    rising = pd.Series(np.arange(1.0, 40.0))
    falling = rising[::-1].reset_index(drop=True)
    assert rsi(rising).iloc[-1] == pytest.approx(100.0)
    assert rsi(falling).iloc[-1] == pytest.approx(0.0)
    assert rsi(pd.Series([5.0] * 30)).iloc[-1] == pytest.approx(50.0)


def test_rsi_is_bounded_and_warms_up():
    prices = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.02, 500))))
    values = rsi(prices, 14)
    assert values.iloc[:14].isna().all()
    assert values.dropna().between(0, 100).all()
