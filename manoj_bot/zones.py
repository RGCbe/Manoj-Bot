"""Weak zones: support and resistance the way the mentor marks them on a 15-minute chart.

The rules, checked against his own chart photos (Sep 25 - Oct 16, spot gold):

1. Formation - 3 candles of the same colour, each breaking the one before:
   3 green with higher highs make a support, 3 red with lower lows a resistance.
2. Anchor - the previous low or high. A support starts at the lowest low since the
   last resistance was formed, a resistance at the highest high since the last
   support was formed. Before any zone of the other kind exists, count from the
   last 3 candles of the same kind.
3. Band - from that wick to the nearest body over the same stretch: a support runs
   from the lowest low up to the lowest body, a resistance from the highest high
   down to the highest body.
4. Zones alternate support, resistance, support. A second zone of the same kind is
   allowed once the last zone has been broken.
5. Only the newest zone of each kind is kept: a new support replaces the old one.
   A zone that would overlap the live zone of its kind is not drawn.
6. A zone dies when a wick goes through its far edge, or once it is ``max_age``
   bars old (192 bars is two days of 15-minute candles).

Every zone only uses candles up to the one that formed it, so the zones are safe to
use in a backtest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

DEFAULT_MAX_AGE = 192
DEFAULT_MAX_LOOKBACK = 192


@dataclass(frozen=True)
class Zone:
    kind: str  # "support" or "resistance"
    bottom: float
    top: float
    start: pd.Timestamp  # the candle whose wick the zone is anchored on
    formed: pd.Timestamp  # the 3rd candle of the formation; the zone exists from here
    end: pd.Timestamp | None = None
    end_reason: str | None = None  # "broken", "replaced" or "expired"; None while live

    @property
    def is_support(self) -> bool:
        return self.kind == "support"


def find_zones(
    data: pd.DataFrame, max_age: int = DEFAULT_MAX_AGE, max_lookback: int = DEFAULT_MAX_LOOKBACK
) -> list[Zone]:
    """All weak zones in ``data`` (open/high/low/close columns), oldest first."""
    o, h, low, c = (data[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    times = data.index

    def colour(i: int) -> int:
        return 1 if c[i] > o[i] else (-1 if c[i] < o[i] else 0)

    def formation(a: int, support: bool) -> bool:
        if a < 0 or any(colour(i) != (1 if support else -1) for i in (a, a + 1, a + 2)):
            return False
        if support:
            return h[a + 1] > h[a] and h[a + 2] > h[a + 1]
        return low[a + 1] < low[a] and low[a + 2] < low[a + 1]

    zones: list[dict] = []
    for j in range(len(data)):
        for z in zones:
            if z["end"] is not None or j <= z["formed"]:
                continue
            if j - z["formed"] >= max_age:
                z.update(end=j, end_reason="expired")
            elif (low[j] < z["bottom"]) if z["support"] else (h[j] > z["top"]):
                z.update(end=j, end_reason="broken")

        c1 = j - 2
        if c1 < 0:
            continue
        for support in (True, False):
            if not formation(c1, support):
                continue
            last = zones[-1] if zones else None
            if last and last["support"] == support and last["end"] is None:
                continue  # zones alternate, unless the last one is already broken
            other = [z for z in zones if z["support"] != support]
            if other:
                begin = max(other[-1]["formed"], c1 - max_lookback)
            else:
                a = c1 - 3
                while a > max(c1 - max_lookback, 0) and not formation(a, support):
                    a -= 1
                begin = a + 3
            window = range(begin, j + 1)
            if support:
                anchor = min(window, key=lambda i: low[i])
                bottom, top = low[anchor], min(min(o[i], c[i]) for i in window)
            else:
                anchor = max(window, key=lambda i: h[i])
                top, bottom = h[anchor], max(max(o[i], c[i]) for i in window)
            top = max(top, bottom)
            live = [z for z in zones if z["support"] == support and z["end"] is None]
            if any(not (top < z["bottom"] or bottom > z["top"]) for z in live):
                continue
            for z in live:
                z.update(end=j, end_reason="replaced")
            zones.append(
                {
                    "support": support,
                    "bottom": bottom,
                    "top": top,
                    "anchor": anchor,
                    "formed": j,
                    "end": None,
                    "end_reason": None,
                }
            )

    return [
        Zone(
            kind="support" if z["support"] else "resistance",
            bottom=float(z["bottom"]),
            top=float(z["top"]),
            start=times[z["anchor"]],
            formed=times[z["formed"]],
            end=None if z["end"] is None else times[z["end"]],
            end_reason=z["end_reason"],
        )
        for z in zones
    ]


def zones_frame(zones: list[Zone]) -> pd.DataFrame:
    """The zones as a table, one row per zone."""
    columns = ["kind", "bottom", "top", "start", "formed", "end", "end_reason"]
    return pd.DataFrame([asdict(z) for z in zones], columns=columns)
