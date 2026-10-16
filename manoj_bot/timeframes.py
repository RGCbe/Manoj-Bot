"""Helpers for timeframe strings such as ``"15m"``, ``"1h"`` or ``"1d"``, and for timestamps."""

from __future__ import annotations

import re

import pandas as pd

_PATTERN = re.compile(r"(\d+)([mhdw])")
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_timeframe(timeframe: str) -> pd.Timedelta:
    """Convert a timeframe like ``"4h"`` into a :class:`pandas.Timedelta`."""
    match = _PATTERN.fullmatch(timeframe.strip()) if isinstance(timeframe, str) else None
    if match is None or int(match.group(1)) == 0:
        raise ValueError(
            f"Invalid timeframe {timeframe!r}; expected e.g. '1m', '15m', '1h', '4h', '1d' or '1w'"
        )
    return pd.Timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def completed_bars(data: pd.DataFrame, timeframe: str, now: pd.Timestamp) -> pd.DataFrame:
    """Drop bars that have not closed yet at ``now``. Bars are labelled by their open time."""
    return data[data.index + parse_timeframe(timeframe) <= now]


def to_utc(value) -> pd.Timestamp:
    """Parse a date/time (string, datetime or Timestamp) as a UTC timestamp."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
