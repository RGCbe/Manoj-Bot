import io
import lzma
import urllib.error

import numpy as np
import pandas as pd
import pytest

from manoj_bot.data import dukascopy
from manoj_bot.data.dukascopy import CANDLE, TICK, DukascopyFeed, instrument, price_scale

# Friday 02:30 UTC: Thursday 15 Oct is a completed day, Friday is still in progress.
NOW = pd.Timestamp("2026-10-16 02:30", tz="UTC")
DAY_URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/2026/09"  # months count from 0


def minute_file(traded: dict[int, tuple[float, float, float, float]], spread=0.0) -> bytes:
    """A day of 1-minute candles: the given minutes traded, every other minute flat and empty."""
    candles = np.zeros(1440, dtype=CANDLE)
    candles["sec"] = np.arange(1440) * 60
    for field in ("open", "close", "low", "high"):
        candles[field] = 4_100_000
    for minute, (o, h, low, c) in traded.items():
        prices = [round((p + spread) * 1000) for p in (o, c, low, h)]
        candles[minute] = (minute * 60, *prices, 2.0)
    return lzma.compress(candles.tobytes(), format=lzma.FORMAT_ALONE)


def tick_file(ticks: list[tuple[int, float]], spread=0.2) -> bytes:
    """An hour of ticks given as (ms into the hour, bid)."""
    records = np.zeros(len(ticks), dtype=TICK)
    for i, (ms, bid) in enumerate(ticks):
        records[i] = (ms, round((bid + spread) * 1000), round(bid * 1000), 1.0, 1.0)
    return lzma.compress(records.tobytes(), format=lzma.FORMAT_ALONE)


class FakeServer:
    def __init__(self, files):
        self.files, self.requests = files, []

    def __call__(self, url):
        self.requests.append(url)
        return self.files.get(url)


def thursday_files():
    bid = {minute: (4150.0, 4151.0, 4149.0, 4150.5) for minute in range(30)}
    return {
        f"{DAY_URL}/15/BID_candles_min_1.bi5": minute_file(bid),
        f"{DAY_URL}/15/ASK_candles_min_1.bi5": minute_file(bid, spread=0.2),
        f"{DAY_URL}/16/00h_ticks.bi5": tick_file(
            [(0, 4160.0), (60_000, 4162.0), (600_000, 4158.0)]
        ),
        f"{DAY_URL}/16/02h_ticks.bi5": b"",
    }


def feed(server, cache_dir=None):
    return DukascopyFeed(fetch=server, clock=lambda: NOW, cache_dir=cache_dir)


def test_symbol_names_and_price_scale():
    assert instrument("xau/usd") == instrument("GOLD") == "XAUUSD"
    assert price_scale("XAUUSD") == price_scale("USDJPY") == 1_000
    assert price_scale("EURUSD") == 100_000


def test_completed_days_use_minute_files_and_today_uses_ticks():
    server = FakeServer(thursday_files())
    bars = feed(server).history("XAUUSD", "15m", start="2026-10-15")

    thursday = bars.loc["2026-10-15"]
    # Two 15-minute bars from the 30 traded minutes; the flat, empty minutes are dropped.
    assert list(thursday.index.strftime("%H:%M")) == ["00:00", "00:15"]
    first = thursday.iloc[0]
    assert (first.open, first.high, first.low, first.close) == pytest.approx(
        (4150.1, 4151.1, 4149.1, 4150.6)  # mid of bid and ask
    )
    assert first.volume == pytest.approx(15 * 4.0)

    friday = bars.loc["2026-10-16"].iloc[0]
    assert (friday.open, friday.high, friday.low, friday.close) == pytest.approx(
        (4160.1, 4162.1, 4158.1, 4158.1)
    )
    assert f"{DAY_URL}/16/01h_ticks.bi5" in server.requests  # missing hour, no error
    assert not any("16/BID_candles" in url for url in server.requests)


def test_completed_days_are_cached(tmp_path):
    server = FakeServer(thursday_files())
    first = feed(server, tmp_path).history("XAUUSD", "15m", start="2026-10-15")
    minute_requests = sum("candles" in url for url in server.requests)

    again = feed(server, tmp_path).history("XAUUSD", "15m", start="2026-10-15")
    pd.testing.assert_frame_equal(first, again)
    assert sum("candles" in url for url in server.requests) == minute_requests
    assert (tmp_path / "XAUUSD" / "2026-10-15.csv").exists()
    assert not (tmp_path / "XAUUSD" / "2026-10-16.csv").exists()


def test_missing_minute_files_fall_back_to_ticks():
    files = {f"{DAY_URL}/15/03h_ticks.bi5": tick_file([(0, 4140.0)])}
    server = FakeServer(files)
    bars = feed(server).history("XAUUSD", "1h", start="2026-10-15", end="2026-10-15 23:00")
    assert bars.index[0] == pd.Timestamp("2026-10-15 03:00", tz="UTC")
    assert bars["close"].iloc[0] == pytest.approx(4140.1)


def test_weekend_without_trading_has_no_data():
    saturday = "https://datafeed.dukascopy.com/datafeed/XAUUSD/2026/09/10"
    files = {f"{saturday}/{side}_candles_min_1.bi5": minute_file({}) for side in ("BID", "ASK")}
    with pytest.raises(ValueError, match="no XAUUSD data"):
        feed(FakeServer(files)).history("XAUUSD", "15m", start="2026-10-10", end="2026-10-10 12:00")


def test_download_retries_busy_server_then_gives_up(monkeypatch):
    replies = [
        urllib.error.HTTPError("u", 503, "busy", {}, None),
        ConnectionResetError("reset"),
        io.BytesIO(b"data"),
    ]

    def urlopen(request, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(dukascopy.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(dukascopy.time, "sleep", lambda seconds: None)
    assert dukascopy._download("https://example.test/file") == b"data"

    def not_found(request, timeout):
        raise urllib.error.HTTPError("u", 404, "missing", {}, None)

    monkeypatch.setattr(dukascopy.urllib.request, "urlopen", not_found)
    assert dukascopy._download("https://example.test/file") is None

    def always_busy(request, timeout):
        raise urllib.error.HTTPError("u", 503, "busy", {}, None)

    monkeypatch.setattr(dukascopy.urllib.request, "urlopen", always_busy)
    with pytest.raises(RuntimeError, match="kept failing"):
        dukascopy._download("https://example.test/file")
