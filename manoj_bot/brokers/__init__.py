"""Order execution: simulated (paper) or real (ccxt exchanges)."""

from manoj_bot.brokers.base import Broker
from manoj_bot.brokers.paper import PaperBroker, simulate_fill

__all__ = ["Broker", "PaperBroker", "simulate_fill"]
