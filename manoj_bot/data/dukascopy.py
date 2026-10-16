from __future__ import annotations

import logging
import lzma
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from manoj_bot.data.base import OHLC, DataFeed, clip, normalize_ohlcv
from manoj_bot.timeframes import parse_timeframe, to_utc

log = logging.getLogger(__name__)

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
ALIASES = {"GOLD": "XAUUSD", "SILVER": "XAGUSD"}
COLUMNS = [*OHLC, "volume"]
# Hourly tick files: ms into the hour, ask, bid (integer prices), ask volume, bid volume.
TICK = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"), ("ask_vol", ">f4"), ("bid_vol", ">f4")])
# Daily 1-minute candle files, one per side (BID/ASK): seconds into the day, then prices.
CANDLE = np.dtype(
    [("sec", ">u4"), ("open", ">u4"), ("close", ">u4"), ("low", ">u4"), ("high", ">u4"), ("volume", ">f4")]
)
RETRIES = 8
DEFAULT_CACHE = Path.home() / ".cache" / "manoj-bot" / "dukascopy"


def instrument(symbol: str) -> str:
    """'XAU/USD', 'xauusd' and 'GOLD' all become 'XAUUSD'."""
    name = symbol.replace("/", "").upper()
    return ALIASES.get(name, name)


def price_scale(name: str) -> int:
    """Dukascopy stores prices as integers; divide by this to get the price."""
    if name.startswith(("XAU", "XAG")) or name.endswith("JPY"):
        return 1_000
    return 100_000


class DukascopyFeed(DataFeed):
    """Spot gold, silver and FX from Dukascopy's free historical data (no API key).

    Prices are the mid of bid and ask, which is close to what TradingView shows for spot
    gold. Completed days come from daily 1-minute files; today comes from hourly tick
    files, which appear with a short delay, so this suits backtests rather than live
    trading. Minutes without trading (weekends, the daily break) are left out.

    Dukascopy is slow and throttles busy clients, so completed days are cached on disk
    (``cache_dir``, one small CSV per day) and an interrupted download resumes there.
    """

    workers = 4

    def __init__(
        self,
        fetch: Callable[[str], bytes | None] | None = None,
        clock: Callable[[], pd.Timestamp] | None = None,
        cache_dir: str | Path | None = DEFAULT_CACHE,
    ):
        self._fetch = fetch or _download
        self._clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))
        self._cache = Path(cache_dir) if cache_dir is not None else None

    def history(self, symbol, timeframe, *, start=None, end=None, limit=None) -> pd.DataFrame:
        step = parse_timeframe(timeframe)
        name = instrument(symbol)
        now = self._clock()
        last = min(to_utc(end) + step, now) if end is not None else now
        if start is not None:
            first = to_utc(start)
        else:
            # Gold and FX close at weekends, so reach back further than bars * step.
            first = last - step * (limit or 1000) * 1.5 - pd.Timedelta(days=3)
        days = pd.date_range(first.floor("D"), last, freq="D", inclusive="left")
        log.info("Downloading %d days of %s from Dukascopy", len(days), name)

        frames = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for done, frame in enumerate(pool.map(lambda day: self._day(name, day, now), days), 1):
                if len(frame):
                    frames.append(frame)
                if done % 10 == 0 or done == len(days):
                    log.info("%s: %d of %d days done", name, done, len(days))
        if not frames:
            raise ValueError(f"Dukascopy has no {name} data between {first} and {last}")
        bars = pd.concat(frames).resample(step).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        return clip(normalize_ohlcv(bars), start, end, limit)

    def _day(self, name: str, day: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
        """1-minute mid-price bars for one UTC day."""
        if day < now.floor("D"):
            cached = self._cache / name / f"{day:%Y-%m-%d}.csv" if self._cache else None
            if cached is not None and cached.exists():
                frame = pd.read_csv(cached, index_col=0)
                frame.index = pd.to_datetime(frame.index, utc=True)
                return frame
            minutes = self._minute_file_day(name, day)
            if minutes is not None:
                if cached is not None:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    minutes.to_csv(cached)
                return minutes
            log.info("No minute file for %s %s yet; using tick files", name, day.date())
        hours = pd.date_range(day, min(day + pd.Timedelta(days=1), now), freq="h", inclusive="left")
        frames = [f for f in (self._tick_hour(name, hour) for hour in hours) if len(f)]
        return pd.concat(frames) if frames else pd.DataFrame(columns=COLUMNS, dtype=float)

    def _minute_file_day(self, name: str, day: pd.Timestamp) -> pd.DataFrame | None:
        sides = {}
        for side in ("BID", "ASK"):
            raw = self._fetch(f"{_day_url(name, day)}/{side}_candles_min_1.bi5")
            if raw is None:
                return None
            sides[side] = np.frombuffer(lzma.decompress(raw), dtype=CANDLE) if raw else None
        bid, ask = sides["BID"], sides["ASK"]
        if bid is None or ask is None or len(bid) != len(ask):
            return None
        scale = 2 * price_scale(name)
        frame = pd.DataFrame(
            {column: (bid[column].astype(float) + ask[column].astype(float)) / scale for column in OHLC},
            index=day + pd.to_timedelta(bid["sec"].astype("int64"), unit="s"),
        )
        frame["volume"] = bid["volume"].astype(float) + ask["volume"].astype(float)
        return frame[frame["volume"] > 0]

    def _tick_hour(self, name: str, hour: pd.Timestamp) -> pd.DataFrame:
        raw = self._fetch(f"{_day_url(name, hour)}/{hour.hour:02d}h_ticks.bi5")
        if not raw:
            return pd.DataFrame(columns=COLUMNS, dtype=float)
        ticks = np.frombuffer(lzma.decompress(raw), dtype=TICK)
        times = pd.DatetimeIndex(hour + pd.to_timedelta(ticks["ms"].astype("int64"), unit="ms"))
        mid = (ticks["ask"].astype(float) + ticks["bid"].astype(float)) / (2 * price_scale(name))
        volume = ticks["ask_vol"].astype(float) + ticks["bid_vol"].astype(float)
        minutes = pd.Series(mid, index=times).resample("1min").ohlc()
        minutes["volume"] = pd.Series(volume, index=times).resample("1min").sum()
        return minutes.dropna()


def _day_url(name: str, day: pd.Timestamp) -> str:
    # Months in Dukascopy URLs count from 0.
    return f"{BASE_URL}/{name}/{day.year}/{day.month - 1:02d}/{day.day:02d}"


def _download(url: str) -> bytes | None:
    """The file's bytes, or None when Dukascopy has no such file.

    The server often answers 503 or drops connections under load, so retry with
    growing pauses before giving up.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            error: Exception = exc
        except OSError as exc:
            error = exc
        log.debug("Retrying %s after %s", url, error)
        time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"Dukascopy kept failing for {url}: {error}")
