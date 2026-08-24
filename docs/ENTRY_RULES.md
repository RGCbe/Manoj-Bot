# Entry rules — working spec

Being confirmed one condition at a time. Nothing here is implemented yet.
Legend: ✅ confirmed · ❓ open question

## Universal order mechanics ✅ (applies to all 4 models)

1. When the **2nd candle closes**, place **Entry and Stop Loss as pending orders**.
2. The **3rd candle** is the only candle that may trigger the entry.
3. If it has not triggered by the **close of the 3rd candle**, **cancel the order**.

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

## Conditions still to cover

The plan has many more conditions (p11 "NOT TRADE", p12 rules focus, 1:3 target,
weak point 1:2.5+, risk management from p4-p5). Being worked through one at a time.
