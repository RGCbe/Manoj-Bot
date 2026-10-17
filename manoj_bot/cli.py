"""Command line interface.

``manoj-bot backtest | run | status | strategies | download | zones | zone-trades``
"""

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
from manoj_bot.config import DATA_SOURCES, BotConfig, DataConfig
from manoj_bot.data import build_feed
from manoj_bot.engine import TradingBot, load_state
from manoj_bot.lots import LotRules, replay_account
from manoj_bot.strategies import STRATEGIES, build_strategy
from manoj_bot.timeframes import parse_timeframe
from manoj_bot.zone_trades import ZoneRules, setups_frame, summarize, trades_frame, zone_trades
from manoj_bot.zones import find_zones, zones_frame

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

    download = commands.add_parser("download", help="save historical bars to a CSV file")
    download.add_argument(
        "--source", choices=[s for s in DATA_SOURCES if s != "csv"], default="yahoo"
    )
    download.add_argument("--symbol", required=True, help="e.g. XAUUSD, RELIANCE.NS, BTC/USDT")
    download.add_argument("--timeframe", default="1d", help="bar size, e.g. 15m, 1h, 1d")
    download.add_argument("--exchange", default="binance", help="ccxt exchange id")
    download.add_argument("--start", help="first date, e.g. 2026-01-01")
    download.add_argument("--end", help="last date (inclusive)")
    download.add_argument("--bars", type=int, help="number of most recent bars, if no --start")
    download.add_argument("-o", "--out", required=True, metavar="CSV", help="file to write")
    download.set_defaults(handler=_download)

    zones = commands.add_parser("zones", help="list the weak zones (support / resistance)")
    _add_bar_arguments(zones)
    zones.add_argument("--tz", default="UTC", help="time zone to print, e.g. Asia/Kolkata")
    zones.add_argument("-o", "--out", metavar="CSV", help="also write the zones to a CSV")
    zones.set_defaults(handler=_zones)

    trades = commands.add_parser(
        "zone-trades", help="backtest the weak-zone entry rules (results in R)"
    )
    _add_bar_arguments(trades)
    trades.add_argument(
        "-p",
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="change a rule, e.g. -p max_stop=20 -p max_trades_thursday=3 (repeatable)",
    )
    trades.add_argument("-o", "--out", metavar="CSV", help="also write the trades to a CSV")
    trades.add_argument(
        "--setups-out", metavar="CSV", help="write every setup and why it was or was not traded"
    )
    trades.add_argument(
        "--balance", type=float, help="starting balance (USD): adds lot sizes and money results"
    )
    trades.add_argument(
        "--risk",
        type=float,
        default=0.01,
        help="share of the balance risked per trade (0.02 = 2%%)",
    )
    trades.add_argument("--contract-size", type=float, default=100.0, help="ounces per lot")
    trades.add_argument(
        "--min-lot", type=float, default=0.01, help="smallest order the broker takes"
    )
    trades.add_argument("--lot-step", type=float, default=0.01, help="lot size increment")
    trades.add_argument("--commission", type=float, default=0.0, help="round-trip cost per lot")
    trades.add_argument("--leverage", type=float, help="e.g. 500 for 1:500; caps lots by margin")
    trades.set_defaults(handler=_zone_trades)
    return parser


def _add_bar_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=DATA_SOURCES, default="dukascopy", help="data source")
    parser.add_argument("--csv", metavar="PATH", help="read bars from a CSV file")
    parser.add_argument("--symbol", default="XAUUSD", help="e.g. XAUUSD, BTC/USDT")
    parser.add_argument("--timeframe", default="15m", help="bar size, e.g. 15m")
    parser.add_argument("--exchange", default="binance", help="ccxt exchange id")
    parser.add_argument("--start", help="first date, e.g. 2026-10-15")
    parser.add_argument("--end", help="last date (inclusive)")
    parser.add_argument("--bars", type=int, help="number of most recent bars, if no --start")


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


