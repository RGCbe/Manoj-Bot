#!/usr/bin/env python3
"""
backtest.py - tests the entry models against real candles.

All four models, confirmed against the full plan (docs/TRADE_PLAN_DECODED.md):
  * orders placed when the 2nd candle closes; the 3rd candle is the only candle
    that may trigger them; not triggered by its close -> cancel        (p6, p10)
  * body-to-body containment, wicks ignored                            (p2)
  * the 2nd candle must break the 1st candle's low (bull) / high (bear)(p9)
  * entry = 2nd candle's extreme + 0.100 buffer + broker spread        (p6, p7)
  * SL    = opposite extreme across both candles -/+ a buffer that scales with
    the raw stop distance (SL_BUFFER_TABLE)                            (p4, p6)
  * R = |entry - SL|, risk 1R, take profit 3R - the TP distance is three
    times R                                                         (p4, p12)
  * entry to the nearest live opposing zone must be >= 2.5R, or no zone (p4, p12)
  * a weak-zone break arms the direction of the NEXT ENTRY only        (p10)
  * cost to cost: the candle after entry is the opposite colour and fails to
    break the entry candle -> the move died, so give up the 3R target and
    take a small profit, exiting at +0.5R once price returns to it. The stop
    still applies while waiting.                                     (p11, p12)
  * price stalling in the 1R-2R band for 1-2 hours -> take 1R          (mentor)
  * scale-out (`scale_out=[1,2,3]`): a third of the position closes at 1R, a
    third at 2R, a third at 3R. Caps the win at +2R but pays on every trade
    that reaches 1R, which is what carries a rangebound month.        (mentor)
  * `scale_trail`: the stop follows one level behind, so reaching 2R moves it
    to 1R and the last third can no longer lose.                      (mentor)
  * dealing cost is folded into the stop, so R is the ALL-IN risk. p6 does
    this with the broker spread; on a percentage-fee venue the commission
    belongs there too - `cost_points`. A stop-out then costs exactly the
    intended risk, and the position is sized correctly rather than paying
    fees on top of a full-size loss.

Open: the session window ("market time 6 to 10.30", p2) currently costs win rate
rather than adding it - see docs/TRADE_PLAN_DECODED.md.
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


# --------------------------------------------------------------------------- #
#  Directional bias - CONFIRMED (docs/ENTRY_RULES.md):
#  a weak-zone break sets the direction of THE NEXT ENTRY ONLY.
#    break on the buy side (a resistance broken up)   -> next entry is a BUY
#    break on the sell side (a support broken down)   -> next entry is a SELL
#  It is NOT a bias for the rest of the day: once that entry is taken the
#  direction is spent, and nothing is traded until the next zone break arms a
#  new one. Two breaks with no entry between them -> the later one is in force.
# --------------------------------------------------------------------------- #
import datetime as _dt

_IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


# --------------------------------------------------------------------------- #
#  Stop-loss buffer table - CONFIRMED (p4 "Buffer Points stop loss").
#  The buffer added beyond the stop is not fixed: it scales with the raw
#  entry-to-stop distance. p6's worked example uses it - a 7 point raw distance
#  falls in the 06-10 band -> 1 point, giving 7 + 1 + 0.3 = R 8.3.
# --------------------------------------------------------------------------- #
SL_BUFFER_TABLE = [(5, 0.5), (10, 1.0), (20, 1.5), (30, 2.0),
                   (40, 3.0), (50, 4.0), (60, 5.0)]


def sl_buffer_for(points):
    """Stop-loss buffer for a raw stop distance of `points` (p4 table).
    Beyond the last band the widest buffer is kept."""
    for upper, buf in SL_BUFFER_TABLE:
        if points <= upper:
            return buf
    return SL_BUFFER_TABLE[-1][1]


def break_events(zones):
    """{bar_index: +1 buy-side break / -1 sell-side break}.

    A zone dies when price breaks through it (weak_zones_ref), so the death is
    the break: a resistance dying means price broke UP through it, a support
    dying means price broke DOWN through it.
    """
    out = {}
    for z in zones:
        if z["death_idx"] is not None:
            out.setdefault(z["death_idx"], +1 if not z["is_support"] else -1)
    return out


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
                   min_zone_r=2.5, tp_r=3.0, zones=None,
                   times=None, daily_bias=False, anchor_hours=4,
                   use_sl_table=False, cost_points=0.0, c2c_bars=None, c2c_take=0.5,
                   stall_bars=None, stall_lo=1.0, stall_hi=2.0, stall_take=1.0,
                   scale_out=None, scale_trail=False, scale_trail_be=False):
    """Walk the candles in order, holding at most one position.

    While a trade is open no new order is placed, so signals that appear during
    it are skipped. When several models signal on the same bar the first one
    listed wins.

    daily_bias=True applies the weak-zone-break direction rule: a break arms the
    direction of the NEXT entry only, and taking that entry spends it.
    """
    if zones is None:
        zones = detect_weak_zones(candles)
    models = models or list(MODELS)

    breaks = break_events(zones) if daily_bias else {}
    armed = None                                      # direction the next entry must take

    result = {m: {"win": 0, "loss": 0, "open": 0, "costtocost": 0, "stall": 0, "partial": 0, "trailed": 0} for m in models}
    rej = {"zone": 0, "no_fill": 0, "busy": 0, "bias": 0}
    log = []
    busy_until = -1                                   # bar index the open trade exits on

    for j in range(1, len(candles) - 1):
        # a break on the previous bar arms the direction for the next entry
        if daily_bias and (j - 1) in breaks:
            armed = breaks[j - 1]
        c1, c2 = candles[j - 1], candles[j]

        for m in models:
            if not detect(m, c1, c2):
                continue
            # an order may only be placed when nothing is open
            if j + 1 <= busy_until:
                rej["busy"] += 1
                break

            side = MODELS[m][1]
            # a zone break arms the next entry's direction; no armed break -> no trade
            if daily_bias and (armed is None or side != armed):
                rej["bias"] += 1
                break
            if side > 0:
                entry = c2[H] + entry_buffer
                raw   = min(c1[L], c2[L])
                # p4 table: the stop buffer scales with the raw stop distance
                buf   = sl_buffer_for(entry - raw) if use_sl_table else sl_buffer
                sl    = raw - buf - cost_points
            else:
                entry = c2[L] - entry_buffer
                raw   = max(c1[H], c2[H])
                buf   = sl_buffer_for(raw - entry) if use_sl_table else sl_buffer
                sl    = raw + buf + cost_points
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

            fill_i = j + 1

            # ---- scale-out: close an equal slice at each R level ------------
            # 1/3 out at 1R, 1/3 at 2R, 1/3 at 3R. The stop stays put for the
            # remainder (trailing it to entry tested worse - it shakes out
            # trades that recover). Max gain +2R, max loss still -1R, but any
            # trade that reaches 1R banks something.
            if scale_out:
                slice_ = 1.0 / len(scale_out)
                levels = [entry + side * lv * R for lv in scale_out]
                banked = 0
                netR = 0.0
                cur_sl = sl
                stop_r = -1.0                     # what the rest is worth if stopped
                outcome, exit_i = "open", len(candles) - 1
                for k in range(fill_i, len(candles)):
                    b = candles[k]
                    if (b[L] <= cur_sl) if side > 0 else (b[H] >= cur_sl):
                        netR += (1.0 - banked * slice_) * stop_r
                        outcome = ("loss" if banked == 0 else
                                   ("partial" if stop_r < 0 else "trailed"))
                        exit_i = k
                        break
                    while banked < len(scale_out) and (
                            (b[H] >= levels[banked]) if side > 0 else (b[L] <= levels[banked])):
                        netR += slice_ * scale_out[banked]
                        banked += 1
                        # trail the stop one level behind: reaching 2R puts the
                        # stop at 1R, so the rest can no longer lose.
                        if scale_trail and banked >= 2:
                            cur_sl = levels[banked - 2]
                            stop_r = scale_out[banked - 2]
                        elif scale_trail_be and banked >= 1:
                            cur_sl = entry
                            stop_r = 0.0
                    if banked == len(scale_out):
                        outcome, exit_i = "win", k
                        break
                result[m][outcome] = result[m].get(outcome, 0) + 1
                busy_until = exit_i
                armed = None
                log.append({"model": m, "signal": j, "exit": exit_i,
                            "outcome": outcome, "R": R, "netR": netR,
                            "banked": banked, "bars": exit_i - j})
                break

            tp = entry + side * tp_r * R
            outcome, exit_i = "open", len(candles) - 1
            cut_to_half = False
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
                # p11/p12: "3 to 4 candle no break -> cost to cost".
                # Not through by then -> close at entry instead of risking the stop.
                # cost to cost (p11/p12): on the candle right after entry, a candle
                # of the opposite colour that fails to break the entry candle means
                # the move has died. Give up on the 3R target and take a small
                # profit instead - drop the exit to c2c_take R and wait for price
                # to come back to it (the stop still applies meanwhile).
                if c2c_bars and k == fill_i + 1 and not cut_to_half:
                    col = candle_color(b)
                    died = ((col == -1 and b[H] <= candles[fill_i][H]) if side > 0
                            else (col == 1 and b[L] >= candles[fill_i][L]))
                    if died:
                        cut_to_half = True
                if cut_to_half:
                    half = entry + side * c2c_take * R
                    if (b[H] >= half) if side > 0 else (b[L] <= half):
                        outcome, exit_i = "costtocost", k; break
                # "for 1 to 2 hours the price moves within 1R to 2R -> exit at 1R":
                # the move stalled short of target, so bank what is there.
                if stall_bars and (k - fill_i) >= stall_bars:
                    best = (max(candles[i][H] for i in range(fill_i, k + 1)) if side > 0
                            else min(candles[i][L] for i in range(fill_i, k + 1)))
                    moved = (best - entry) / R if side > 0 else (entry - best) / R
                    if stall_lo <= moved < stall_hi:
                        outcome, exit_i = "stall", k; break
            result[m][outcome] += 1
            busy_until = exit_i
            armed = None                              # entry taken -> direction spent
            log.append({"model": m, "signal": j, "exit": exit_i,
                        "outcome": outcome, "R": R, "bars": exit_i - j})
            break                                     # one order per bar

    return result, rej, log


def report(result, rej, title, tp_r=3.0, stall_take=1.0, c2c_take=0.5):
    lines = [title, "-" * len(title)]
    lines.append(f"{'model':<20}{'trades':>8}{'3R win':>7}{'loss':>7}{'profit%':>8}{'netR':>9}")
    TW = TL = TB = TS = 0
    for m, t in result.items():
        w, l, b, st = t["win"], t["loss"], t.get("costtocost", 0), t.get("stall", 0)
        TW += w; TL += l; TB += b; TS += st
        n = w + l + b + st
        prof = (w + st + b) / n * 100 if n else 0.0
        lines.append(f"{MODELS[m][0]:<20}{n:>8}{w:>7}{l:>7}{prof:>7.1f}%{w*tp_r+st*stall_take+b*c2c_take-l:>+8.1f}R")
    n = TW + TL + TB + TS
    wr = (TW + TS + TB) / n * 100 if n else 0.0
    lines.append("-" * 59)
    lines.append(f"{'TOTAL':<20}{n:>8}{TW:>7}{TL:>7}{wr:>7.1f}%{TW*tp_r+TS*stall_take+TB*c2c_take-TL:>+8.1f}R")
    if TS:
        lines.append(f"exits at {stall_take}R (stalled)     : {TS}")
    if TB:
        lines.append(f"cost-to-cost exits        : {TB}  @ +{c2c_take}R each")
    lines.append(f"skipped - trade already open: {rej['busy']}")
    lines.append(f"skipped - zone too close    : {rej['zone']}")
    lines.append(f"skipped - never triggered   : {rej['no_fill']}")
    if rej.get("bias"):
        lines.append(f"skipped - against day bias  : {rej['bias']}")
    return "\n".join(lines)
