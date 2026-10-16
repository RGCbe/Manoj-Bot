from __future__ import annotations

from pathlib import Path

import pandas as pd

from manoj_bot.data.base import DataFeed, clip, normalize_ohlcv

TIME_COLUMNS = ("timestamp", "datetime", "date", "time")


class CsvFeed(DataFeed):
    """Bars from a CSV file with a time column plus open, high, low, close (and volume).

    The time column may hold dates/datetimes or Unix epochs in seconds or milliseconds.
    The file is used as-is: ``symbol`` and ``timeframe`` are not checked against it.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def history(self, symbol, timeframe, *, start=None, end=None, limit=None) -> pd.DataFrame:
        raw = pd.read_csv(self.path)
        if raw.empty:
            raise ValueError(f"{self.path} has no rows")
        time_column = next(
            (column for column in raw.columns if str(column).lower() in TIME_COLUMNS),
            raw.columns[0],
        )
        times = raw.pop(time_column)
        if pd.api.types.is_numeric_dtype(times):
            unit = "ms" if times.max() > 1e11 else "s"
            index = pd.to_datetime(times, unit=unit, utc=True)
        else:
            index = pd.to_datetime(times, utc=True)
        raw.index = pd.DatetimeIndex(index)
        return clip(normalize_ohlcv(raw), start, end, limit)
