from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from manoj_bot.timeframes import to_utc

OHLC = ["open", "high", "low", "close"]


class DataFeed(ABC):
    @abstractmethod
    def history(
        self,
        symbol: str,
        timeframe: str,
        *,
        start=None,
        end=None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """OHLCV bars between ``start`` and ``end`` (inclusive), or the latest ``limit`` bars.

        The frame has float columns open, high, low, close, volume and is indexed by each
        bar's open time in UTC, oldest first. The newest bar may still be in progress.
        """


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Lower-case the columns, index by UTC time, sort, and drop duplicate or empty bars."""
    frame = frame.rename(columns=lambda column: str(column).lower())
    missing = [column for column in OHLC if column not in frame.columns]
    if missing:
        raise ValueError(f"Price data is missing column(s): {', '.join(missing)}")
    if "volume" not in frame.columns:
        frame = frame.assign(volume=0.0)
    out = frame[[*OHLC, "volume"]].astype(float)
    index = pd.DatetimeIndex(out.index)
    out.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    out.index.name = "timestamp"
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=OHLC)


def clip(frame: pd.DataFrame, start=None, end=None, limit: int | None = None) -> pd.DataFrame:
    if start is not None:
        frame = frame[frame.index >= to_utc(start)]
    if end is not None:
        frame = frame[frame.index <= to_utc(end)]
    if limit is not None:
        frame = frame.tail(limit)
    return frame
