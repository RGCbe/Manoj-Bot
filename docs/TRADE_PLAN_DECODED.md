# Trade plan — full page-by-page decode

Every page of the hand-written plan, transcribed and mapped to the code.
Legend: ✅ implemented · ⚠️ implemented but not helping in backtest · ❌ not implemented

## p1 — Class Day 3: how to find the weak point ✅

> Trade in **live market only**. How to find the weak point?
> **Minimum 3 candles in 15 min** → same colour → **must break with each other**.
> First & second candle high must be broken.
> Reversal zone weak point: **low wick → low body**.

`detect_weak_zones()`. Note "**minimum** 3" — the code matches exactly 3; runs of
4+ are covered because each consecutive triple re-tests, and alternation stops
duplicates.

## p2 — The four models, timeframe, session ✅

> Engulfing: red→green = UP, green→red = sell.
> Harami: red→small green = UP, green→small red = sell.
> **Body must [be] inside the next candle** · **only Body we need to mark** (wicks ignored).
> **Stocks market only 5, 15 min · others all ⇒ 15 min**
> **market time 6 to 10.30**

Timeframe 15m ✅. The session is `06:00–22:30 IST` ("morning 6 to night 10.30") ⚠️.

## p3 — Live / dead ✅

> This is live … **this weak point is death bcz the body full close the weak point**.

A zone dies when a wick **or** body fully breaks through the far edge.

## p4 — Risk management + THE BUFFER TABLE ✅

> Risk 1% (1) = weak point (2.5) · **2.5% and above** from entry to the zone
> **1:3 fixed** · Risk ⇒ 2:3

**Buffer Points stop loss** — the buffer scales with the raw stop distance:

| Raw distance (points) | Buffer |
|---|---|
| 01–05 | 0.500 |
| 06–10 | 1 |
| 11–20 | 1.5 |
| 21–30 | 2 |
| 31–40 | 3 |
| 41–50 | 4 |
| 51–60 | 5 |

Also a cent-account table (1$ = 100 cents … 50$ = 5000 cents).
`SL_BUFFER_TABLE` / `sl_buffer_for()`.

## p5 — Lot / point / value table ✅

| Lot | 1 point |
|---|---|
| 0.01 | 1 USD |
| 0.05 | 5 USD |
| 0.1 | 10 USD |
| 1 | 100 USD |
| 5 | 500 USD |

Confirms `VALUE_PER_POINT_PER_LOT = 100`.

## p6 — Bullish engulfing entry & stop ✅

> **Entry @ only High with Buffer 0.100 and 0.200 Spread ⇒ 0.3 Point**
> **SL @ Low of the both with 0.3 spread + 7 point + 1 point as per table ⇒ 8.3**
> **Entry only 3rd Candle** · **SL ⇒ P + B.f + SP**

    entry = 2nd_high + 0.100 + spread
    SL    = min(low1, low2) - buffer_from_p4_table(raw distance)

The worked example checks out exactly: 7 + 1 + 0.3 = **R 8.3**.
The spread is **broker-specific** — measured live, Delta India quotes XAUTUSD at
**0.030** against the mentor's 0.200.

## p7 — Harami entry & stop ✅

> **Entry + SP + 0.1 Point** · **SL + SP + points distance from entry low**

Same formula as engulfing — one rule for all four models.

## p8 — Trade day 5: psychology ❌ (nothing mechanical)

FOMO, revenge trading, greed, fear, overconfidence, no trading plan, oversized
lot, loss acceptance, external pressure, lack of discipline. **"Cut the
Emotional!"** — a bot removes these by construction.

## p9 — Trade confirmation ✅

> **Engulfing breakout:** 2nd candle must break the 1st candle's **low** for bull,
> **high** for bear.
> **Harami breakout:** 2nd candle must break the 1st candle's **low** for bull,
> **high** for bear.

Exactly what `detect()` requires for all four models.

## p10 — Direction + Day 6 Master Level ✅

> **when market death the first … weak point the market go downside**

The directional rule in the mentor's own words: a broken weak point sets
direction. Per his later clarification it governs **the next entry only**, not
the whole day.

> **Bullish engulfing:** 1st red candle, the 2nd candle breaks out the 1st low and
> body of the 1st candle must be inside 2nd candle, then we place the entry at top
> of the 2nd candle and SL @ low of the 1st and 2nd whichever has the lower low,
> and the entry only valid 3rd candle only break the entry.

Matches the implementation element for element.

## p11 — NOT TRADE + cost-to-cost ⚠️

> **NOT TRADE**
> - No breakout – no trade confirmation
> - No trade [without] second candle confirmation
> - **Cost to cost – stop loss**
> - No trade [without] third candle confirmation
>
> (diagram) **Exit @ cost to cost**

The first, second and fourth are the breakout/confirmation rules already enforced
by `detect()` + the 3rd-candle trigger. "Cost to cost – stop loss" is the exit.

## p12 — Rules focus ⚠️

> weak point – 1:2.5+ · **3 to 4 Candle no Break – cost to cost** ·
> Target set – 1:3 · Entry & stop loss set

This defines **cost-to-cost**: if the trade has not *broken* within **3 to 4
candles**, close it at entry (breakeven) rather than waiting for the stop.
Lot examples re-confirm the formula: `50/12.05 → 0.04 lot`, `50/5 → 0.10 lot`.

---

## Backtest state after the full decode

Spot XAUUSD (Dukascopy), p4 buffer table + break-arms-next-entry + 2.5R clearance:

| Config | Trades | Win | Loss | B/E | Win% | Net R |
|---|---|---|---|---|---|---|
| no session, no cost-to-cost | 28 | 9 | 19 | 0 | 32.1% | +8R |
| **no session, cost-to-cost (3 candles)** | **29** | 8 | 13 | 8 | **38.1%** | **+11R** |
| session 06:00–22:30, cost-to-cost | 22 | 3 | 11 | 8 | 21.4% | −2R |
| **Mentor (August)** | **27** | **16** | **11** | — | **59.3%** | **+37R** |

**Cost-to-cost works** — it converts 8 would-be losses into breakevens and lifts
the win rate ~6 points, exactly as the notes intend.

**The session filter is the open anomaly.** p2 states "market time 6 to 10.30",
but applying `06:00–22:30 IST` *costs* ~13 points of win rate on both feeds. Two
candidate explanations, not yet separated:

1. **The window may be narrower** — "6 to 10.30" read as morning-only
   (06:00–10:30) gives 33.3% and only 7 trades, closer in spirit but a very small
   sample.
2. **Interaction with the arming rule** — in the current code a signal rejected on
   session grounds does *not* spend the armed direction, so the arm survives to a
   later, staler signal. Whether a blocked signal should consume or expire the arm
   is undecided, and it materially changes which trades are taken.

## Still open

- Which session window the mentor actually means, and whether a session-blocked
  signal spends the armed direction.
- Whether "no break" for cost-to-cost means *failed to reach 1R* (current
  implementation) or something stricter, e.g. failed to break the entry candle's
  extreme.
- Whether cost-to-cost counts as a trade in the mentor's 27 (if his breakevens are
  not recorded, our 29-with-8-breakevens is ~21 recorded trades against his 27).
