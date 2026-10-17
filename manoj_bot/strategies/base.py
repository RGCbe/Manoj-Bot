from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import pandas as pd


class Strategy(ABC):
    """Turns OHLCV bars into a target position for every bar: 1 = long, 0 = flat.

    The value for a bar may only depend on that bar and earlier ones. It is acted on at
    the next bar's open in backtests, and as soon as the bar closes when trading.
    """

    name: ClassVar[str]

    @property
    @abstractmethod
    def warmup(self) -> int:
        """Number of bars needed before the signal is meaningful."""

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return an int Series aligned with ``data.index``."""


def require_int(value, name: str, minimum: int = 1) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
