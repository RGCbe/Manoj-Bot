#!/usr/bin/env python3
"""
backtest.py - tests the entry models against real candles.

CONFIRMED (docs/ENTRY_RULES.md), applies to all four models:
  * orders placed when the 2nd candle closes; the 3rd candle is the only candle
    that may trigger them; not triggered by its close -> cancel
  * R = |entry - SL|, risk 1R, take profit 3R
  * entry to the nearest live opposing zone must be >= 2.5R, or no zone at all
  * Model 1 (Bullish Engulfing): 1st red, 2nd green, 1st BODY inside 2nd BODY,
    2nd candle breaks the 1st candle's LOW

ASSUMED - not yet confirmed:
  * entry price = the 2nd candle's extreme in the trade direction (+/- buffer)
  * stop loss   = the opposite extreme across both candles (-/+ buffer)
  * models 2-4 mirror model 1; Harami reverses the containment (2nd body inside
    the 1st body) and, per p9, the 2nd candle still breaks the 1st candle's
    low (bull) / high (bear)
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weak_zones_ref import detect_weak_zones, candle_color

O, H, L, C = 0, 1, 2, 3


def _body(c):
    return min(c[O], c[C]), max(c[O], c[C])


def _contains(outer, inner):
    """outer body fully contains inner body"""
    lo_o, hi_o = _body(outer)
    lo_i, hi_i = _body(inner)
    return lo_o <= lo_i and hi_o >= hi_i


def detect(model, c1, c2):
    """True when the 2-candle pattern for `model` is present."""
    if model == "bull_engulf":                       # CONFIRMED
        return (candle_color(c1) == -1 and candle_color(c2) == 1
                and _contains(c2, c1) and c2[L] < c1[L])
    if model == "bear_engulf":
        return (candle_color(c1) == 1 and candle_color(c2) == -1
                and _contains(c2, c1) and c2[H] > c1[H])
    if model == "bull_harami":
        return (candle_color(c1) == -1 and candle_color(c2) == 1
                and _contains(c1, c2) and c2[L] < c1[L])
    if model == "bear_harami":
        return (candle_color(c1) == 1 and candle_color(c2) == -1
                and _contains(c1, c2) and c2[H] > c1[H])
    raise ValueError(model)


MODELS = {
    "bull_engulf": ("Bullish Engulfing", +1),
    "bear_engulf": ("Bearish Engulfing", -1),
    "bull_harami": ("Bullish Harami",    +1),
    "bear_harami": ("Bearish Harami",    -1),
}


def live_zones_at(zones, bar):
    for z in zones:
        if z["create_idx"] <= bar and (z["death_idx"] is None or z["death_idx"] > bar):
            yield z


def zone_clearance_ok(zones, bar, entry, R, side, min_r=2.5):
    """The nearest live opposing zone must sit >= min_r*R beyond entry.
    A buy is blocked by resistance above; a sell by support below.
    No zone in the way -> allowed."""
    nearest = None
    for z in live_zones_at(zones, bar):
        if side > 0:
            if z["is_support"]:
                continue
            edge = z["bottom"]                        # near edge going up
            if edge <= entry:
                continue
            if nearest is None or edge < nearest:
                nearest = edge
        else:
            if not z["is_support"]:
                continue
            edge = z["top"]                           # near edge going down
            if edge >= entry:
                continue
            if nearest is None or edge > nearest:
                nearest = edge
    if nearest is None:
        return True, None
    return abs(nearest - entry) >= min_r * R, nearest


def run_model(candles, model, entry_buffer=0.0, sl_buffer=0.0,
              min_zone_r=2.5, tp_r=3.0, zones=None):
    if zones is None:
        zones = detect_weak_zones(candles)
    side = MODELS[model][1]
    trades = {"win": 0, "loss": 0, "open": 0}
    rej = {"zone": 0, "no_fill": 0}

    for j in range(1, len(candles) - 1):
        c1, c2 = candles[j - 1], candles[j]
        if not detect(model, c1, c2):
            continue

        if side > 0:
            entry = c2[H] + entry_buffer
            sl    = min(c1[L], c2[L]) - sl_buffer
        else:
            entry = c2[L] - entry_buffer
            sl    = max(c1[H], c2[H]) + sl_buffer
        R = abs(entry - sl)
        if R <= 0:
            continue

        ok, _ = zone_clearance_ok(zones, j, entry, R, side, min_zone_r)
        if not ok:
            rej["zone"] += 1
            continue

        third = candles[j + 1]
        filled = third[H] >= entry if side > 0 else third[L] <= entry
        if not filled:
            rej["no_fill"] += 1
            continue

        tp = entry + side * tp_r * R
        outcome = "open"
        for k in range(j + 1, len(candles)):
            b = candles[k]
            if side > 0:
                hit_sl, hit_tp = b[L] <= sl, b[H] >= tp
            else:
                hit_sl, hit_tp = b[H] >= sl, b[L] <= tp
            if hit_sl:                                # same-bar tie -> assume the loss
                outcome = "loss"; break
            if hit_tp:
                outcome = "win"; break
        trades[outcome] += 1
    return trades, rej


# --------------------------------------------------------------------------- #
#  Sequential engine - CONFIRMED: only one trade at a time.
#  A new order is only placed once the previous trade has closed.
# --------------------------------------------------------------------------- #
def run_sequential(candles, models=None, entry_buffer=0.0, sl_buffer=0.0,
                   min_zone_r=2.5, tp_r=3.0, zones=None):
    """Walk the candles in order, holding at most one position.

    While a trade is open no new order is placed, so signals that appear during
    it are skipped. When several models signal on the same bar the first one
    listed wins.
    """
    if zones is None:
        zones = detect_weak_zones(candles)
    models = models or list(MODELS)

    result = {m: {"win": 0, "loss": 0, "open": 0} for m in models}
    rej = {"zone": 0, "no_fill": 0, "busy": 0}
    log = []
    busy_until = -1                                   # bar index the open trade exits on

    for j in range(1, len(candles) - 1):
        c1, c2 = candles[j - 1], candles[j]

        for m in models:
            if not detect(m, c1, c2):
                continue
            # an order may only be placed when nothing is open
            if j + 1 <= busy_until:
                rej["busy"] += 1
                break

            side = MODELS[m][1]
            if side > 0:
                entry = c2[H] + entry_buffer
                sl    = min(c1[L], c2[L]) - sl_buffer
            else:
                entry = c2[L] - entry_buffer
                sl    = max(c1[H], c2[H]) + sl_buffer
            R = abs(entry - sl)
            if R <= 0:
                break

            ok, _ = zone_clearance_ok(zones, j, entry, R, side, min_zone_r)
            if not ok:
                rej["zone"] += 1
                break

            third = candles[j + 1]
            filled = third[H] >= entry if side > 0 else third[L] <= entry
            if not filled:
                rej["no_fill"] += 1
                break

            tp = entry + side * tp_r * R
            outcome, exit_i = "open", len(candles) - 1
            for k in range(j + 1, len(candles)):
                b = candles[k]
                if side > 0:
                    hit_sl, hit_tp = b[L] <= sl, b[H] >= tp
                else:
                    hit_sl, hit_tp = b[H] >= sl, b[L] <= tp
                if hit_sl:
                    outcome, exit_i = "loss", k; break
                if hit_tp:
                    outcome, exit_i = "win", k; break
            result[m][outcome] += 1
            busy_until = exit_i
            log.append({"model": m, "signal": j, "exit": exit_i,
                        "outcome": outcome, "R": R, "bars": exit_i - j})
            break                                     # one order per bar

    return result, rej, log


def report(result, rej, title, tp_r=3.0):
    lines = [title, "-" * len(title)]
    lines.append(f"{'model':<20}{'trades':>8}{'wins':>7}{'loss':>7}{'win%':>8}{'netR':>9}")
    TW = TL = 0
    for m, t in result.items():
        w, l = t["win"], t["loss"]
        TW += w; TL += l
        n = w + l
        wr = w / n * 100 if n else 0.0
        lines.append(f"{MODELS[m][0]:<20}{n:>8}{w:>7}{l:>7}{wr:>7.1f}%{w*tp_r-l:>+8.0f}R")
    n = TW + TL
    wr = TW / n * 100 if n else 0.0
    lines.append("-" * 59)
    lines.append(f"{'TOTAL':<20}{n:>8}{TW:>7}{TL:>7}{wr:>7.1f}%{TW*tp_r-TL:>+8.0f}R")
    lines.append(f"skipped - trade already open: {rej['busy']}")
    lines.append(f"skipped - zone too close    : {rej['zone']}")
    lines.append(f"skipped - never triggered   : {rej['no_fill']}")
    return "\n".join(lines)
