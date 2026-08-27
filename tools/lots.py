#!/usr/bin/env python3
"""
lots.py - position sizing.

From p5 of the plan: 0.01 lot moving 1 point = 1 USD, so

    1.00 lot moving 1 point = 100 USD          (VALUE_PER_POINT_PER_LOT)

which gives

    lot = risk_usd / (sl_points * 100)

Verified against all 40 rows of the course lot tables ($1000 account at 1%, 2%
and 5%). 35 of 40 match exactly when the result is rounded DOWN; the other 5
were rounded up by hand in the printed table. This module rounds DOWN, so the
loss can never exceed the intended risk.
"""

from __future__ import annotations
import math

VALUE_PER_POINT_PER_LOT = 100.0
MIN_LOT  = 0.01
LOT_STEP = 0.01


def risk_amount(balance, risk_pct):
    return balance * risk_pct / 100.0


def lot_size(balance, risk_pct, sl_points, min_lot=MIN_LOT, step=LOT_STEP,
             floor_min=False):
    """Lot for `sl_points` of stop distance, rounded DOWN to the lot step.

    By default returns 0.0 when even the minimum lot would risk more than
    intended - the trade is too wide for the account and should be skipped.

    floor_min=True takes the minimum lot anyway. On a small account that means
    the risk percentage stops being honoured: the real risk becomes whatever the
    stop happens to be. On $100 against our gold trades that is a median 7.6%
    and up to 28.8% on a single trade, so use `plan()` and watch `over_risk`.
    """
    if sl_points <= 0:
        raise ValueError("sl_points must be > 0")
    raw = risk_amount(balance, risk_pct) / (sl_points * VALUE_PER_POINT_PER_LOT)
    lots = math.floor(raw / step) * step
    lots = round(lots, 2)
    if lots >= min_lot:
        return lots
    return min_lot if floor_min else 0.0


def trade_value(lots, points):
    """Money moved by `lots` over `points`."""
    return lots * points * VALUE_PER_POINT_PER_LOT


def plan(balance, risk_pct, sl_points, tp_r=3.0, floor_min=False):
    """Full sizing for one trade.

    `risk_actual_pct` is what the trade really risks; when `floor_min` forces the
    minimum lot on a stop the account cannot afford, `over_risk` marks it and
    that figure is the one that matters, not `risk_pct`.
    """
    lots = lot_size(balance, risk_pct, sl_points, floor_min=floor_min)
    risk_actual = trade_value(lots, sl_points)
    return {
        "balance":         balance,
        "risk_pct":        risk_pct,
        "risk_target":     risk_amount(balance, risk_pct),
        "sl_points":       sl_points,
        "lots":            lots,
        "risk_actual":     risk_actual,
        "risk_actual_pct": risk_actual / balance * 100 if balance else 0.0,
        "over_risk":       risk_actual > risk_amount(balance, risk_pct) + 1e-9,
        "tp_points":       sl_points * tp_r,
        "reward":          trade_value(lots, sl_points * tp_r),
        "skip":            lots == 0.0,
    }


def table(balance, risk_pct, max_sl=20, tp_r=3.0):
    rows = []
    for sl in range(1, max_sl + 1):
        p = plan(balance, risk_pct, sl, tp_r)
        rows.append((sl, p["risk_target"], p["lots"], p["reward"]))
    return rows


if __name__ == "__main__":
    for pct in (2, 5):
        print(f"\n$1000 account - risk {pct}%  (${1000*pct/100:.0f})")
        print(f"{'SL POINT':>9}{'RISK $':>9}{'LOT':>8}{'REWARD 1:3':>12}")
        for sl, r, l, rew in table(1000, pct):
            print(f"{sl:>9}{r:>9.0f}{l:>8.2f}{rew:>12.0f}")

    print("\n$100 account, 5% risk, always taking the minimum lot")
    print(f"{'SL POINT':>9}{'LOT':>8}{'RISK $':>9}{'RISK %':>9}   note")
    for sl in (3, 5, 8, 10, 15, 20, 30, 37):
        p = plan(100, 5, sl, floor_min=True)
        note = "OVER the 5% target" if p["over_risk"] else ""
        print(f"{sl:>9}{p['lots']:>8.2f}{p['risk_actual']:>9.2f}"
              f"{p['risk_actual_pct']:>8.1f}%   {note}")
