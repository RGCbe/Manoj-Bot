"""Command line interface: ``manoj-bot backtest | run | status | strategies``."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys
from pathlib import Path

import yaml

from manoj_bot.backtest import run_backtest
from manoj_bot.brokers import Broker, PaperBroker
from manoj_bot.config import DATA_SOURCES, BotConfig
from manoj_bot.data import build_feed
from manoj_bot.engine import TradingBot, load_state
from manoj_bot.strategies import STRATEGIES, build_strategy

log = logging.getLogger("manoj_bot")

DEFAULT_BACKTEST_BARS = 1000


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    try:
        return args.handler(args)
    except Exception as exc:
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manoj-bot", description="Backtest, paper trade and live trade strategies."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    backtest = commands.add_parser("backtest", help="test a strategy on historical data")
    backtest.add_argument("-c", "--config", help="YAML config file (defaults if omitted)")
    backtest.add_argument("--source", choices=DATA_SOURCES, help="data source")
    backtest.add_argument("--csv", metavar="PATH", help="read bars from a CSV file")
    backtest.add_argument("--exchange", help="ccxt exchange id, e.g. binance")
    backtest.add_argument("--symbol", help="e.g. BTC/USDT, AAPL, RELIANCE.NS")
    backtest.add_argument("--timeframe", help="bar size, e.g. 15m, 1h, 1d")
    backtest.add_argument("--start", help="first date, e.g. 2023-01-01")
    backtest.add_argument("--end", help="last date (inclusive)")
    backtest.add_argument("--bars", type=int, help="number of most recent bars to use")
    backtest.add_argument("--capital", type=float, help="starting capital")
    backtest.add_argument("--strategy", choices=sorted(STRATEGIES), help="strategy name")
    backtest.add_argument(
        "-p",
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="strategy parameter, e.g. -p fast=10 -p slow=30 (repeatable)",
    )
    backtest.add_argument("--trades-out", metavar="CSV", help="write the trade list to a CSV")
    backtest.add_argument("--equity-out", metavar="CSV", help="write the equity curve to a CSV")
    backtest.set_defaults(handler=_backtest)

    run = commands.add_parser("run", help="trade on live market data (paper or live)")
    run.add_argument("-c", "--config", default="config.yaml", help="YAML config file")
    run.add_argument("--once", action="store_true", help="check the market once and exit")
    run.add_argument("--iterations", type=int, help="stop after this many checks")
    run.add_argument(
        "--confirm-live",
        action="store_true",
        help="required when the config has mode: live (real orders, real money)",
    )
    run.set_defaults(handler=_run)

    status = commands.add_parser("status", help="show the bot's saved position and trades")
    status.add_argument("-c", "--config", default="config.yaml", help="YAML config file")
    status.set_defaults(handler=_status)

    strategies = commands.add_parser("strategies", help="list strategies and their parameters")
    strategies.set_defaults(handler=_strategies)
    return parser


def _backtest(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config) if args.config else BotConfig()
    for name in ("symbol", "timeframe", "capital"):
        if getattr(args, name) is not None:
            setattr(config, name, getattr(args, name))
    if args.csv:
        config.data.source, config.data.path = "csv", args.csv
    if args.source:
        config.data.source = args.source
    if args.exchange:
        config.data.exchange = args.exchange
    if args.strategy and args.strategy != config.strategy.name:
        config.strategy.name, config.strategy.params = args.strategy, {}
    config.strategy.params.update(_parse_params(args.param))
    config.validate()

    strategy = build_strategy(config.strategy.name, config.strategy.params)
    limit = args.bars or (None if args.start else DEFAULT_BACKTEST_BARS)
    data = build_feed(config.data).history(
        config.symbol, config.timeframe, start=args.start, end=args.end, limit=limit
    )
    if len(data) <= strategy.warmup:
        raise ValueError(f"Got {len(data)} bars; {strategy} needs more than {strategy.warmup}")

    result = run_backtest(data, strategy, config.risk, config.costs, config.capital)
    source = config.data.source
    if source == "synthetic":
        source += " (made-up random prices, for demos only)"
    print(f"Symbol             {config.symbol} {config.timeframe} via {source}")
    print(f"Strategy           {strategy}")
    print(result.summary())
    if args.trades_out:
        result.trades_frame().to_csv(args.trades_out, index=False)
        print(f"Trades written to {args.trades_out}")
    if args.equity_out:
        result.equity.to_csv(args.equity_out)
        print(f"Equity curve written to {args.equity_out}")
    return 0


def _run(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config)
    if config.mode == "live":
        if not args.confirm_live:
            print(
                "error: the config has mode: live, which places REAL orders. "
                "Re-run with --confirm-live if that is what you want.",
                file=sys.stderr,
            )
            return 2
        if config.data.source != "ccxt":
            raise ValueError("Live trading needs data.source: ccxt (prices from the exchange)")
        if config.data.exchange != config.broker.exchange:
            raise ValueError("data.exchange and broker.exchange must match for live trading")
    elif config.data.source not in ("yahoo", "ccxt"):
        raise ValueError("'run' needs live market data: set data.source to yahoo or ccxt")

    strategy = build_strategy(config.strategy.name, config.strategy.params)
    feed = build_feed(config.data)
    broker = _live_broker(config) if config.mode == "live" else PaperBroker(config.costs)
    bot = TradingBot(config, strategy, feed, broker)
    log.info(
        "Starting %s trading: %s %s, strategy %s, capital %.2f, state %s",
        config.mode,
        config.symbol,
        config.timeframe,
        strategy,
        config.capital,
        config.state_file,
    )
    try:
        bot.run(1 if args.once else args.iterations)
    except KeyboardInterrupt:
        log.info("Stopped")
    return 0


def _live_broker(config: BotConfig) -> Broker:
    from manoj_bot.brokers.ccxt_broker import CcxtBroker

    api_key, secret = os.environ.get("MANOJ_BOT_API_KEY"), os.environ.get("MANOJ_BOT_API_SECRET")
    if not api_key or not secret:
        raise ValueError("Set MANOJ_BOT_API_KEY and MANOJ_BOT_API_SECRET for live trading")
    log.warning(
        "LIVE TRADING on %s%s with up to %.2f of capital",
        config.broker.exchange,
        " (sandbox/testnet)" if config.broker.sandbox else "",
        config.capital,
    )
    return CcxtBroker(
        config.broker.exchange,
        api_key=api_key,
        secret=secret,
        password=os.environ.get("MANOJ_BOT_API_PASSWORD"),
        sandbox=config.broker.sandbox,
    )


def _status(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config)
    if not Path(config.state_file).exists():
        print(f"No saved state at {config.state_file} yet.")
        return 0
    state = load_state(config.state_file, config)
    portfolio = state.portfolio
    print(f"Symbol        {state.symbol} ({config.mode})")
    print(f"Cash          {portfolio.cash:,.2f}")
    if portfolio.quantity > 0:
        print(f"Position      {portfolio.quantity:.8g} @ {portfolio.entry_price:.6g}")
    else:
        print("Position      none")
    print(
        f"Closed trades {len(state.trades)}, realised P&L {sum(t.pnl for t in state.trades):,.2f}"
    )
    if state.halted:
        print("HALTED        max drawdown reached; delete the state file to reset")
    for trade in state.trades[-10:]:
        print(
            f"  {trade.exit_time[:19]}  {trade.exit_reason:<13} "
            f"{trade.entry_price:.6g} -> {trade.exit_price:.6g}  pnl {trade.pnl:,.2f}"
        )
    return 0


def _strategies(args: argparse.Namespace) -> int:
    for name, cls in STRATEGIES.items():
        params = ", ".join(f"{f.name}={f.default!r}" for f in dataclasses.fields(cls))
        print(f"{name}\n    {' '.join((cls.__doc__ or '').split())}\n    params: {params}")
    return 0


def _parse_params(items: list[str]) -> dict:
    params = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"Strategy parameters look like KEY=VALUE, got {item!r}")
        params[key.strip()] = yaml.safe_load(value)
    return params
