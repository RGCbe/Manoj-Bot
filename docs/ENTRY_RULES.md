# Entry rules — working spec

Being confirmed one condition at a time. Nothing here is implemented yet.
Legend: ✅ confirmed · ❓ open question

## Universal order mechanics ✅ (applies to all 4 models)

1. When the **2nd candle closes**, place **Entry and Stop Loss as pending orders**.
2. The **3rd candle** is the only candle that may trigger the entry.
3. If it has not triggered by the **close of the 3rd candle**, **cancel the order**.

## Weak-zone clearance check ✅ (applies to all 4 models)

Run this **after** the stop loss is calculated, since it is measured in R:

1. Measure the distance from **entry to the weak zone's near edge** (the zone low
   for a buy — the first edge price would reach).
2. **>= 2.5** -> place the pending order.
3. **No zone in the way** -> place the pending order.
4. **Closer than 2.5** -> no trade.

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
| Zone clearance | Entry to weak-zone low must be >= 2.5, or no zone present | ✅ |
| Entry price | At the 2nd candle's high + buffer 0.100 + spread 0.200 = 0.3 point (from p6) | ❓ not yet confirmed |
| Stop loss | Low of both candles + 0.3 spread + 7 point + 1 point per table = 8.3 (from p6) | ❓ not yet confirmed |

### 2. Bearish Engulfing → SELL
Not yet reviewed.

### 3. Bullish Harami → BUY
Not yet reviewed.

### 4. Bearish Harami → SELL
Not yet reviewed.

## Open questions

- **What R means when sizing the stop.** "1R = the distance between entry and SL",
  but the ratio is given as "risk 2 : reward 3". Those only fit together if the
  unit in "2:3" is something smaller than the entry-to-SL distance. Needs pinning
  down before the SL/target code is written.
- Is the 2.5 clearance measured in R, or in percent (p4 writes "2.5% and above")?
- Entry order type: does the entry sit **above** price (buy stop) or below it (buy limit)?
- Harami confirmation (p9): the 2nd candle sits inside the 1st, so does its **wick**
  break the 1st candle's low/high?
- Do these patterns only fire **at a weak zone**, or anywhere on the chart?

## Conditions still to cover

The plan has many more conditions (p11 "NOT TRADE", p12 rules focus, 1:3 target,
weak point 1:2.5+, risk management from p4-p5). Being worked through one at a time.