def _download(args: argparse.Namespace) -> int:
    parse_timeframe(args.timeframe)
    feed = build_feed(DataConfig(source=args.source, exchange=args.exchange))
    limit = args.bars or (None if args.start else DEFAULT_BACKTEST_BARS)
    data = feed.history(args.symbol, args.timeframe, start=args.start, end=args.end, limit=limit)
    if data.empty:
        raise ValueError(f"No {args.timeframe} data for {args.symbol} from {args.source}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(out)
    print(
        f"Saved {len(data)} {args.timeframe} bars of {args.symbol} "
        f"({data.index[0]:%Y-%m-%d %H:%M} -> {data.index[-1]:%Y-%m-%d %H:%M} UTC) to {out}"
    )
    return 0


def _load_bars(args: argparse.Namespace):
    parse_timeframe(args.timeframe)
    source = "csv" if args.csv else args.source
    feed = build_feed(DataConfig(source=source, exchange=args.exchange, path=args.csv))
    limit = args.bars or (None if args.start else DEFAULT_BACKTEST_BARS)
    data = feed.history(args.symbol, args.timeframe, start=args.start, end=args.end, limit=limit)
    if data.empty:
        raise ValueError(f"No {args.timeframe} data for {args.symbol} from {source}")
    return data


def _zones(args: argparse.Namespace) -> int:
    zones = find_zones(_load_bars(args))
    print(f"{len(zones)} weak zones in {args.symbol} {args.timeframe}, times in {args.tz}")
    for zone in zones:
        start = zone.start.tz_convert(args.tz)
        formed = zone.formed.tz_convert(args.tz)
        end = (
            f"{zone.end_reason} {zone.end.tz_convert(args.tz):%a %d %b %H:%M}"
            if zone.end is not None
            else "live"
        )
        print(
            f"  {zone.kind:<10}  {zone.bottom:,.2f} - {zone.top:,.2f}  "
            f"from {start:%a %d %b %H:%M}  formed {formed:%H:%M}  {end}"
        )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        zones_frame(zones).to_csv(out, index=False)
        print(f"Zones written to {out}")
    return 0


def _zone_trades(args: argparse.Namespace) -> int:
    params = _parse_params(args.param)
    allowed = {f.name for f in dataclasses.fields(ZoneRules)}
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(
            f"Unknown rule(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}"
        )
    rules = ZoneRules(**params)
    trades, setups = zone_trades(_load_bars(args), rules)
    account = None
    if args.balance is not None:
        lot_rules = LotRules(
            risk=args.risk,
            contract_size=args.contract_size,
            min_lot=args.min_lot,
            lot_step=args.lot_step,
            commission_per_lot=args.commission,
            leverage=args.leverage,
        )
        account = replay_account(trades, args.balance, lot_rules)
    print(f"{len(trades)} weak-zone trades in {args.symbol} {args.timeframe}, times in {rules.tz}")
    for n, trade in enumerate(trades):
        signal = trade.signal_time.tz_convert(rules.tz)
        exit_ = trade.exit_time.tz_convert(rules.tz)
        money = ""
        if account:
            row = account[n]
            money = (
                f"  {row.lots:.2f} lot {row.pnl:+,.2f} -> {row.balance_after:,.2f}"
                if row.lots
                else "  skipped: the minimum lot risks too much"
            )
        print(
            f"  {signal:%a %d %b %H:%M}  {trade.side.upper():<4}  {trade.pattern:<17}  "
            f"entry {trade.entry:,.2f}  stop {trade.stop:,.2f}  1R {trade.risk:.2f}  "
            f"{trade.outcome:<7} {trade.result_r:+.2f}R  exit {exit_:%a %d %b %H:%M}{money}"
        )
    totals = summarize(trades)
    print(
        f"Trades {totals['trades']}, win rate {totals['win_rate']:.0%}, "
        f"net {totals['net_r']:+.1f}R, worst drop {totals['max_drawdown_r']:.1f}R, "
        f"longest losing run {totals['longest_losing_run']}"
    )
    frame = trades_frame(trades)
    if account:
        frame["lots"] = [row.lots for row in account]
        frame["pnl"] = [row.pnl for row in account]
        frame["balance_after"] = [row.balance_after for row in account]
    if trades:
        month = frame.signal_time.dt.tz_convert(rules.tz).dt.strftime("%Y-%m")
        by_month = frame.groupby(month, sort=True).result_r.sum()
        print("By month: " + ", ".join(f"{m} {r:+.1f}R" for m, r in by_month.items()))
    if account:
        balances = [args.balance] + [row.balance_after for row in account]
        peak, drop = balances[0], 0.0
        for value in balances:
            peak = max(peak, value)
            drop = max(drop, 1 - value / peak)
        end = balances[-1]
        skipped = sum(row.lots == 0 for row in account)
        print(
            f"Account {args.balance:,.2f} -> {end:,.2f} ({end / args.balance - 1:+.1%}) "
            f"risking {args.risk:.1%} a trade, worst drop {drop:.1%}, "
            f"{skipped} trades skipped as too small for the minimum lot"
        )
        if trades:
            start = args.balance
            for m, pnl in frame.groupby(month, sort=True).pnl.sum().items():
                print(f"  {m}  {pnl:+,.2f} ({pnl / start:+.1%})  balance {start + pnl:,.2f}")
                start += pnl
    for path, table, what in (
        (args.out, frame, "Trades"),
        (args.setups_out, setups_frame(setups), "Setups"),
    ):
        if path:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(out, index=False)
            print(f"{what} written to {out}")
    return 0


def _parse_params(items: list[str]) -> dict:
    params = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"Strategy parameters look like KEY=VALUE, got {item!r}")
        params[key.strip()] = yaml.safe_load(value)
    return params
