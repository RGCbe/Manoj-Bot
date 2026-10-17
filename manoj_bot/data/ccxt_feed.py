from __future__ import annotations

from typing import Any

import pandas as pd

from manoj_bot._ccxt import create_exchange
from manoj_bot.data.base import DataFeed, clip, normalize_ohlcv
from manoj_bot.timeframes import parse_timeframe, to_utc

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class CcxtFeed(DataFeed):
    """Crypto candles from any exchange supported by ccxt (public data, no API key needed)."""

    page_size = 1000

    def __init__(self, exchange_id: str = "binance", exchange: Any = None):
        self.exchange = exchange if exchange is not None else create_exchange(exchange_id)

    def history(self, symbol, timeframe, *, start=None, end=None, limit=None) -> pd.DataFrame:
        step_ms = int(parse_timeframe(timeframe).total_seconds() * 1000)
        end_ms = _ms(end) if end is not None else int(self.exchange.milliseconds())
        if start is not None:
            since = _ms(start)
        else:
            since = end_ms - ((limit or 1000) + 1) * step_ms

        rows: list[list[float]] = []
        while since <= end_ms:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=self.page_size)
            if not batch:
                break
            rows.extend(batch)
            next_since = int(batch[-1][0]) + step_ms
            if next_since <= since:
                break
            since = next_since

        frame = pd.DataFrame(rows, columns=COLUMNS)
        frame.index = pd.to_datetime(frame.pop("timestamp"), unit="ms", utc=True)
        return clip(normalize_ohlcv(frame), start, end, limit)


def _ms(value) -> int:
    return int(to_utc(value).timestamp() * 1000)
