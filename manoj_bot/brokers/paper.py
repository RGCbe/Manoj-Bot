from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from manoj_bot.brokers.base import Broker
from manoj_bot.config import CostConfig
from manoj_bot.portfolio import Fill


def simulate_fill(
    side: str, quantity: float, price: float, costs: CostConfig, timestamp: str
) -> Fill:
    """Fill at ``price`` moved against us by the slippage, and charge the fee."""
    direction = 1 if side == "buy" else -1
    fill_price = float(price) * (1 + direction * costs.slippage)
    fee = float(quantity) * fill_price * costs.fee_rate
    return Fill(side, float(quantity), fill_price, fee, timestamp)


class PaperBroker(Broker):
    """Simulated orders: nothing is sent to an exchange."""

    def __init__(self, costs: CostConfig, clock: Callable[[], pd.Timestamp] | None = None):
        self.costs = costs
        self._clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))

    def buy(self, symbol: str, quantity: float, price: float) -> Fill:
        return simulate_fill("buy", quantity, price, self.costs, self._clock().isoformat())

    def sell(self, symbol: str, quantity: float, price: float) -> Fill:
        return simulate_fill("sell", quantity, price, self.costs, self._clock().isoformat())
