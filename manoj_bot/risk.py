"""Position sizing and exit rules shared by the backtester and the live engine."""

from __future__ import annotations

import math

from manoj_bot.config import CostConfig, RiskConfig


def position_quantity(
    cash: float, equity: float, price: float, risk: RiskConfig, costs: CostConfig
) -> float:
    """Units to buy at ``price``, leaving room for slippage and fees."""
    if price <= 0 or cash <= 0:
        return 0.0
    budget = equity * risk.position_size
    if risk.risk_per_trade is not None and risk.stop_loss:
        # Size the position so that being stopped out loses about risk_per_trade of equity.
        budget = min(budget, equity * risk.risk_per_trade / risk.stop_loss)
    budget = min(budget, cash)
    quantity = budget / (price * (1 + costs.slippage) * (1 + costs.fee_rate))
    if risk.lot_size:
        # The tiny epsilon keeps e.g. 3 / 0.001 from rounding down to 2999 lots.
        quantity = math.floor(quantity / risk.lot_size + 1e-9) * risk.lot_size
    return quantity


def exit_levels(entry_price: float, risk: RiskConfig) -> tuple[float | None, float | None]:
    """Stop-loss and take-profit prices for a long position opened at ``entry_price``."""
    stop = entry_price * (1 - risk.stop_loss) if risk.stop_loss else None
    target = entry_price * (1 + risk.take_profit) if risk.take_profit else None
    return stop, target


def drawdown_breached(equity: float, peak: float, risk: RiskConfig) -> bool:
    """True when equity has fallen ``max_drawdown`` or more below its peak."""
    return risk.max_drawdown is not None and peak > 0 and equity <= peak * (1 - risk.max_drawdown)
