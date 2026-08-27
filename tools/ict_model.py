#!/usr/bin/env python3
"""
ict_model.py - the 4-step confirmation model (liquidity sweep -> HTF FVG
delivery -> LTF inversion -> CISD).

    Step 1  Liquidity sweep : price takes out a major high/low. No sweep, no trade.
    Step 2  HTF delivery    : price is delivering from a higher-timeframe FVG.
    Step 3  LTF inversion   : on the entry timeframe price displaces and closes
                              through an FVG.
    Step 4  CISD            : a clean body close past the run of candles that led
                              into the sweep, confirming the structural shift.

Candles are [open, high, low, close] throughout, oldest first, as in backtest.py.
"""

from __future__ import annotations

O, H, L, C = 0, 1, 2, 3


# --------------------------------------------------------------------------- #
#  Fair Value Gap - a 3-candle imbalance where candle 1 and candle 3 do not
#  overlap, leaving a window price tends to return to.
# --------------------------------------------------------------------------- #
def find_fvgs(candles, min_size=0.0):
    """[{i, side, top, bottom, size}] - `i` is the index of the 3rd candle.

    bullish: low[i] > high[i-2]  -> gap sits below price, supports it
    bearish: high[i] < low[i-2]  -> gap sits above price, caps it
    """
    out = []
    for i in range(2, len(candles)):
        a, c = candles[i - 2], candles[i]
        if c[L] > a[H]:
            size = c[L] - a[H]
            if size >= min_size:
                out.append({"i": i, "side": +1, "bottom": a[H], "top": c[L], "size": size})
        elif c[H] < a[L]:
            size = a[L] - c[H]
            if size >= min_size:
                out.append({"i": i, "side": -1, "bottom": c[H], "top": a[L], "size": size})
    return out


def fvg_at(fvgs, price, bar, side=None, max_age=None):
    """The most recent FVG containing `price` at `bar`, or None."""
    best = None
    for g in fvgs:
        if g["i"] > bar:
            break
        if side is not None and g["side"] != side:
            continue
        if max_age is not None and bar - g["i"] > max_age:
            continue
        if g["bottom"] <= price <= g["top"]:
            best = g                                   # keep the latest match
    return best


# --------------------------------------------------------------------------- #
#  Swing points and the liquidity sweep
# --------------------------------------------------------------------------- #
def swings(candles, left=2, right=2):
    """Pivot highs and lows: an extreme with `left` bars before and `right` after."""
    hi, lo = [], []
    for i in range(left, len(candles) - right):
        h = candles[i][H]
        if all(candles[j][H] < h for j in range(i - left, i)) and \
           all(candles[j][H] <= h for j in range(i + 1, i + right + 1)):
            hi.append(i)
        l = candles[i][L]
        if all(candles[j][L] > l for j in range(i - left, i)) and \
           all(candles[j][L] >= l for j in range(i + 1, i + right + 1)):
            lo.append(i)
    return hi, lo


def liquidity_sweep(candles, i, swing_hi, swing_lo, lookback=60, right=2):
    """Did bar `i` sweep a prior swing and close back inside?

    Returns (side, swept_index, level) - side +1 means a low was swept, so the
    reaction is upward; -1 means a high was swept. None when there is no sweep.
    A sweep needs the wick THROUGH the level and the close back on the near side:
    that is the stop-run, not a genuine break.
    """
    b = candles[i]
    best = None
    for p in reversed(swing_lo):
        if p > i - right - 1 or p < i - lookback:
            continue
        lvl = candles[p][L]
        if b[L] < lvl <= b[C]:                          # wicked under, closed back above
            best = (+1, p, lvl)
            break
    for p in reversed(swing_hi):
        if p > i - right - 1 or p < i - lookback:
            continue
        lvl = candles[p][H]
        if b[H] > lvl >= b[C]:                          # wicked over, closed back below
            if best is None or p > best[1]:
                best = (-1, p, lvl)
            break
    return best


# --------------------------------------------------------------------------- #
#  Displacement and CISD
# --------------------------------------------------------------------------- #
def displacement(candles, i, side, atr_win=20, min_mult=1.5):
    """A decisive candle in `side`: body at least `min_mult` x the recent average
    range, closing in that direction."""
    b = candles[i]
    body = abs(b[C] - b[O])
    lo = max(0, i - atr_win)
    if i <= lo:
        return False
    atr = sum(candles[k][H] - candles[k][L] for k in range(lo, i)) / (i - lo)
    if atr <= 0:
        return False
    directional = (b[C] > b[O]) if side > 0 else (b[C] < b[O])
    return directional and body >= min_mult * atr


def cisd(candles, i, side, sweep_idx):
    """Change In State of Delivery.

    Take the run of candles running into the sweep that were delivering the OTHER
    way (red before an up-move, green before a down-move) and require a clean body
    close past the start of that run - price is now being delivered the new way.
    """
    j = sweep_idx
    want = -1 if side > 0 else 1                        # colour of the run into the sweep
    start = None
    while j >= 1:
        c = candles[j]
        col = 1 if c[C] > c[O] else (-1 if c[C] < c[O] else 0)
        if col == want:
            start = j
            j -= 1
        else:
            break
    if start is None:
        return False, None
    level = candles[start][O]                           # open of the first candle of the run
    b = candles[i]
    ok = (b[C] > level) if side > 0 else (b[C] < level)
    return ok, level


