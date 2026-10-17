"""Lot sizing for XAUUSD-style CFDs, and an account replay of weak-zone trades.

One lot is ``contract_size`` ounces (100 for XAUUSD), so a one-point move is worth
``contract_size`` in the account currency per lot. The account is assumed to be in the
quote currency (USD for XAUUSD).

Each trade risks ``risk`` of the balance at the time, so lots grow with the account
(compounding, 3% by default): lots = balance x risk / (stop distance x contract size),
rounded down to ``lot_step`` so the real risk never exceeds it.
When even ``min_lot`` would risk more, the trade is skipped.

A trade that scales out in thirds is split into three parts in whole lot steps, the
first parts taking any remainder: 0.02 lots close as 0.01 at 1R and 0.01 at 2R.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from manoj_bot.zone_trades import TARGETS, ZoneTrade

# The R each third of the position exits at, by outcome (thirds at 1R, 2R, 3R; 1R trail).
LEG_R = {
    "loss": (-1.0, -1.0, -1.0),
    "partial": (1.0, -1.0, -1.0),
    "trailed": (1.0, 2.0, 1.0),
    "win": (1.0, 2.0, 3.0),
}


@dataclass(frozen=True)
class LotRules:
    risk: float = 0.03  # share of the balance lost if the stop is hit (0.03 = 3%)
    contract_size: float = 100.0  # ounces per lot
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float | None = None
    commission_per_lot: float = 0.0  # round trip, in the account currency
    leverage: float | None = None  # e.g. 500 for 1:500; caps lots by the margin available

    def __post_init__(self) -> None:
        if not 0 < self.risk < 1:
            raise ValueError("risk must be between 0 and 1 (0.02 = 2%)")
        for name in ("contract_size", "min_lot", "lot_step"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.commission_per_lot < 0:
            raise ValueError("commission_per_lot must be >= 0")
        for name in ("max_lot", "leverage"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be > 0")


def _steps(lots: float, step: float) -> int:
    # The tiny epsilon keeps e.g. 0.03 / 0.01 from rounding down to 2 steps.
    return math.floor(lots / step + 1e-9)


def lot_size(balance: float, entry: float, stop: float, rules: LotRules) -> float:
    """Lots that lose at most ``rules.risk`` of ``balance`` at the stop; 0 if too small."""
    points = abs(entry - stop)
    if balance <= 0 or points <= 0:
        return 0.0
    loss_per_lot = points * rules.contract_size + rules.commission_per_lot
    lots = balance * rules.risk / loss_per_lot
    if rules.max_lot is not None:
        lots = min(lots, rules.max_lot)
    if rules.leverage is not None:
        lots = min(lots, balance * rules.leverage / (rules.contract_size * entry))
    lots = round(_steps(lots, rules.lot_step) * rules.lot_step, 8)
    return lots if lots >= rules.min_lot - 1e-9 else 0.0


def split_thirds(lots: float, step: float) -> tuple[float, float, float]:
    """Three parts in whole lot steps, the first ones taking any remainder."""
    n = _steps(lots, step)
    base, extra = divmod(n, len(TARGETS))
    return tuple(round((base + (i < extra)) * step, 8) for i in range(len(TARGETS)))


@dataclass(frozen=True)
class AccountTrade:
    trade: ZoneTrade
    balance_before: float
    lots: float  # 0 when the trade was skipped as too small for the minimum lot
    risk_money: float  # what hitting the stop would have lost
    pnl: float
    balance_after: float


def trade_pnl(trade: ZoneTrade, lots: float, rules: LotRules) -> float:
    """Money made or lost by ``lots`` of ``trade``, after commission."""
    if lots <= 0:
        return 0.0
    per_r = trade.risk * rules.contract_size  # money per R per lot
    if trade.outcome in LEG_R:
        legs = split_thirds(lots, rules.lot_step)
        gross = sum(part * r * per_r for part, r in zip(legs, LEG_R[trade.outcome], strict=True))
    else:  # "target" (one exit) or "open" (marked at the last close)
        gross = lots * trade.result_r * per_r
    return gross - lots * rules.commission_per_lot


def replay_account(trades: list[ZoneTrade], balance: float, rules: LotRules) -> list[AccountTrade]:
    """Size every trade from the balance at the time and apply its result, oldest first."""
    out = []
    for trade in trades:
        lots = lot_size(balance, trade.entry, trade.stop, rules)
        risk_money = lots * (trade.risk * rules.contract_size + rules.commission_per_lot)
        pnl = trade_pnl(trade, lots, rules)
        out.append(AccountTrade(trade, balance, lots, risk_money, pnl, balance + pnl))
        balance += pnl
    return out
