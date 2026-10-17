"""Market data sources."""

from __future__ import annotations

from manoj_bot.config import DataConfig
from manoj_bot.data.base import DataFeed, normalize_ohlcv
from manoj_bot.data.csv_feed import CsvFeed
from manoj_bot.data.synthetic import SyntheticFeed


def build_feed(config: DataConfig) -> DataFeed:
    if config.source == "synthetic":
        return SyntheticFeed(seed=config.seed)
    if config.source == "csv":
        return CsvFeed(config.path)
    if config.source == "yahoo":
        from manoj_bot.data.yahoo import YahooFeed

        return YahooFeed()
    if config.source == "ccxt":
        from manoj_bot.data.ccxt_feed import CcxtFeed

        return CcxtFeed(config.exchange)
    if config.source == "dukascopy":
        from manoj_bot.data.dukascopy import DukascopyFeed

        return DukascopyFeed()
    raise ValueError(f"Unknown data source {config.source!r}")


__all__ = ["CsvFeed", "DataFeed", "SyntheticFeed", "build_feed", "normalize_ohlcv"]
