"""Trading strategies. Add a new one by subclassing Strategy and registering it below."""

from __future__ import annotations

import dataclasses
from typing import Any

from manoj_bot.strategies.base import Strategy
from manoj_bot.strategies.ma_crossover import MaCrossover
from manoj_bot.strategies.rsi_reversion import RsiReversion

STRATEGIES: dict[str, type[Strategy]] = {cls.name: cls for cls in (MaCrossover, RsiReversion)}


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    cls = STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy {name!r}. Available: {', '.join(STRATEGIES)}")
    params = params or {}
    allowed = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(
            f"Unknown parameter(s) for {name}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )
    return cls(**params)


__all__ = ["STRATEGIES", "MaCrossover", "RsiReversion", "Strategy", "build_strategy"]
