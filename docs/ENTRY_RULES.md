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

## Weak-zone clearance check ✅ (applies to all 4 models)

Run this **after** the stop loss is calculated, since it is measured in R:

1. Measure the distance from **entry to the weak zone's near edge** (the zone low
   for a buy — the first edge price would reach).
2. **>= 2.5R** -> place the pending order.
3. **No zone in the way** -> place the pending order.
4. **Closer than 2.5R** -> no trade.

The idea: if a zone sits closer than 2.5, price meets that obstacle before the
trade can reach its target, so the setup is not worth taking.

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

## Session filter — strong evidence, needs confirming

The plan says "market time 6 to 10:30" (p2) but never states the timezone.
Tested against a known data point: the mentor took **16 trades on gold in
August**. Counting the bot's August gold trades inside a 06:00-10:30 window
under different timezones:

| Window timezone | Aug trades |
|---|---|
| UTC | 9 |
| **IST (UTC+5:30)** | **16** |
| New York | 8 |
| London | 10 |
| Dubai | 15 |
| Tokyo | 7 |

**IST reproduces the count exactly**, and it is the trader's own timezone. That
is good evidence the window is 06:00-10:30 IST, though a matching count is not
proof on its own.

Caveat: those 16 trades come out 1 win / 15 losses, which a mentor teaching the
method would not have produced. So the session filter looks right while the
entry/SL/exit rules still are not - the missing pieces (cost-to-cost, the p6/p7
buffers, the p11 NOT TRADE conditions) must change the outcomes substantially.

## Conditions still to cover

The plan has many more conditions (p11 "NOT TRADE", p12 rules focus, 1:3 target,
weak point 1:2.5+, risk management from p4-p5). Being worked through one at a time.
