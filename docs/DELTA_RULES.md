# Trading the plan on Delta Exchange (XAUTUSD)

The mentor's rules are unchanged — see `TRADE_PLAN_DECODED.md`. This file covers
only what Delta forces you to do differently, and why.

## What Delta is

| | |
|---|---|
| Instrument | `XAUTUSD` perpetual (Tether Gold), also `PAXGUSD` — identical fees |
| Contract | **1 contract = 0.001 XAUT** (0.01 MT5 lot = $1/point = 1000 contracts) |
| Tick | 0.01 |
| Spread | ~**0.030** points (measured live) |
| Fee | **0.0001 maker AND taker** — limit orders do not help |
| Funding | ~0.005% per 8h stamp, charged on notional |
| Max leverage | 100x |

XAUT tracks spot gold at 0.983 correlation on 15m moves but trades at a widening
discount (~$13, -0.30% and growing over our sample) and runs 24/7 including
weekends. It is a proxy for gold, not gold.

## The cost, in points

Both costs are independent of position size, because fees scale with notional
and P&L scales per point:

    spread                  0.030 pts
    fee round trip          0.926 pts   = price x 0.0001 x 2
    -----------------------------------
    total per trade         0.956 pts

The mentor's gold broker charges a 0.200 spread and no commission. **Delta costs
4.8x more per trade.** Everything below follows from that one fact.

## Rule D1 — spread goes in the entry, commission does NOT go in the stop

p6 puts the broker spread into the entry and stop. That is right for a *spread*,
which is a price offset. A *commission* is a cash charge and must not move the
stop: widening the stop for it makes a stop-out cost **2.29%** against a 2.00%
target, because the trade loses the full widened distance *and* pays the fee.

    entry = 2nd candle extreme + 0.100 buffer + 0.030 spread
    stop  = p4 buffer table, unchanged
    size  = risk$ / ((R + 0.926) x 0.001)      <- cost only shrinks the position

Sized that way a stop-out costs exactly the intended percentage (verified 2.00%
at every stop distance).

## Rule D2 — minimum R. This is what makes Delta viable at all

    fee as a share of your risk = 0.926 / R

| R (points) | fee as % of risk |
|---|---|
| 3 | **31%** |
| 5 | 19% |
| 9 | 10% |
| 15 | 6% |

A 3-point stop hands Delta a third of your risk before the trade starts. With
honest accounting and **no** minimum-R rule the strategy **loses money** on Delta.

$100 at 2% risk, 60 days (25 Jun – 24 Aug 2026), funding included:

| min R | trades | final | return | maxDD | fees | funding |
|---|---|---|---|---|---|---|
| none | 87 | $97.75 | **−2.2%** | 19.1% | $30.56 | $2.11 |
| **>= 6 pts** | **34** | **$111.57** | **+11.6%** | **8.1%** | $5.87 | $0.26 |
| >= 9 pts | 14 | $118.27 | +18.3% | 4.5% | $1.87 | $0.13 |
| >= 12 pts | 7 | $111.96 | +12.0% | 4.0% | $0.79 | $0.12 |

**Use >= 6 points.** The higher thresholds show better returns but on 14 and 7
trades — too few to mean anything, and their profit is entirely August. At 6
points you keep 34 trades, still cut fees by 80%, and halve the drawdown.

The *fee reduction* and the *drawdown reduction* are mechanical and will hold.
The exact return at each threshold is noise; do not tune on it.

## Rule D3 — size by risk, never to leverage

Leverage is a ceiling that decides where you are liquidated, not a target.

At 100x on $100, liquidation sits ~23 points away — nearer than many of this
strategy's stops — so the exchange closes the position **before the stop loss can
act**. Backtested, that wiped the account on 12 Aug even though equity had grown
to $190. At a true 2% risk, leverage lands between 3x and 30x on its own and no
trade comes near liquidation.

`delta_size.plan()` reports `liq_points` and `stop_is_safe`; never take a trade
where the stop sits beyond the liquidation distance.

## Rule D4 — 2% risk, compounded

| risk | 60-day return | maxDD |
|---|---|---|
| 1% | +8.9% | 2.2% |
| **2%** | **+18.3%** | **4.5%** |
| 3% | +28.1% | 6.8% |

(at R >= 9; the same ordering holds at R >= 6.) Compounding vs fixed-fractional
makes almost no difference at 2% and is the standard approach. Do not use 5%:
across every test in this project it took disproportionate drawdown for its
return.

## What this does not fix

Even with the minimum-R rule Delta still takes a large share of gross. The method
uses tight stops and a percentage-fee venue punishes exactly that.

| route | roughly what you keep |
|---|---|
| Delta, no filter | edge is gone |
| Delta + min R | most of it, on far fewer trades |
| spread-only spot broker | nearly all of it |

If a spot gold account with a spread-only broker and small minimum lots is
available, the same rules keep far more of what they earn. Delta's advantages are
that it is accessible, and that its 0.001 contract makes precise sizing possible
on a small account — on MT5 the 0.01 lot minimum risks ~$1/point, which a $100
account cannot size around at all.

## Sample-size warning

60 days, and the two months in it were not alike: July gold moved **19 points net
across the whole month**, August moved **578**. This is a breakout system, so it
earns in trends and treads water in ranges. Most of the profit in every table
above is August. Do not annualise these numbers.
