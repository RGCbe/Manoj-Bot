#!/usr/bin/env python3
"""
backtest.py - tests the confirmed entry rules against real candles.

Implements only what has been CONFIRMED in docs/ENTRY_RULES.md:

  Model 1 - Bullish Engulfing (buy)
    * 1st candle red, 2nd candle green
    * 1st candle's BODY inside the 2nd candle's BODY (wicks ignored)
    * 2nd candle must break the 1st candle's LOW
    * orders placed when the 2nd candle closes
    * the 3rd candle is the only candle that may trigger them
    * not triggered by the 3rd candle's close -> cancel
    * R = |entry - SL|, risk 1R, take profit 3R
    * entry to the nearest live resistance zone must be >= 2.5R, or no zone

Still ASSUMED (not yet confirmed) - both exposed as parameters:
    * entry price   = 2nd candle's high  + entry_buffer
    * stop loss     = lowest low of the two candles - sl_buffer
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weak_zones_ref import detect_weak_zones, candle_color

O, H, L, C = 0, 1, 2, 3


def is_bullish_engulfing(c1, c2):
    """1st red, 2nd green, 1st body inside 2nd body, 2nd breaks 1st low."""
    if candle_color(c1) != -1 or candle_color(c2) != 1:
        return False
    b1_lo, b1_hi = min(c1[O], c1[C]), max(c1[O], c1[C])
    b2_lo, b2_hi = min(c2[O], c2[C]), max(c2[O], c2[C])
    if not (b2_lo <= b1_lo and b2_hi >= b1_hi):      # body inside body
        return False
    return c2[L] < c1[L]                              # breaks the 1st low


def live_zones_at(zones, bar):
    for z in zones:
        if z["create_idx"] <= bar and (z["death_idx"] is None or z["death_idx"] > bar):
            yield z


def zone_clearance_ok(zones, bar, entry, R, min_r=2.5):
    """Nearest live resistance above entry must sit >= min_r * R away.
    No zone in the way -> allowed."""
    nearest = None
    for z in live_zones_at(zones, bar):
        if z["is_support"]:
            continue                                  # a buy is blocked by resistance
        edge = z["bottom"]                            # near edge = the zone's low
        if edge <= entry:
            continue                                  # already below us, not in the way
        if nearest is None or edge < nearest:
            nearest = edge
    if nearest is None:
        return True, None                             # clear road
    return (nearest - entry) >= min_r * R, nearest


def run(candles, entry_buffer=0.0, sl_buffer=0.0, min_zone_r=2.5,
        tp_r=3.0, zone_kwargs=None):
    zones = detect_weak_zones(candles, **(zone_kwargs or {}))
    trades, skipped = [], {"zone_too_close": 0, "not_triggered": 0}

    for j in range(1, len(candles) - 1):
        c1, c2 = candles[j - 1], candles[j]
        if not is_bullish_engulfing(c1, c2):
            continue

        entry = c2[H] + entry_buffer
        sl    = min(c1[L], c2[L]) - sl_buffer
        R     = entry - sl
        if R <= 0:
            continue

        ok, blocker = zone_clearance_ok(zones, j, entry, R, min_zone_r)
        if not ok:
            skipped["zone_too_close"] += 1
            continue

        third = candles[j + 1]                        # the only candle that may fill
        if third[H] < entry:
            skipped["not_triggered"] += 1
            continue

        tp = entry + tp_r * R
        # walk forward from the fill bar until SL or TP is hit
        outcome, exit_i = "open", None
        for k in range(j + 1, len(candles)):
            bar = candles[k]
            hit_sl = bar[L] <= sl
            hit_tp = bar[H] >= tp
            if hit_sl and hit_tp:                     # same bar: assume the worst
                outcome, exit_i = "loss", k
                break
            if hit_sl:
                outcome, exit_i = "loss", k
                break
            if hit_tp:
                outcome, exit_i = "win", k
                break
        trades.append({"signal_idx": j, "entry": entry, "sl": sl, "tp": tp, "R": R,
                       "outcome": outcome, "exit_idx": exit_i,
                       "bars_held": (exit_i - j) if exit_i else None,
                       "blocker": blocker})
    return trades, skipped, zones


def summarise(trades, skipped):
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    wins   = [t for t in closed if t["outcome"] == "win"]
    losses = [t for t in closed if t["outcome"] == "loss"]
    still  = [t for t in trades if t["outcome"] == "open"]
    tp_r   = (trades[0]["tp"] - trades[0]["entry"]) / trades[0]["R"] if trades else 3.0
    netR   = len(wins) * tp_r - len(losses) * 1.0
    out = []
    out.append(f"signals taken     : {len(trades)}")
    out.append(f"  wins            : {len(wins)}")
    out.append(f"  losses          : {len(losses)}")
    out.append(f"  still open      : {len(still)}")
    if closed:
        out.append(f"win rate          : {len(wins)/len(closed)*100:.1f}%  "
                   f"(break-even at {1/(1+tp_r)*100:.0f}% for 1:{tp_r:g})")
        out.append(f"net result        : {netR:+.1f}R over {len(closed)} closed trades")
        out.append(f"average hold      : {sum(t['bars_held'] for t in closed)/len(closed):.1f} bars")
    out.append(f"rejected - zone too close : {skipped['zone_too_close']}")
    out.append(f"rejected - never triggered: {skipped['not_triggered']}")
    return "\n".join(out)
