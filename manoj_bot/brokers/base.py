from __future__ import annotations

from abc import ABC, abstractmethod

from manoj_bot.portfolio import Fill


class Broker(ABC):
    """Places market orders. ``price`` is the latest known price, used by simulated brokers."""

    @abstractmethod
    def buy(self, symbol: str, quantity: float, price: float) -> Fill: ...

    @abstractmethod
    def sell(self, symbol: str, quantity: float, price: float) -> Fill: ...
