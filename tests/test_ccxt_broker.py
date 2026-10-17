import math

import pytest

from manoj_bot.brokers.ccxt_broker import CcxtBroker


class FakeExchange:
    def __init__(self, order, fetched=None):
        self.order, self.fetched, self.orders = order, fetched, []

    def load_markets(self):
        pass

    def market(self, symbol):
        return {"base": "BTC", "quote": "USDT"}

    def amount_to_precision(self, symbol, amount):
        return f"{math.floor(amount * 1000) / 1000:.3f}"

    def create_order(self, symbol, order_type, side, amount):
        self.orders.append((symbol, order_type, side, amount))
        return self.order

    def fetch_order(self, order_id, symbol):
        return self.fetched


def broker(order, fetched=None):
    return CcxtBroker("fake", exchange=FakeExchange(order, fetched))


def test_market_buy_with_fee_in_quote_currency():
    order = {
        "id": "1",
        "filled": 0.5,
        "average": 100.0,
        "datetime": "2024-01-01T00:00:00Z",
        "fee": {"cost": 0.05, "currency": "USDT"},
    }
    b = broker(order)
    fill = b.buy("BTC/USDT", 0.5004, 100.0)
    assert b.exchange.orders == [("BTC/USDT", "market", "buy", 0.5)]
    assert (fill.side, fill.quantity, fill.price, fill.fee) == ("buy", 0.5, 100.0, 0.05)
    assert fill.timestamp == "2024-01-01T00:00:00Z"


def test_fee_paid_in_the_bought_asset_reduces_the_quantity():
    order = {
        "id": "1",
        "filled": 0.5,
        "average": 100.0,
        "fees": [{"cost": 0.001, "currency": "BTC"}],
    }
    fill = broker(order).buy("BTC/USDT", 0.5, 100.0)
    assert fill.quantity == pytest.approx(0.499)
    # Cash spent is unchanged: 0.499 * 100 + 0.1 == 0.5 * 100.
    assert fill.fee == pytest.approx(0.1)


def test_order_details_are_fetched_when_missing():
    fetched = {"id": "1", "filled": 0.2, "average": 101.0, "status": "closed"}
    fill = broker({"id": "1", "status": "open"}, fetched).sell("BTC/USDT", 0.2, 100.0)
    assert (fill.side, fill.quantity, fill.price, fill.fee) == ("sell", 0.2, 101.0, 0.0)


def test_rejects_tiny_and_unfilled_orders():
    with pytest.raises(ValueError, match="rounds to zero"):
        broker({}).buy("BTC/USDT", 0.0001, 100.0)
    unfilled = {"id": "1", "status": "canceled", "filled": 0}
    with pytest.raises(RuntimeError, match="not filled"):
        broker(unfilled, unfilled).buy("BTC/USDT", 1, 100.0)
