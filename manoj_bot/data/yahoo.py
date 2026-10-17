from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pandas as pd

from manoj_bot.data.base import DataFeed, clip, normalize_ohlcv
from manoj_bot.timeframes import parse_timeframe, to_utc

log = logging.getLogger(__name__)

# Bot timeframe -> Yahoo interval.
INTERVALS = {
    "1m": "1m",
    "2m": "2m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "90m": "90m",
    "1h": "1h",
    "1d": "1d",
    "5d": "5d",
    "1w": "1wk",
}
# How far back Yahoo serves intraday bars.
MAX_LOOKBACK = {
    "1m": pd.Timedelta(days=7),
    "2m": pd.Timedelta(days=59),
    "5m": pd.Timedelta(days=59),
    "15m": pd.Timedelta(days=59),
    "30m": pd.Timedelta(days=59),
    "90m": pd.Timedelta(days=59),
    "1h": pd.Timedelta(days=729),
}


class YahooFeed(DataFeed):
    """Stocks, ETFs, indices and FX from Yahoo Finance (e.g. AAPL, RELIANCE.NS, ^NSEI)."""

    def __init__(self, ticker_factory: Callable[[str], Any] | None = None):
        if ticker_factory is None:
            try:
                import yfinance
            except ImportError as exc:
                raise RuntimeError(
                    "yfinance is not installed; run: pip install 'manoj-bot[stocks]'"
                ) from exc
            ticker_factory = yfinance.Ticker
        self._ticker = ticker_factory

    def history(self, symbol, timeframe, *, start=None, end=None, limit=None) -> pd.DataFrame:
        interval = INTERVALS.get(timeframe)
        if interval is None:
            raise ValueError(
                f"Yahoo Finance does not support timeframe {timeframe!r}; "
                f"use one of {', '.join(INTERVALS)}"
            )
        step = parse_timeframe(timeframe)
        end_ts = to_utc(end) if end is not None else pd.Timestamp.now(tz="UTC")
        if start is not None:
            start_ts = to_utc(start)
        else:
            # Markets close overnight and at weekends, so reach back well beyond bars * step.
            factor = 5 if step < pd.Timedelta(days=1) else 1.6
            start_ts = end_ts - step * (limit or 1000) * factor - pd.Timedelta(days=5)
        cap = MAX_LOOKBACK.get(timeframe)
        if cap is not None and start_ts < end_ts - cap:
            if start is not None:
                log.warning("Yahoo only serves %s bars for the last %s; start moved", interval, cap)
            start_ts = end_ts - cap

        raw = self._ticker(symbol).history(
            start=start_ts.to_pydatetime(),
            # Yahoo's end is exclusive; ours is inclusive.
            end=(end_ts + step).to_pydatetime() if end is not None else None,
            interval=interval,
            auto_adjust=True,
        )
        if raw is None or raw.empty:
            raise ValueError(
                f"Yahoo Finance returned no {interval} data for {symbol!r}. Check the ticker: "
                "NSE stocks end in .NS (RELIANCE.NS), BSE stocks in .BO"
            )
        return clip(normalize_ohlcv(raw), start, end, limit)
