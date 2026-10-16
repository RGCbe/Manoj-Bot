from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
import pandas as pd

from manoj_bot.strategies import Strategy


def make_bars(closes, start="2024-01-01", freq="1D", opens=None, highs=None, lows=None):
    """Bars whose open is the previous close unless given explicitly."""
    closes = np.asarray(closes, dtype=float)
    opens = np.r_[closes[0], closes[:-1]] if opens is None else np.asarray(opens, dtype=float)
    highs = np.maximum(opens, closes) if highs is None else np.asarray(highs, dtype=float)
    lows = np.minimum(opens, closes) if lows is None else np.asarray(lows, dtype=float)
    index = pd.date_range(start, periods=len(closes), freq=freq, tz="UTC", name="timestamp")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1.0}, index=index
    )


@dataclass
class ScriptedStrategy(Strategy):
    """Emits the given signals bar by bar (0 after the script runs out)."""

    name: ClassVar[str] = "scripted"
    signals: list[int] = field(default_factory=list)

    @property
    def warmup(self) -> int:
        return 1

    def generate_signals(self, data):
        values = (list(self.signals) + [0] * len(data))[: len(data)]
        return pd.Series(values, index=data.index, dtype=int)


@dataclass
class ConstantStrategy(Strategy):
    """Always emits ``value``; tests change it between steps."""

    name: ClassVar[str] = "constant"
    value: int = 1
    bars_seen: int = 0

    @property
    def warmup(self) -> int:
        return 3

    def generate_signals(self, data):
        self.bars_seen = len(data)
        return pd.Series(self.value, index=data.index, dtype=int)
