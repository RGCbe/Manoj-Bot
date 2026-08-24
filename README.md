# Manoj-Bot — Weak Zone marking

Detects and marks **weak point / reversal zones** on a chart, following the
hand-written trade-plan rules (Class Day 3, Day 4, Day 6).

This is the first building block of the bot: **marking the zones**. Entries,
stop-loss, targets and lot-sizing (from the later pages of the plan) build on
top of these zones and will be added next.

## The rule it implements

**1. Formation** — three **same-colour** candles where **each breaks the previous**:

| Run | Break condition | Meaning | Zone |
|-----|-----------------|---------|------|
| 3 green | higher highs (each high > previous high) | bullish reversal | **support** |
| 3 red | lower lows (each low < previous low) | bearish reversal | **resistance** |

**2. Band** — the zone is a *band*, drawn from **body to wick**, anchored to the
nearest low/high (the formation candles plus a small `lookback`):

- **support:** `top = lowest body`, `bottom = lowest wick`
- **resistance:** `top = highest wick`, `bottom = highest body`

The box **starts at the lowest candle** (support) / **highest candle**
(resistance) — the wick candle itself — and **ends at the candle that breaks
it**.

**3. Alternating sides** — weak points alternate: a support marked from 3 green
is followed by a resistance from 3 red, then a support again. A formation on the
same side as the last marked zone is **skipped**. This is what keeps the marks on
the actual swing turns (on 4 days of BTC 15m it takes 45 zones down to 24).

**4. Live / Dead** — the zone stays **LIVE** while price only *touches into* the
band. It **DIES** the moment a **wick _or_ body fully breaks through the far
edge** (below a support / above a resistance). On death the box **stops** (right
edge frozen) and turns grey/dotted.

> A partial touch that stops **inside** the band keeps it live.
> Anything that goes **all the way through** kills it.

## What's in here

| File | Platform | Purpose |
|------|----------|---------|
| `MQL5/Indicators/WeakZones.mq5` | MetaTrader 5 | Draws the zones on an MT5 chart (production) |
| `pine/WeakZones.pine` | TradingView (Pine v6) | Same zones on TradingView — easiest way to compare against your manual marks |
| `tools/weak_zones_ref.py` | Python (no deps) | Reference implementation + chart renderer to *verify* the logic |

All three use the **identical** algorithm and the **same input names**, so a zone
marked by one is marked by the others.

## Verify it marks the same as you do by hand

### TradingView (recommended — your charts)
1. Open the Pine Editor, paste `pine/WeakZones.pine`, **Add to chart**.
2. Open BTCUSD (or any symbol) on the **15-min** timeframe.
3. Compare the boxes it draws to the zones you drew manually. They should sit on
   the same low-body → low-wick band, and stop where the zone died.

### MetaTrader 5
1. Copy `WeakZones.mq5` into `MQL5/Indicators/` of your MT5 data folder.
2. In MetaEditor press **Compile**.
3. Drag **WeakZones** onto a 15-min chart.

### Python (here / offline)
```bash
python3 tools/weak_zones_ref.py
```
Prints the zones it marks and writes `weak_zones_demo.png` — a worked example of
a support zone that is **LIVE**, gets only wicked into, then **DIES** and the box
stops. Point the same `detect_weak_zones()` at your own OHLC data to check it.

## Inputs (same across all three)

| Input | Default | What it does |
|-------|---------|--------------|
| `lookback` / `InpAnchorLookback` | `4` | Candles before the 1st candle to include when finding the nearest low/high. `4` was chosen by matching a hand-marked zone on real BTC 15m data (see below); raise it to reach a deeper swing. |
| `allowDoji` / `InpAllowDoji` | `false` | Whether a doji may sit inside the 3-candle run |
| `deathBuf` / `InpDeathBufferPts` | `0` | Extra distance past the far edge before the zone is called dead (filters tiny stop-hunt wicks). `0` = exact rule. |
| `alternate` / `InpAlternate` | `true` | Require weak points to alternate support → resistance → support. Turn off to mark every valid formation. |
| `extendRight` / `InpExtendRight` | `true` | Stretch live zones to the current bar |
| `maxZones` / `InpMaxZones` | `60` | Cap on how many zones stay on the chart |

## Notes / assumptions

These match the rule as decoded from the notes; adjust the inputs to taste:

- **"Break"** = higher high (green) / lower low (red) versus the previous candle.
- **Death** is evaluated on **closed candles** (an intrabar wick that is not there
  at close does not kill the zone). Use `deathBuf` if you want a tolerance.
- **Anchor** uses a fixed `lookback` window as a stand-in for "the nearest swing
  low/high". The default of `4` was validated against a hand-marked zone on real
  BTC-USD 15m candles: a formation completing at 12:00 IST on 2026-08-23 produced
  a band of **75,602 - 75,865** starting at the 10:45 candle, matching the
  hand-marked **75,600 - 75,900** starting at ~10:45. Raising it further widens
  the search without changing the number of zones.

- **Candle colour differs between exchanges.** In that same example the 11:30
  bar closed 28 points below its open on one feed (red) and above it on another
  (green), which decides whether the 3-candle formation exists at all. Verify on
  the same feed you trade.
