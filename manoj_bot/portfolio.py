"""Cash and position bookkeeping shared by the backtester and the live engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Fill:
    side: str  # "buy" or "sell"
    quantity: float  # units of the base asset
    price: float  # average fill price
    fee: float  # commission, in quote currency
    timestamp: str  # ISO-8601


@dataclass
class Trade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float  # net of fees on both sides
    return_pct: float  # pnl relative to the cash spent on entry
    exit_reason: str


@dataclass
class Portfolio:
    """A single long position plus the cash the bot is allowed to use."""

    cash: float
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_cost: float = 0.0  # cash spent on the open position, fees included
    entry_time: str | None = None

    def equity(self, price: float) -> float:
        return self.cash + self.quantity * price

    def apply_buy(self, fill: Fill) -> None:
        cost = fill.quantity * fill.price + fill.fee
        total = self.quantity + fill.quantity
        self.entry_price = (self.entry_price * self.quantity + fill.price * fill.quantity) / total
        self.quantity = total
        self.entry_cost += cost
        self.cash -= cost
        if self.entry_time is None:
            self.entry_time = fill.timestamp

    def apply_sell(self, fill: Fill, reason: str) -> Trade:
        if self.quantity <= 0:
            raise ValueError("There is no open position to sell")
        sold = min(fill.quantity, self.quantity)
        cost_basis = self.entry_cost * sold / self.quantity
        proceeds = sold * fill.price - fill.fee
        trade = Trade(
            entry_time=self.entry_time or fill.timestamp,
            exit_time=fill.timestamp,
            entry_price=self.entry_price,
            exit_price=fill.price,
            quantity=sold,
            pnl=proceeds - cost_basis,
            return_pct=(proceeds - cost_basis) / cost_basis if cost_basis else 0.0,
            exit_reason=reason,
        )
        self.cash += proceeds
        self.quantity -= sold
        self.entry_cost -= cost_basis
        if self.quantity <= 1e-12:
            self.quantity = self.entry_price = self.entry_cost = 0.0
            self.entry_time = None
        return trade
