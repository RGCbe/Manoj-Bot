"""Weak-zone trades: the mentor's entry, exit and day rules on top of the weak zones.

Decoded from his trades and tested on spot gold, 15-minute candles (Jun 1 - Oct 16 2026).
Times are India time (``ZoneRules.tz``).

Direction
1. The trading day starts at ``session_start`` (06:00). The first resistance that breaks
   that day opens the buy side, the first support that breaks opens the sell side. Both
   sides can open on the same day.
2. Until a zone breaks that day, the side of the last break before it is the one allowed.
   A candle that breaks a support and a resistance at once opens both sides, and carries
   over the side it closed on (green: buy, red: sell).

Entry
3. Two closed candles make a bullish or bearish engulfing or harami. Bodies are compared
   with ``body_tolerance`` of slack, and the 2nd candle must break the 1st candle's low
   (buy) or high (sell).
4. A buy stop goes ``entry_offset`` above the 2nd candle's high (a sell stop below its low).
   The stop-loss sits beyond the lower low (higher high) of the two candles plus a buffer
   that grows with the stop distance. Only the next candle may fill the order.
5. For a buy, the nearest resistance above the entry must be at least ``min_room`` R away;
   for a sell, the nearest support below. Broken zones and zones younger than
   ``zone_min_age`` candles do not count.

Filters
6. The 2nd candle closes between ``session_start`` and ``session_end`` (06:00-22:00).
7. No trade with a stop wider than ``max_stop`` points.
8. One trade at a time; at most ``max_trades`` a day and ``max_trades_thursday`` on Thursday.
9. When the day's first trade ends in profit the bot stops for the day.

Exit
10. A third of the position closes at 1R, 2R and 3R. Once 2R is reached the stop moves to
    1R. If a candle reaches both the stop and a target, the stop is assumed to come first.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, fields

import numpy as np
import pandas as pd

from manoj_bot.zones import Zone, find_zones

# (largest stop distance in points, buffer added beyond the candles)
STOP_BUFFERS = ((5, 0.5), (10, 1.0), (20, 1.5), (30, 2.0), (40, 3.0), (50, 4.0))
WIDEST_BUFFER = 5.0
TARGETS = (1, 2, 3)  # R multiples; an equal share of the position closes at each
PATTERNS = (  # name, side, True if the 2nd body engulfs the 1st (else the 1st holds the 2nd)
    ("bullish engulfing", 1, True),
    ("bearish engulfing", -1, True),
    ("bullish harami", 1, False),
    ("bearish harami", -1, False),
)
THURSDAY = 3


@dataclass(frozen=True)
class ZoneRules:
    tz: str = "Asia/Kolkata"
    session_start: int = 6  # hour; the trading day starts here too
    session_end: int = 22
    body_tolerance: float = 0.2
    entry_offset: float = 0.3  # 0.1 past the candle plus 0.2 spread
    max_stop: float = 15.0
    min_room: float = 2.5
    zone_min_age: int = 4  # candles
    max_trades: int = 3
    max_trades_thursday: int = 1
    rest_after_first_win: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.session_start < self.session_end <= 24:
            raise ValueError("session_start and session_end must satisfy 0 <= start < end <= 24")
        for name in ("body_tolerance", "entry_offset", "min_room"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_stop <= 0:
            raise ValueError("max_stop must be > 0")
        for name in ("zone_min_age", "max_trades", "max_trades_thursday"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class Setup:
    """A pattern the rules looked at, and whether it was traded or why not."""

    time: pd.Timestamp  # the 2nd candle
    side: str  # "buy" or "sell"
    pattern: str
    entry: float
    stop: float
    status: str  # "traded" or the reason it was skipped


@dataclass(frozen=True)
class ZoneTrade:
    side: str
    pattern: str
    signal_time: pd.Timestamp  # the 2nd candle of the pattern
    entry_time: pd.Timestamp
    entry: float
    stop: float
    risk: float  # entry to stop in price points: 1R
    exit_time: pd.Timestamp
    result_r: float
    # "win" (3R), "trailed" (2R then back to 1R), "partial" (1R then the stop),
    # "loss", or "open" when the data ends first (marked at the last close)
    outcome: str


def stop_buffer(points: float) -> float:
    return next((buffer for upper, buffer in STOP_BUFFERS if points <= upper), WIDEST_BUFFER)


def zone_trades(
    data: pd.DataFrame, rules: ZoneRules | None = None, zones: list[Zone] | None = None
) -> tuple[list[ZoneTrade], list[Setup]]:
    """Replay the rules over ``data`` (open/high/low/close, UTC index), oldest first.

    ``zones`` defaults to ``find_zones(data)``. Returns the trades and every setup seen.
    """
    rules = rules or ZoneRules()
    zones = find_zones(data) if zones is None else zones
    o, h, low, c = (data[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    times = data.index
    local = times.tz_convert(rules.tz)
    day = (local - pd.Timedelta(hours=rules.session_start)).date
    position = {ts: i for i, ts in enumerate(times)}
    indexed = [
        (z, position[z.formed], None if z.end is None else position[z.end]) for z in zones
    ]  # (zone, formed index, end index)
    # Side each break opens: a broken resistance opens buys, a broken support sells.
    breaks = sorted(
        (position[z.end], -1 if z.is_support else 1) for z in zones if z.end_reason == "broken"
    )
    both = {i for i, n in Counter(i for i, _ in breaks).items() if n > 1}

    def colour(i: int) -> int:
        return 1 if c[i] > o[i] else (-1 if c[i] < o[i] else 0)

    def body(i: int) -> tuple[float, float]:
        return min(o[i], c[i]), max(o[i], c[i])

    def pattern(j: int) -> tuple[str, int] | None:
        for name, side, engulf in PATTERNS:
            if colour(j - 1) != -side or colour(j) != side:
                continue
            (out_lo, out_hi), (in_lo, in_hi) = (
                (body(j), body(j - 1)) if engulf else (body(j - 1), body(j))
            )
            tol = rules.body_tolerance
            if not (out_lo - tol <= in_lo and out_hi + tol >= in_hi):
                continue
            if (low[j] < low[j - 1]) if side > 0 else (h[j] > h[j - 1]):
                return name, side
        return None

    def room(j: int, side: int, entry: float, risk: float) -> bool:
        edges = [
            z.bottom if side > 0 else z.top
            for z, formed, end in indexed
            if formed <= j - rules.zone_min_age
            and (end is None or end > j)
            and z.is_support == (side < 0)
        ]
        ahead = (
            [e - entry for e in edges if e > entry]
            if side > 0
            else [entry - e for e in edges if e < entry]
        )
        return not ahead or min(ahead) >= rules.min_room * risk

    trades: list[ZoneTrade] = []
    setups: list[Setup] = []
    busy_until, count, resting = -1, {}, set()
    next_break, last_side, opened, opened_day = 0, 0, set(), None
    for j in range(1, len(data) - 1):
        if day[j] != opened_day:
            opened_day, opened = day[j], set()
        while next_break < len(breaks) and breaks[next_break][0] < j:
            i, side = breaks[next_break]
            if day[i] == day[j]:
                opened.add(side)
            last_side = colour(i) if i in both else side
            next_break += 1

        found = pattern(j)
        if found is None:
            continue
        name, side = found
        if side > 0:
            entry, extreme = h[j] + rules.entry_offset, min(low[j - 1], low[j])
            stop = extreme - stop_buffer(entry - extreme)
        else:
            entry, extreme = low[j] - rules.entry_offset, max(h[j - 1], h[j])
            stop = extreme + stop_buffer(extreme - entry)
        risk = abs(entry - stop)
        limit = rules.max_trades_thursday if local[j].weekday() == THURSDAY else rules.max_trades

        if not rules.session_start <= local[j].hour < rules.session_end:
            status = "outside trading hours"
        elif j + 1 <= busy_until:
            status = "in a trade"
        elif day[j] in resting:
            status = "resting: first trade won"
        elif count.get(day[j], 0) >= limit:
            status = "daily trade limit"
        elif risk > rules.max_stop:
            status = "stop too wide"
        elif not (side in opened or (not opened and side == last_side)):
            status = "side not open"
        elif not room(j, side, entry, risk):
            status = "no room to the zone"
        elif not ((h[j + 1] >= entry) if side > 0 else (low[j + 1] <= entry)):
            status = "not filled"
        else:
            status = "traded"
            exit_i, result, outcome = _manage(h, low, c, j + 1, side, entry, risk, stop)
            trades.append(
                ZoneTrade(
                    side="buy" if side > 0 else "sell",
                    pattern=name,
                    signal_time=times[j],
                    entry_time=times[j + 1],
                    entry=float(entry),
                    stop=float(stop),
                    risk=float(risk),
                    exit_time=times[exit_i],
                    result_r=float(result),
                    outcome=outcome,
                )
            )
            busy_until = exit_i
            count[day[j]] = count.get(day[j], 0) + 1
            if rules.rest_after_first_win and count[day[j]] == 1 and result > 0:
                resting.add(day[j])
        setups.append(
            Setup(times[j], "buy" if side > 0 else "sell", name, float(entry), float(stop), status)
        )
    return trades, setups


def _manage(h, low, c, fill, side, entry, risk, stop) -> tuple[int, float, str]:
    """Scale out at TARGETS from the fill candle on: (exit index, result in R, outcome)."""
    targets = [entry + side * m * risk for m in TARGETS]
    share = 1 / len(TARGETS)
    hit, result, stop_r = 0, 0.0, -1.0
    for k in range(fill, len(h)):
        if (low[k] <= stop) if side > 0 else (h[k] >= stop):
            outcome = "loss" if hit == 0 else ("trailed" if stop_r > 0 else "partial")
            return k, result + (1 - hit * share) * stop_r, outcome
        while hit < len(targets) and (
            (h[k] >= targets[hit]) if side > 0 else (low[k] <= targets[hit])
        ):
            result += share * TARGETS[hit]
            hit += 1
            if hit >= 2:
                stop, stop_r = targets[hit - 2], TARGETS[hit - 2]
        if hit == len(targets):
            return k, result, "win"
    last = len(h) - 1
    return last, result + (1 - hit * share) * side * (c[last] - entry) / risk, "open"


def trades_frame(trades: list[ZoneTrade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(t) for t in trades], columns=[f.name for f in fields(ZoneTrade)])


def setups_frame(setups: list[Setup]) -> pd.DataFrame:
    return pd.DataFrame([asdict(s) for s in setups], columns=[f.name for f in fields(Setup)])


def summarize(trades: list[ZoneTrade]) -> dict[str, float]:
    """Totals in R: trades, wins, win rate, net, worst drop from a peak, longest losing run."""
    r = np.array([t.result_r for t in trades], dtype=float)
    equity = np.cumsum(r)
    drop = float((np.maximum.accumulate(np.r_[0.0, equity])[1:] - equity).max()) if len(r) else 0.0
    run = longest = 0
    for value in r:
        run = run + 1 if value <= 0 else 0
        longest = max(longest, run)
    return {
        "trades": len(r),
        "wins": int((r > 0).sum()),
        "win_rate": float((r > 0).mean()) if len(r) else 0.0,
        "net_r": float(r.sum()),
        "avg_r": float(r.mean()) if len(r) else 0.0,
        "max_drawdown_r": drop,
        "longest_losing_run": longest,
    }
