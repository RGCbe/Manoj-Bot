"""Bar-by-bar backtester.

Signals are computed from each bar's close and executed at the next bar's open, so a strategy
never trades on information it could not have had yet. Stop-loss and take-profit levels are
checked against each bar's low and high; when a bar gaps through a level the exit happens at
the open instead. If both levels fall inside one bar, the stop is assumed to hit first.
After a stop-loss or take-profit exit the strategy must go flat before it can buy again.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

import numpy as np
import pandas as pd

from manoj_bot.brokers.paper import simulate_fill
from manoj_bot.config import CostConfig, RiskConfig
from manoj_bot.metrics import compute_metrics
from manoj_bot.portfolio import Portfolio, Trade
from manoj_bot.risk import drawdown_breached, exit_levels, position_quantity
from manoj_bot.strategies import Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade]
    metrics: dict[str, float]

    def trades_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            [asdict(trade) for trade in self.trades], columns=[f.name for f in fields(Trade)]
        )
        for column in ("entry_time", "exit_time"):
            frame[column] = pd.to_datetime(frame[column])
        return frame

    def summary(self) -> str:
        m = self.metrics
        rows = [
            (
                "Period",
                f"{self.equity.index[0]:%Y-%m-%d %H:%M} -> {self.equity.index[-1]:%Y-%m-%d %H:%M}",
            ),
            ("Bars", f"{len(self.equity)}"),
            ("Initial capital", f"{m['initial_capital']:,.2f}"),
            ("Final equity", f"{m['final_equity']:,.2f}"),
            ("Total return", f"{m['total_return']:.2%}"),
            ("Buy & hold return", f"{m['buy_and_hold_return']:.2%}"),
            ("CAGR", f"{m['cagr']:.2%}"),
            ("Sharpe ratio", f"{m['sharpe']:.2f}"),
            ("Max drawdown", f"{m['max_drawdown']:.2%}"),
            ("Trades", f"{m['trades']}"),
            ("Win rate", f"{m['win_rate']:.2%}"),
            ("Profit factor", f"{m['profit_factor']:.2f}"),
            ("Avg trade return", f"{m['avg_trade_return']:.2%}"),
            ("Time in market", f"{m['exposure']:.2%}"),
            ("Fees paid", f"{m['fees']:,.2f}"),
        ]
        return "\n".join(f"{label:<18} {value}" for label, value in rows)


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    risk: RiskConfig,
    costs: CostConfig,
    capital: float,
) -> BacktestResult:
    if data.empty:
        raise ValueError("No data to backtest")
    signals = strategy.generate_signals(data).reindex(data.index).fillna(0).astype(int).to_numpy()

    portfolio = Portfolio(cash=capital)
    trades: list[Trade] = []
    equity = np.empty(len(data))
    in_market = np.zeros(len(data), dtype=bool)
    peak, halted, wait_for_reset, fees = capital, False, False, 0.0

    def buy(quantity: float, price: float, stamp: str) -> None:
        nonlocal fees
        fill = simulate_fill("buy", quantity, price, costs, stamp)
        fees += fill.fee
        portfolio.apply_buy(fill)

    def sell(price: float, stamp: str, reason: str) -> None:
        nonlocal fees, wait_for_reset
        fill = simulate_fill("sell", portfolio.quantity, price, costs, stamp)
        fees += fill.fee
        trades.append(portfolio.apply_sell(fill, reason))
        if reason in ("stop_loss", "take_profit"):
            wait_for_reset = True

    bars = zip(
        data.index,
        data["open"].to_numpy(),
        data["high"].to_numpy(),
        data["low"].to_numpy(),
        data["close"].to_numpy(),
        strict=True,
    )
    for i, (ts, open_, high, low, close) in enumerate(bars):
        stamp = ts.isoformat()
        target = signals[i - 1] if i else 0
        if target == 0:
            wait_for_reset = False

        # At the open: gaps through stop/target first, then the previous bar's signal.
        if portfolio.quantity > 0:
            stop, take = exit_levels(portfolio.entry_price, risk)
            if stop is not None and open_ <= stop:
                sell(open_, stamp, "stop_loss")
            elif take is not None and open_ >= take:
                sell(open_, stamp, "take_profit")
            elif target == 0:
                sell(open_, stamp, "signal")
        if portfolio.quantity == 0 and target == 1 and not (halted or wait_for_reset):
            quantity = position_quantity(portfolio.cash, portfolio.cash, open_, risk, costs)
            if quantity > 0 and quantity * open_ >= risk.min_trade_value:
                buy(quantity, open_, stamp)

        # During the bar: stop-loss / take-profit.
        if portfolio.quantity > 0:
            stop, take = exit_levels(portfolio.entry_price, risk)
            if stop is not None and low <= stop:
                sell(stop, stamp, "stop_loss")
            elif take is not None and high >= take:
                sell(take, stamp, "take_profit")

        # At the close: drawdown circuit breaker.
        value = portfolio.equity(close)
        peak = max(peak, value)
        if not halted and drawdown_breached(value, peak, risk):
            halted = True
            if portfolio.quantity > 0:
                sell(close, stamp, "drawdown_halt")
                value = portfolio.equity(close)
        equity[i] = value
        in_market[i] = portfolio.quantity > 0

    if portfolio.quantity > 0:
        sell(data["close"].iloc[-1], data.index[-1].isoformat(), "end_of_data")
        equity[-1] = portfolio.cash

    curve = pd.Series(equity, index=data.index, name="equity")
    metrics = compute_metrics(
        curve, trades, data["close"], capital, exposure=float(in_market.mean()), fees=fees
    )
    return BacktestResult(curve, trades, metrics)
