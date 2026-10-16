"""The trading loop for paper and live trading.

Each step fetches recent bars, asks the strategy for a signal on the bars that have closed,
and compares it with the bot's position. Stop-loss, take-profit and the drawdown limit are
checked against the latest price on every step. The bot keeps its own ledger (cash, position,
trades) in a JSON state file, so it only ever trades the capital it was given and can be
stopped and restarted safely.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from manoj_bot.brokers import Broker
from manoj_bot.config import BotConfig
from manoj_bot.data import DataFeed
from manoj_bot.portfolio import Portfolio, Trade
from manoj_bot.risk import drawdown_breached, exit_levels, position_quantity
from manoj_bot.strategies import Strategy
from manoj_bot.timeframes import completed_bars

log = logging.getLogger(__name__)

# Extra bars fetched beyond the strategy's warmup.
LOOKBACK_BUFFER = 50


@dataclass
class BotState:
    symbol: str
    portfolio: Portfolio
    peak_equity: float
    halted: bool = False
    wait_for_reset: bool = False
    trades: list[Trade] = field(default_factory=list)

    @classmethod
    def new(cls, config: BotConfig) -> BotState:
        return cls(config.symbol, Portfolio(cash=config.capital), peak_equity=config.capital)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BotState:
        return cls(
            symbol=raw["symbol"],
            portfolio=Portfolio(**raw["portfolio"]),
            peak_equity=raw["peak_equity"],
            halted=raw.get("halted", False),
            wait_for_reset=raw.get("wait_for_reset", False),
            trades=[Trade(**trade) for trade in raw.get("trades", [])],
        )


def load_state(path: str | Path, config: BotConfig) -> BotState:
    path = Path(path)
    if not path.exists():
        return BotState.new(config)
    state = BotState.from_dict(json.loads(path.read_text()))
    if state.symbol != config.symbol:
        raise ValueError(
            f"State file {path} belongs to {state.symbol}, not {config.symbol}. "
            "Use a different state_file for each symbol."
        )
    return state


def save_state(path: str | Path, state: BotState) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2))
    tmp.replace(path)


class TradingBot:
    def __init__(
        self,
        config: BotConfig,
        strategy: Strategy,
        feed: DataFeed,
        broker: Broker,
        *,
        clock: Callable[[], pd.Timestamp] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.strategy = strategy
        self.feed = feed
        self.broker = broker
        self.state = load_state(config.state_file, config)
        self._clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))
        self._sleep = sleep

    def run(self, iterations: int | None = None) -> None:
        """Step every ``poll_interval`` seconds, forever or ``iterations`` times."""
        done = 0
        while iterations is None or done < iterations:
            try:
                self.step()
            except Exception:
                log.exception("Step failed; retrying in %ss", self.config.poll_interval)
            done += 1
            if iterations is None or done < iterations:
                self._sleep(self.config.poll_interval)

    def step(self) -> str:
        """Check the market once and trade if needed. Returns what was done."""
        config = self.config
        data = self.feed.history(
            config.symbol, config.timeframe, limit=self.strategy.warmup + LOOKBACK_BUFFER
        )
        if data.empty:
            log.warning("No market data for %s", config.symbol)
            return "no-data"
        price = float(data["close"].iloc[-1])
        bars = completed_bars(data, config.timeframe, self._clock())
        if len(bars) < self.strategy.warmup:
            log.info("Waiting for data: %d of %d bars", len(bars), self.strategy.warmup)
            return "warming-up"

        signal = int(self.strategy.generate_signals(bars).iloc[-1])
        action = self._act(signal, price)
        save_state(config.state_file, self.state)
        log.info(
            "%s price=%.6g signal=%d equity=%.2f -> %s",
            config.symbol,
            price,
            signal,
            self.state.portfolio.equity(price),
            action,
        )
        return action

    def _act(self, signal: int, price: float) -> str:
        state, portfolio, risk = self.state, self.state.portfolio, self.config.risk
        if signal == 0:
            state.wait_for_reset = False

        equity = portfolio.equity(price)
        state.peak_equity = max(state.peak_equity, equity)
        if not state.halted and drawdown_breached(equity, state.peak_equity, risk):
            state.halted = True
            log.error(
                "Max drawdown reached (equity %.2f, peak %.2f): trading halted. "
                "Delete the state file to start over.",
                equity,
                state.peak_equity,
            )

        if portfolio.quantity > 0 and portfolio.quantity * price >= risk.min_trade_value:
            stop, take = exit_levels(portfolio.entry_price, risk)
            if state.halted:
                reason = "drawdown_halt"
            elif stop is not None and price <= stop:
                reason = "stop_loss"
            elif take is not None and price >= take:
                reason = "take_profit"
            elif signal == 0:
                reason = "signal"
            else:
                return "hold"
            fill = self.broker.sell(self.config.symbol, portfolio.quantity, price)
            trade = portfolio.apply_sell(fill, reason)
            state.trades.append(trade)
            if reason in ("stop_loss", "take_profit"):
                state.wait_for_reset = True
            log.info(
                "SELL %.8g %s @ %.6g (%s) pnl=%.2f",
                fill.quantity,
                self.config.symbol,
                fill.price,
                reason,
                trade.pnl,
            )
            return f"sell:{reason}"

        if signal != 1:
            return "flat"
        if state.halted:
            return "halted"
        if state.wait_for_reset:
            return "waiting-for-reset"
        quantity = position_quantity(portfolio.cash, equity, price, risk, self.config.costs)
        if quantity <= 0 or quantity * price < risk.min_trade_value:
            log.warning("Order value %.2f is below min_trade_value; not buying", quantity * price)
            return "too-small"
        fill = self.broker.buy(self.config.symbol, quantity, price)
        portfolio.apply_buy(fill)
        log.info("BUY %.8g %s @ %.6g", fill.quantity, self.config.symbol, fill.price)
        return "buy"
