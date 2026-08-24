# Entry rules — working spec

Being confirmed one condition at a time. Nothing here is implemented yet.
Legend: ✅ confirmed · ❓ open question

## R — the unit everything is measured in ✅

**R = the distance between Entry and Stop Loss.** That is the whole definition,
and it applies everywhere: all four models, every distance, every target.

Consequences:

| Quantity | In R | Note |
|----------|------|------|
| Risk on the trade | **1R** | by definition — the SL sits exactly 1R from entry |
| Weak-zone clearance | **>= 2.5R** | entry to the zone's near edge, else no trade |
| Target (TP) | **3R** | fixed at 3R for all four models — "1:3 fixed" (p4 / p12) |

Worked example — entry 2650.00, SL 2642.00:

| Level | Price | Distance |
|-------|-------|----------|
| Target (3R) | 2674.90 | +24.90 |
| Zone must be at or beyond (2.5R) | 2670.75 | +20.75 |
| Entry | 2650.00 | - |
| Stop loss (1R) | 2642.00 | -8.30 |

R = 8.30 points. Risk 8.30 to make 24.90.

## Universal order mechanics ✅ (applies to all 4 models)

1. When the **2nd candle closes**, place **Entry and Stop Loss as pending orders**.
2. The **3rd candle** is the only candle that may trigger the entry.
3. If it has not triggered by the **close of the 3rd candle**, **cancel the order**.
4. **Take profit = 3R**, fixed, for all four models.

## Weak-zone marking ✅ (updated)

- **Anchor lookback: 8 candles** before the 1st candle of the formation.
- **Zones expire after 2 days** — 192 bars on the 15-minute chart. A zone that
  has neither been broken nor expired stays live.

## Weak-zone clearance check ✅ (applies to all 4 models)

Run this **after** the stop loss is calculated, since it is measured in R:

1. Measure the distance from **entry to the weak zone's near edge** (the zone low
   for a buy — the first edge price would reach).
2. **>= 2.5R** -> place the pending order.
3. **No zone in the way** -> place the pending order.
4. **Closer than 2.5R** -> no trade.

The idea: if a zone sits closer than 2.5, price meets that obstacle before the
trade can reach its target, so the setup is not worth taking.

## Directional bias — a zone break sets the NEXT ENTRY ✅ (applies to all 4 models)

A weak-zone break sets the direction of **the next entry only**:

- Break on the **buy side** (a resistance broken up) -> **the next entry is a BUY**.
- Break on the **sell side** (a support broken down) -> **the next entry is a SELL**.

**This is not a bias for the rest of the day.** Once that entry is taken the
direction is spent; nothing more is traded until the next zone break arms a new
one. If two breaks happen with no entry between them, the later one is in force.

"Break" here is a zone death (README rule 5): a support dies on a sell-side break,
a resistance dies on a buy-side break — so the death direction **is** the break
direction.

Measured both ways on August gold, the "next entry only" reading is clearly the
right one — it takes **26 August trades on spot against the mentor's 27**, where
treating the first break as a whole-day lock took 43. On Delta XAUT it lifts the
win rate from 37.5% to **47.9%** (+32R -> +44R).

## The 4 models

| # | Model | Direction |
|---|-------|-----------|
| 1 | Bullish Engulfing | buy |
| 2 | Bearish Engulfing | sell |
| 3 | Bullish Harami | buy |
| 4 | Bearish Harami | sell |

### 1. Bullish Engulfing → BUY

| Item | Rule | State |
|------|------|-------|
| Formation | 1st candle red, 2nd candle green | ✅ |
| Body rule | 1st candle's **body** inside the 2nd candle's **body** (wicks ignored) | ✅ |
| Confirmation | 2nd candle must break the 1st candle's **low** | ✅ |
| Orders | Placed at 2nd candle close, live for the 3rd candle only | ✅ |
| Zone clearance | Entry to weak-zone low must be >= 2.5R, or no zone present | ✅ |
| Take profit | 3R | ✅ |
| Entry price | At the 2nd candle's high + buffer 0.100 + spread 0.200 = 0.3 point (from p6) | ❓ not yet confirmed |
| Stop loss | Low of both candles + 0.3 spread + 7 point + 1 point per table = 8.3 (from p6) | ❓ not yet confirmed |

### 2. Bearish Engulfing → SELL
Not yet reviewed.

### 3. Bullish Harami → BUY
Not yet reviewed.

### 4. Bearish Harami → SELL
Not yet reviewed.

## Open questions

- Entry order type: does the entry sit **above** price (buy stop) or below it (buy limit)?
- Harami confirmation (p9): the 2nd candle sits inside the 1st, so does its **wick**
  break the 1st candle's low/high?
- Do these patterns only fire **at a weak zone**, or anywhere on the chart?
  Tested: a hard "only at an opposing zone" filter is **wrong** — the Aug 5 winning
  buy fired in open space (no support at entry), so requiring a zone kills winners
  too. Entries fire anywhere; the zone only feeds the 2.5R clearance check.

## Benchmark: the mentor's August on gold

| | trades | wins | losses | win rate | net |
|---|---|---|---|---|---|
| **Mentor** (August) | 27 | 16 | 11 | **59.3%** | **+37R** |
| Bot — spot, August only | 26 | 9 | 17 | 34.6% | +10R |
| Bot — Delta XAUT (Jul 25 - Aug 24) | 48 | 23 | 25 | 47.9% | +44R |

The **trade count now matches** (26 vs 27 in August) — the remaining gap is win
rate, i.e. entry/exit mechanics rather than trade selection.

Feeds differ: Dukascopy spot XAUUSD vs Delta's XAUT (Tether Gold) perpetual,
which tracks spot with 0.983 correlation on 15m moves but trades at a widening
~$13 (-0.30%) discount and runs 24/7 including weekends. The mentor trades
TradingView / FOREX.com spot — a third feed again, which shifts wicks and
candle colours and so the exact formations.

This is the target to reproduce. The gap is not a tuning gap - a 59% win rate
at 1:3 is a different system from what is currently implemented, and no session
window, SL buffer or target setting tested so far gets close to both the trade
count and the win rate at once. The first-break bias (above) is confirmed and
helps, but entries still win only ~30% (barely above the 25% break-even for a 3R
target) — entry **quality** (p11 NOT-TRADE conditions) is the remaining lever,
not direction.

An earlier note here claimed a 06:00-10:30 IST window reproduced the mentor's
count. That was wrong: the 16 was the mentor's **wins**, not the total. Session
windows tested against the real target of 27 trades:

| Window timezone | Aug trades | win rate |
|---|---|---|
| UTC | 9 | 33.3% |
| IST (UTC+5:30) | 16 | 6.2% |
| London | 10 | 30.0% |
| New York | 8 | 12.5% |
| Tokyo | 7 | 42.9% |

None land near 27 trades at 59%.

## Conditions still to cover

The plan has many more conditions (p11 "NOT TRADE", p12 rules focus, 1:3 target,
weak point 1:2.5+, risk management from p4-p5). Being worked through one at a time.
