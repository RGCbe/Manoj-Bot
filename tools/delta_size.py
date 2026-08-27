#!/usr/bin/env python3
"""
delta_size.py - position sizing for Delta Exchange (XAUTUSD perpetual).

Delta trades CONTRACTS, not lots: 1 contract = 0.001 XAUT, so a $1 move in the
gold price is worth $0.001 per contract. (0.01 MT5 lot = $1/point = 1000
contracts.)

Size by RISK, never by leverage. Leverage is a ceiling that decides where the
exchange liquidates you, not a target to fill:

    contracts = risk$ / (SL points * CONTRACT_VALUE)

Sizing to full leverage is what kills the account. At 100x on $100 liquidation
sits ~23 points away, nearer than many of this strategy's stops, so the position
is closed by margin call before the stop loss can act - in the August backtest
that wiped the account on 12 Aug even though equity had grown to $190.
`plan()` therefore reports liq_points and flags stop_is_safe.
"""

from __future__ import annotations

CONTRACT_VALUE = 0.001        # XAUT per contract
MAINT_MARGIN   = 0.005        # 0.5% maintenance margin
TAKER_FEE      = 0.0001       # 0.01% per side
MIN_CONTRACTS  = 1


def contracts_for(balance, risk_pct, sl_points, contract_value=CONTRACT_VALUE):
    """Contracts to risk `risk_pct` of balance over `sl_points` of stop."""
    if sl_points <= 0:
        raise ValueError("sl_points must be > 0")
    risk = balance * risk_pct / 100.0
    return risk / (sl_points * contract_value)


def plan(balance, risk_pct, sl_points, price, max_leverage=None, tp_r=3.0):
    """Full sizing for one Delta trade, with the liquidation check."""
    n = contracts_for(balance, risk_pct, sl_points)
    n = max(MIN_CONTRACTS, int(n))            # whole contracts, rounded down

    notional = n * CONTRACT_VALUE * price
    leverage = notional / balance if balance else float("inf")
    capped = False
    if max_leverage and leverage > max_leverage:
        n = int(balance * max_leverage / (CONTRACT_VALUE * price))
        n = max(MIN_CONTRACTS, n)
        notional = n * CONTRACT_VALUE * price
        leverage = notional / balance if balance else float("inf")
        capped = True

    per_point = n * CONTRACT_VALUE
    risk_usd  = per_point * sl_points
    fees      = notional * TAKER_FEE * 2
    # equity is gone once it falls to the maintenance requirement
    liq_points = (balance - notional * MAINT_MARGIN) / per_point if per_point else 0.0

    return {
        "contracts":     n,
        "notional":      notional,
        "leverage":      leverage,
        "leverage_capped": capped,
        "per_point":     per_point,
        "risk_usd":      risk_usd,
        "risk_pct":      risk_usd / balance * 100 if balance else 0.0,
        "fees_roundtrip": fees,
        "fees_pct_of_risk": fees / risk_usd * 100 if risk_usd else 0.0,
        "liq_points":    liq_points,
        # the stop must be reached before the exchange liquidates us
        "stop_is_safe":  liq_points > sl_points,
        "reward":        per_point * sl_points * tp_r,
    }


if __name__ == "__main__":
    bal, pct, price = 100.0, 2.0, 4629.0
    print(f"Delta XAUTUSD - ${bal:.0f} account, {pct}% risk per trade\n")
    print(f"{'SL pts':>7}{'contracts':>11}{'$/point':>9}{'risk $':>8}{'risk %':>8}"
          f"{'lev':>7}{'liq pts':>9}{'fees %risk':>11}  safe?")
    for sl in (3, 5, 8.7, 10, 15, 20, 25.4, 37.6):
        p = plan(bal, pct, sl, price)
        print(f"{sl:>7}{p['contracts']:>11}{p['per_point']:>9.3f}{p['risk_usd']:>8.2f}"
              f"{p['risk_pct']:>7.1f}%{p['leverage']:>6.1f}x{p['liq_points']:>9.1f}"
              f"{p['fees_pct_of_risk']:>10.1f}%  {'yes' if p['stop_is_safe'] else 'NO'}")
    print("\nAt 2% risk the position never approaches liquidation: the stop is always")
    print("reached first, which is the whole point of sizing by risk.")


def cost_points(price, spread=0.0, taker=TAKER_FEE):
    """Dealing cost of a round trip, expressed in price points.

    The fee is a share of notional and the P&L is per point, so the two scale
    together and the cost in points is independent of position size:

        fee_points = price * taker * 2

    Fold this into the stop (p6 does the same with the broker spread) so that R
    is the all-in risk. Sized that way a stop-out costs exactly the intended
    percentage instead of that percentage plus commission - which on August's
    Delta data is the difference between -0.3% and +13.4% on a $100 account.
    """
    return spread + price * taker * 2
