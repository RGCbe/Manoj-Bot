from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from manoj_bot._ccxt import create_exchange
from manoj_bot.brokers.base import Broker
from manoj_bot.portfolio import Fill

log = logging.getLogger(__name__)


class CcxtBroker(Broker):
    """Real market orders on a crypto exchange through ccxt (spot, long only)."""

    def __init__(
        self,
        exchange_id: str,
        *,
        api_key: str | None = None,
        secret: str | None = None,
        password: str | None = None,
        sandbox: bool = True,
        exchange: Any = None,
    ):
        if exchange is None:
            exchange = create_exchange(
                exchange_id, {"apiKey": api_key, "secret": secret, "password": password}
            )
            if sandbox:
                exchange.set_sandbox_mode(True)
        self.exchange = exchange
        self.exchange.load_markets()

    def buy(self, symbol: str, quantity: float, price: float) -> Fill:
        return self._market_order(symbol, "buy", quantity)

    def sell(self, symbol: str, quantity: float, price: float) -> Fill:
        return self._market_order(symbol, "sell", quantity)

    def _market_order(self, symbol: str, side: str, quantity: float) -> Fill:
        market = self.exchange.market(symbol)
        amount = float(self.exchange.amount_to_precision(symbol, quantity))
        if amount <= 0:
            raise ValueError(f"Order size {quantity} rounds to zero on {symbol}")
        order = self.exchange.create_order(symbol, "market", side, amount)
        if not order.get("filled") or not order.get("average"):
            # Some exchanges only acknowledge the order; ask again for the fill details.
            order = self.exchange.fetch_order(order["id"], symbol)

        filled = float(order.get("filled") or 0)
        price = float(order.get("average") or order.get("price") or 0)
        if filled <= 0 or price <= 0:
            raise RuntimeError(
                f"Order {order.get('id')} was not filled (status {order.get('status')})"
            )

        fee = 0.0
        for item in order.get("fees") or ([order["fee"]] if order.get("fee") else []):
            cost = float(item.get("cost") or 0)
            if not cost:
                continue
            if item.get("currency") == market["quote"]:
                fee += cost
            elif item.get("currency") == market["base"]:
                # Fee paid in the asset itself: we received less of it. Count it in quote terms
                # so the cash bookkeeping still matches what was spent.
                fee += cost * price
                if side == "buy":
                    filled -= cost
            else:
                log.warning(
                    "Fee of %s %s on order %s is not tracked",
                    cost,
                    item.get("currency"),
                    order.get("id"),
                )
        timestamp = order.get("datetime") or pd.Timestamp.now(tz="UTC").isoformat()
        return Fill(side, filled, price, fee, timestamp)
