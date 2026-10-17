"""Performance statistics for an equity curve and its trades."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from manoj_bot.portfolio import Trade

SECONDS_PER_YEAR = 365.25 * 24 * 3600


def compute_metrics(
    equity: pd.Series,
    trades: list[Trade],
    prices: pd.Series,
    capital: float,
    exposure: float,
    fees: float,
) -> dict[str, float]:
    final = float(equity.iloc[-1])
    years = (equity.index[-1] - equity.index[0]).total_seconds() / SECONDS_PER_YEAR

    returns = equity.pct_change().dropna()
    # Annualise with the observed bar frequency, so market hours and weekends are respected.
    periods_per_year = len(returns) / years if years > 0 else 0.0
    std = float(returns.std()) if len(returns) > 1 else 0.0
    sharpe = float(returns.mean()) / std * math.sqrt(periods_per_year) if std > 0 else 0.0

    curve = np.r_[capital, equity.to_numpy()]
    max_drawdown = float((curve / np.maximum.accumulate(curve) - 1).min())

    pnls = [trade.pnl for trade in trades]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p <= 0)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = math.inf if gross_profit > 0 else 0.0

    return {
        "initial_capital": capital,
        "final_equity": final,
        "total_return": final / capital - 1,
        "buy_and_hold_return": float(prices.iloc[-1] / prices.iloc[0] - 1),
        "cagr": (final / capital) ** (1 / years) - 1 if years > 0 and final > 0 else 0.0,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "trades": len(trades),
        "win_rate": sum(p > 0 for p in pnls) / len(pnls) if pnls else 0.0,
        "profit_factor": profit_factor,
        "avg_trade_return": float(np.mean([t.return_pct for t in trades])) if trades else 0.0,
        "exposure": exposure,
        "fees": fees,
    }
