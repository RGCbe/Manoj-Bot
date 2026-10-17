"""Technical indicators. Every indicator only looks backwards, so it is safe to backtest."""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100) using Wilder's smoothing."""
    delta = series.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    # With no losses the ratio is infinite and RSI is 100; with no movement at all it is 50.
    value = 100 - 100 / (1 + avg_gain / avg_loss)
    return value.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
