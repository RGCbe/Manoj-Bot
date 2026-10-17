import pandas as pd
import pytest

from manoj_bot.config import DataConfig
from manoj_bot.data import CsvFeed, SyntheticFeed, build_feed, normalize_ohlcv
from manoj_bot.data.ccxt_feed import CcxtFeed
from manoj_bot.data.yahoo import YahooFeed

HOUR_MS = 3_600_000


def test_normalize_ohlcv():
    raw = pd.DataFrame(
        {"Open": [2, 1, 1], "High": [2, 1, 1], "Low": [2, 1, 1], "Close": [2, 1, 1.5]},
        index=pd.to_datetime(["2024-01-02", "2024-01-01", "2024-01-01"]),
    )
    out = normalize_ohlcv(raw)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert str(out.index.tz) == "UTC"
    assert out.index.is_monotonic_increasing
    assert out["close"].tolist() == [1.5, 2]  # the later duplicate wins
    with pytest.raises(ValueError, match="close"):
        normalize_ohlcv(pd.DataFrame({"open": [1], "high": [1], "low": [1]}))


def test_csv_feed_with_dates(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-01,1,2,0.5,1.5,10\n"
        "2024-01-02,1.5,2.5,1,2,20\n"
        "2024-01-03,2,3,1.5,2.5,30\n"
    )
    feed = CsvFeed(path)
    assert len(feed.history("X", "1d")) == 3
    assert feed.history("X", "1d", start="2024-01-02")["close"].tolist() == [2, 2.5]
    assert feed.history("X", "1d", end="2024-01-02")["close"].tolist() == [1.5, 2]
    assert feed.history("X", "1d", limit=1)["close"].tolist() == [2.5]


def test_csv_feed_with_epoch_milliseconds(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text("timestamp,open,high,low,close\n1704067200000,1,1,1,1\n1704070800000,2,2,2,2\n")
    data = CsvFeed(path).history("X", "1h")
    assert data.index[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert data["volume"].tolist() == [0, 0]


def test_synthetic_feed_is_deterministic_and_valid():
    one = SyntheticFeed(seed=1).history("X", "1d", end="2024-01-01", limit=300)
    two = SyntheticFeed(seed=1).history("X", "1d", end="2024-01-01", limit=300)
    pd.testing.assert_frame_equal(one, two)
    assert len(one) == 300 and one.index[-1] == pd.Timestamp("2024-01-01", tz="UTC")
    assert (one["high"] >= one[["open", "close"]].max(axis=1)).all()
    assert (one["low"] <= one[["open", "close"]].min(axis=1)).all()
    ranged = SyntheticFeed().history("X", "1h", start="2024-01-01", end="2024-01-02")
    assert len(ranged) == 25


class FakeTicker:
    calls: list = []

    def __init__(self, symbol, frame):
        self.symbol, self.frame = symbol, frame

    def history(self, **kwargs):
        FakeTicker.calls.append((self.symbol, kwargs))
        return self.frame


def yahoo_frame(periods=5):
    index = pd.date_range("2024-01-01", periods=periods, freq="D", tz="Asia/Kolkata")
    values = [float(i) for i in range(periods)]
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Volume": values,
            "Dividends": 0.0,
        },
        index=index,
    )


def test_yahoo_feed():
    FakeTicker.calls = []
    feed = YahooFeed(ticker_factory=lambda symbol: FakeTicker(symbol, yahoo_frame()))
    data = feed.history("RELIANCE.NS", "1w", end="2024-01-05", limit=3)
    assert list(data.columns) == ["open", "high", "low", "close", "volume"]
    assert data.index[0] == pd.Timestamp("2024-01-02 18:30", tz="UTC")  # Jan 3 in IST
    assert len(data) == 3
    symbol, kwargs = FakeTicker.calls[-1]
    assert (symbol, kwargs["interval"], kwargs["auto_adjust"]) == ("RELIANCE.NS", "1wk", True)


def test_yahoo_feed_errors():
    feed = YahooFeed(ticker_factory=lambda symbol: FakeTicker(symbol, pd.DataFrame()))
    with pytest.raises(ValueError, match="timeframe"):
        feed.history("AAPL", "4h")
    with pytest.raises(ValueError, match="no 1d data"):
        feed.history("NOPE", "1d")


class FakeExchange:
    """Serves hourly candles from 2024-01-01 00:00 to `now`, `page` at a time."""

    def __init__(self, now_ms, page):
        self.now_ms, self.page, self.calls = now_ms, page, 0
        self.candles = [
            [t, 1.0, 2.0, 0.5, 1.5, 10.0] for t in range(1704067200000, now_ms, HOUR_MS)
        ]

    def milliseconds(self):
        return self.now_ms

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        return [c for c in self.candles if c[0] >= since][: min(limit, self.page)]


def test_ccxt_feed_paginates_a_date_range():
    exchange = FakeExchange(now_ms=1704067200000 + 100 * HOUR_MS, page=7)
    data = CcxtFeed(exchange=exchange).history(
        "BTC/USDT", "1h", start="2024-01-01 10:00", end="2024-01-02 09:00"
    )
    assert len(data) == 24
    assert data.index[0] == pd.Timestamp("2024-01-01 10:00", tz="UTC")
    assert data.index[-1] == pd.Timestamp("2024-01-02 09:00", tz="UTC")
    assert exchange.calls >= 4


def test_ccxt_feed_latest_bars():
    exchange = FakeExchange(now_ms=1704067200000 + 100 * HOUR_MS, page=1000)
    data = CcxtFeed(exchange=exchange).history("BTC/USDT", "1h", limit=20)
    assert len(data) == 20
    assert data.index[-1] == pd.Timestamp(exchange.candles[-1][0], unit="ms", tz="UTC")


def test_build_feed():
    assert isinstance(build_feed(DataConfig(source="synthetic")), SyntheticFeed)
    assert isinstance(build_feed(DataConfig(source="csv", path="x.csv")), CsvFeed)
