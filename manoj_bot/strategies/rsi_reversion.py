from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
import pandas as pd

from manoj_bot.indicators import rsi, sma
from manoj_bot.strategies.base import Strategy, require_int


@dataclass
class RsiReversion(Strategy):
    """Mean reversion: buy when RSI falls below oversold, sell once it recovers above
    exit_level. With trend set, only buy while price is above that moving average."""

    name: ClassVar[str] = "rsi_reversion"

    period: int = 14
    oversold: float = 30.0
    exit_level: float = 55.0
    trend: int | None = None

    def __post_init__(self) -> None:
        require_int(self.period, "period", minimum=2)
        if self.trend is not None:
            require_int(self.trend, "trend", minimum=2)
        if not 0 < self.oversold < self.exit_level < 100:
            raise ValueError("Need 0 < oversold < exit_level < 100")

    @property
    def warmup(self) -> int:
        return max(self.period + 1, self.trend or 0)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        value = rsi(close, self.period)
        entries = value < self.oversold
        if self.trend:
            entries &= close > sma(close, self.trend)
        # Mark entries and exits, then hold the last state until the next event.
        state = (
            pd.Series(np.nan, index=data.index)
            .mask(entries, 1.0)
            .mask(value > self.exit_level, 0.0)
        )
        return state.ffill().fillna(0).astype(int)
