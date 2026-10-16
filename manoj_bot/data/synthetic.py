from __future__ import annotations

import numpy as np
import pandas as pd

from manoj_bot.data.base import OHLC, DataFeed
from manoj_bot.timeframes import parse_timeframe, to_utc


class SyntheticFeed(DataFeed):
    """Random-walk prices with trending regimes, for offline demos and tests.

    The prices are made up. For the same seed and number of bars they are always the same.
    """

    def __init__(
        self,
        seed: int = 42,
        start_price: float = 100.0,
        drift: float = 0.0,
        volatility: float = 0.01,
        regime_length: int = 200,
    ):
        self.seed = seed
        self.start_price = start_price
        self.drift = drift
        self.volatility = volatility
        self.regime_length = regime_length

    def history(self, symbol, timeframe, *, start=None, end=None, limit=None) -> pd.DataFrame:
        step = parse_timeframe(timeframe)
        last = (to_utc(end) if end is not None else pd.Timestamp.now(tz="UTC")).floor(step)
        count = limit or 1000
        if start is not None:
            span = int((last - to_utc(start)) / step) + 1
            count = min(span, limit) if limit else span
        if count <= 0:
            return pd.DataFrame(columns=[*OHLC, "volume"], dtype=float)
        index = pd.date_range(end=last, periods=count, freq=step, name="timestamp")
        return self._generate(index)

    def _generate(self, index: pd.DatetimeIndex) -> pd.DataFrame:
        n, vol = len(index), self.volatility
        rng = np.random.default_rng(self.seed)
        regimes = -(-n // self.regime_length)
        drift = np.repeat(rng.normal(self.drift, vol / 5, regimes), self.regime_length)[:n]
        close = self.start_price * np.exp(
            np.cumsum(drift - 0.5 * vol**2 + vol * rng.standard_normal(n))
        )
        open_ = np.r_[self.start_price, close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
        volume = rng.lognormal(10, 0.5, n)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=index,
        )