# --------------------------------------------------------------------------- #
#  Higher timeframe
# --------------------------------------------------------------------------- #
def resample(candles, times, factor):
    """Aggregate `factor` bars into one. Returns (candles, times)."""
    out, ot = [], []
    for i in range(0, len(candles) - factor + 1, factor):
        chunk = candles[i:i + factor]
        out.append([chunk[0][O], max(c[H] for c in chunk),
                    min(c[L] for c in chunk), chunk[-1][C]])
        ot.append(times[i])
    return out, ot


# --------------------------------------------------------------------------- #
#  The full 4-step model
# --------------------------------------------------------------------------- #
def signals(candles, times, htf_factor=4, major=10, sweep_lookback=120,
            confirm_within=6, disp_mult=1.5, htf_fvg_age=40, require_htf=True,
            require_disp=True, require_cisd=True):
    """Every setup passing the four steps. Yields dicts with entry/stop/side.

    Step 1  a major swing is swept (wick through, close back inside)
    Step 2  price sits in a higher-timeframe FVG delivering the same way
    Step 3  an entry-timeframe displacement closes through an FVG
    Step 4  CISD - a body close past the run that led into the sweep

    Entry is the close of the confirming candle; the stop goes beyond the sweep
    extreme, which is the level the whole setup is predicated on.
    """
    hi, lo = swings(candles, major, major)
    fvgs = find_fvgs(candles)
    htf, htimes = resample(candles, times, htf_factor)
    htf_fvgs = find_fvgs(htf)

    out = []
    for i in range(major + 2, len(candles) - 1):
        sw = liquidity_sweep(candles, i, hi, lo, sweep_lookback, major)
        if not sw:
            continue
        side, sidx, level = sw
        sweep_extreme = candles[i][L] if side > 0 else candles[i][H]

        # Steps 2-4 must land within `confirm_within` bars of the sweep
        for k in range(i, min(i + confirm_within + 1, len(candles))):
            if require_htf:
                hb = min(k // htf_factor, len(htf) - 1)
                if not fvg_at(htf_fvgs, candles[k][C], hb, side, htf_fvg_age):
                    continue
            if require_disp and not displacement(candles, k, side, 20, disp_mult):
                continue
            if require_disp and not fvg_at(fvgs, candles[k][C], k, side, 30):
                continue                                  # displacing THROUGH an FVG
            if require_cisd:
                ok, _ = cisd(candles, k, side, sidx)
                if not ok:
                    continue
            out.append({"signal": k, "side": side, "sweep": i,
                        "entry": candles[k][C], "stop": sweep_extreme,
                        "level": level})
            break
    return out


# --------------------------------------------------------------------------- #
#  Multi-timeframe form: sweep + HTF delivery on the higher frames, the entry
#  trigger (displacement through an FVG, then CISD) on the 1-minute chart.
#  This is the model as written - steps 1-2 are context, 3-4 are the entry.
# --------------------------------------------------------------------------- #
def signals_mtf(m1, times, sweep_tf=15, htf_tf=60, major=10, sweep_lookback=120,
                confirm_min=60, disp_mult=1.5, htf_fvg_age=40,
                require_htf=True, require_disp=True, require_cisd=True):
    """m1 = 1-minute candles. sweep_tf / htf_tf are in minutes.

    confirm_min is how long after the sweep the 1m trigger may still fire.
    """
    swp, swp_t = resample(m1, times, sweep_tf)
    htf, htf_t = resample(m1, times, htf_tf)
    hi, lo = swings(swp, major, major)
    htf_fvgs = find_fvgs(htf)
    m1_fvgs = find_fvgs(m1)

    # index 1m FVGs by bar for a quick lookup
    out = []
    for si in range(major + 2, len(swp) - 1):
        sw = liquidity_sweep(swp, si, hi, lo, sweep_lookback, major)
        if not sw:
            continue
        side, sidx, level = sw
        sweep_extreme = swp[si][L] if side > 0 else swp[si][H]
        # the sweep bar ends here in 1m terms
        m1_start = (si + 1) * sweep_tf
        if m1_start >= len(m1):
            break
        for k in range(m1_start, min(m1_start + confirm_min, len(m1))):
            if require_htf:
                hb = min(k // htf_tf, len(htf) - 1)
                if not fvg_at(htf_fvgs, m1[k][C], hb, side, htf_fvg_age):
                    continue
            if require_disp:
                if not displacement(m1, k, side, 20, disp_mult):
                    continue
                if not fvg_at(m1_fvgs, m1[k][C], k, side, 30):
                    continue
            if require_cisd:
                # CISD measured on the 1m run into this displacement
                ok, _ = cisd(m1, k, side, max(0, k - 1))
                if not ok:
                    continue
            out.append({"signal": k, "side": side, "sweep_bar": si,
                        "entry": m1[k][C], "stop": sweep_extreme, "level": level})
            break
    return out


# --------------------------------------------------------------------------- #
#  FVG MAGNET MODEL
#
#    1. On 15m, find an FVG that price has not yet traded into. An unfilled gap
#       is a magnet - price tends to come back and rebalance it.
#    2. Drop to 1m and wait for an INVERSION FVG (IFVG) pointing at the magnet.
#       An IFVG is an FVG that price has closed through: it flips role, so a
#       bearish gap closed through from below becomes support.
#    3. Enter on the inversion, stop beyond the IFVG, target the 15m gap.
#
#  The target is a level rather than a multiple, so R:R is whatever the distance
#  to the magnet happens to be - often large, which is the point.
# --------------------------------------------------------------------------- #
def unfilled_fvgs(candles, fvgs=None, touch_fills=True):
    """Annotate each FVG with the bar that first traded into it (None = still open).

    touch_fills=True counts any wick into the gap as filling it; False requires
    price to trade fully through.
    """
    fvgs = fvgs if fvgs is not None else find_fvgs(candles)
    for g in fvgs:
        g["filled_at"] = None
        for k in range(g["i"] + 1, len(candles)):
            b = candles[k]
            if touch_fills:
                hit = b[L] <= g["top"] and b[H] >= g["bottom"]
            else:
                hit = b[L] <= g["bottom"] and b[H] >= g["top"]
            if hit:
                g["filled_at"] = k
                break
    return fvgs


def magnet_at(fvgs, bar, price, min_dist=0.0, max_dist=None):
    """The nearest still-unfilled FVG at `bar`, and the direction to it.

    Returns (side, gap) - side +1 the magnet sits above (buy toward it), -1 below.
    Nearest is used deliberately: the closest unfilled gap is the one price is
    most likely to rebalance next.
    """
    best = None
    for g in fvgs:
        if g["i"] > bar:
            break
        if g["filled_at"] is not None and g["filled_at"] <= bar:
            continue
        if g["bottom"] > price:                       # magnet above
            d = g["bottom"] - price
            side = +1
        elif g["top"] < price:                        # magnet below
            d = price - g["top"]
            side = -1
        else:
            continue                                  # price already inside it
        if d < min_dist or (max_dist is not None and d > max_dist):
            continue
        if best is None or d < best[2]:
            best = (side, g, d)
    return (best[0], best[1]) if best else (0, None)


def inversion_fvgs(candles, fvgs=None, max_age=None):
    """[{i, side, top, bottom, origin}] - FVGs price has CLOSED through, which
    flips their role. side is the direction the inverted gap now supports:
    a bearish gap closed through upward becomes +1 (support under price).
    """
    fvgs = fvgs if fvgs is not None else find_fvgs(candles)
    out = []
    for g in fvgs:
        limit = len(candles) if max_age is None else min(len(candles), g["i"] + max_age + 1)
        for k in range(g["i"] + 1, limit):
            c = candles[k][C]
            if g["side"] < 0 and c > g["top"]:        # bearish gap closed through up
                out.append({"i": k, "side": +1, "top": g["top"],
                            "bottom": g["bottom"], "origin": g["i"]})
                break
            if g["side"] > 0 and c < g["bottom"]:     # bullish gap closed through down
                out.append({"i": k, "side": -1, "top": g["top"],
                            "bottom": g["bottom"], "origin": g["i"]})
                break
    out.sort(key=lambda x: x["i"])
    return out


def magnet_signals(m1, times, htf_tf=15, min_rr=1.0, max_dist_frac=0.02,
                   ifvg_max_age=120, stop_buf_frac=0.0):
    """The full magnet model on 1m candles.

    htf_tf   - minutes per higher-timeframe candle that holds the magnet
    min_rr   - skip setups whose distance-to-magnet is less than this x the stop
    max_dist_frac - ignore magnets further than this fraction of price away
    """
    htf, _ = resample(m1, times, htf_tf)
    htf_g = unfilled_fvgs(htf)
    m1_ifvg = inversion_fvgs(m1, max_age=ifvg_max_age)

    out = []
    for iv in m1_ifvg:
        k = iv["i"]
        if k + 1 >= len(m1):
            break
        hb = min(k // htf_tf, len(htf) - 1)
        price = m1[k][C]
        side, gap = magnet_at(htf_g, hb, price, max_dist=price * max_dist_frac)
        if side == 0 or side != iv["side"]:
            continue                                   # IFVG must point at the magnet
        # stop beyond the inverted gap
        if side > 0:
            stop = iv["bottom"] * (1 - stop_buf_frac)
            target = gap["bottom"]
        else:
            stop = iv["top"] * (1 + stop_buf_frac)
            target = gap["top"]
        entry = price
        R = abs(entry - stop)
        if R <= 0:
            continue
        rr = abs(target - entry) / R
        if rr < min_rr:
            continue
        out.append({"signal": k, "side": side, "entry": entry, "stop": stop,
                    "target": target, "R": R, "rr": rr, "gap_bar": gap["i"]})
    return out
