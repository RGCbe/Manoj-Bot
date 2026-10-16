from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from manoj_bot.indicators import ema, sma
from manoj_bot.strategies.base import Strategy, require_int


@dataclass
class MaCrossover(Strategy):
    """Trend following: long while the fast moving average is above the slow one."""

    name: ClassVar[str] = "ma_crossover"

    fast: int = 20
    slow: int = 50
    kind: str = "sma"  # "sma" or "ema"

    def __post_init__(self) -> None:
        require_int(self.fast, "fast")
        require_int(self.slow, "slow")
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be smaller than slow ({self.slow})")
        if self.kind not in ("sma", "ema"):
            raise ValueError(f"kind must be 'sma' or 'ema', got {self.kind!r}")

    @property
    def warmup(self) -> int:
        return self.slow

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        average = sma if self.kind == "sma" else ema
        close = data["close"]
        return (average(close, self.fast) > average(close, self.slow)).astype(int)
