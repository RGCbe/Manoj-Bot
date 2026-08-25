# Manoj-Bot — final configuration

Everything decoded and tested. `TRADE_PLAN_DECODED.md` has the page-by-page
derivation, `DELTA_RULES.md` the venue reasoning; this is the settled spec.

## 1. Chart

15-minute candles. Spot gold, or XAUT on Delta.

## 2. Weak zones

* 3 same-colour candles, **each breaking the previous** (higher highs / lower lows).
  3 green -> **support**, 3 red -> **resistance**.
* Band = body -> wick, anchored over the formation + **8** candle lookback.
  Support: top = lowest body, bottom = lowest wick. Resistance mirrored.
* Box starts at the extreme candle, ends at the candle that breaks it.
* Zones **alternate** support -> resistance -> support; same-side formations skipped.
* A zone lives **2 days** (192 bars) unless broken first.
* It **dies** when a wick *or* body fully breaks through the far edge.

## 3. Direction

The **most recent weak-zone break arms the next entry only**:
buy-side break -> next entry is a BUY, sell-side break -> next entry is a SELL.
Taking the entry spends it; nothing trades until the next break. Not a daily bias.

## 4. Entry — the four models

1st and 2nd candle, **bodies only, wicks ignored**:

| Model | 1st | 2nd | Containment | Confirmation | Dir |
|---|---|---|---|---|---|
| Bullish Engulfing | red | green | 1st body inside 2nd | 2nd breaks 1st **low** | BUY |
| Bearish Engulfing | green | red | 1st body inside 2nd | 2nd breaks 1st **high** | SELL |
| Bullish Harami | red | green | 2nd body inside 1st | 2nd breaks 1st **low** | BUY |
| Bearish Harami | green | red | 2nd body inside 1st | 2nd breaks 1st **high** | SELL |

Orders placed at the **2nd candle's close**; the **3rd candle** is the only candle
that may trigger them; untriggered at its close -> **cancel**.

    entry = 2nd candle extreme + 0.100 buffer + spread
    stop  = opposite extreme of both candles -/+ buffer from the p4 table

**p4 buffer table** (scales with the raw stop distance):

| raw pts | 1-5 | 6-10 | 11-20 | 21-30 | 31-40 | 41-50 | 51-60 |
|---|---|---|---|---|---|---|---|
| buffer | 0.5 | 1 | 1.5 | 2 | 3 | 4 | 5 |

**R = entry - stop.** Filters: entry to the nearest live opposing zone must be
**>= 2.5R** (or no zone); **one trade at a time**, but a pattern forming on the
stop-loss candle is valid.

## 5. Exits

| Trigger | Action |
|---|---|
| **1R** | close 1/3 |
| **2R** | close 1/3, **stop moves to 1R** |
| **3R** | close final 1/3 |
| Candle after entry is opposite colour and fails to break the entry candle | drop the target to **+0.5R** and exit when price returns to it (cost to cost) |
| 1 hour stuck in the 1R-2R band | take **1R** |
| Stop hit | -1R on whatever remains |

Best +2R, worst -1R, and after 2R the last third cannot lose. Never move the stop
to breakeven — it tested worse three separate times; only trail after 2R.

## 6. Sizing

    lot / contracts = risk$ / ((R + dealing cost) x value per point)

* Risk a fixed **% of the current balance** (compounded).
* A **spread** belongs in the entry (a price offset). A **commission** must NOT
  move the stop — it only shrinks the position, or a stop-out costs more than
  the intended risk.
* MT5 gold: 0.01 lot = $1/point. Delta: 1 contract = 0.001 XAUT.
* **Size by risk, never to leverage.** Check the stop is nearer than liquidation.

## 7. Venue settings

| | mentor's gold broker | Delta XAUTUSD |
|---|---|---|
| spread | 0.200 | 0.030 |
| commission | none | 0.0001 per side (maker = taker) |
| **all-in cost** | **0.200 pts** | **0.956 pts** |
| funding | none | ~0.005% / 8h on notional |
| **minimum R** | none needed | **>= 6 points** |

**The minimum-R rule is what makes Delta viable.** fee/risk = 0.926/R, so a
3-point stop hands the exchange 31% of the risk. Without the filter, honest
accounting shows a **loss** on Delta (-2.2% over 60 days).

## 8. Results — $100 on Delta, 60 days (25 Jun - 24 Aug 2026)

Complete rules, min R >= 6, correct cost accounting, fees and funding included:

| risk | final | return | maxDD | worst ordering (5000 shuffles) |
|---|---|---|---|---|
| 1% | $105.88 | +5.9% | 4.1% | — |
| **2%** | **$111.57** | **+11.6%** | **8.1%** | — |
| 3% | $116.90 | +16.9% | 12.1% | — |
| **5%** | **$126.69** | **+26.7%** | **19.7%** | 49.8% DD, **0% ruin, 0% losing** |

34 trades: 7 full wins, 9 trailed, 2 partial, 16 losses. Jun +3.38, Jul +4.74,
Aug +18.57 — every month positive.

On spot gold (mentor's instrument, 30-day sample) the same rules gave 28 trades
at 57.1% profitable and +14.0R, against his 27 trades and 59.3%.

## 9. Read the results with these in mind

* **60 days, 34 trades.** Modest. Do not annualise.
* **August carries it.** Gold moved 578 points in August against 19 in July.
  This is a breakout system: it earns in trends and treads water in ranges.
* **XAUT is not gold.** 0.983 correlated on 15m moves, but a widening ~$13
  discount and it trades weekends.
* **A 5% ordering can put you near $50 before recovering.** No ordering lost
  money on this data, but the drawdown is real.

## 10. Session — settled: OFF, but only trade while gold is open

Every intraday session window tested worse, on 60 days of Delta at 5% risk:

| session | trades | return | maxDD |
|---|---|---|---|
| **none** | 34 | **+26.7%** | 19.7% |
| 06:00-22:30 IST | 32 | +10.1% | 22.6% |
| 06:00-10:30 IST (morning) | 16 | **-12.6%** | 22.6% |

Only 8 of 34 trades fall outside 06:00-22:30 and those 8 made **+$5.39** — the
window cuts profitable trades. **No intraday session filter.**

Separately, `weekdays_only` restricts trading to when spot gold is actually open
(Sun 22:00 - Fri 21:00 UTC). On Delta, where XAUT keeps trading the weekend on
thin unbacked price action, this is on. Its effect is close to neutral (+26.9%
vs +26.7%, drawdown 18.5% vs 19.7%) — it is there because trading an instrument
whose underlying market is shut is not the method, not because it adds return.
An earlier +33.6% for "weekdays only" came from a naive IST weekday test that
cut different bars and happened to drop one losing trade; the correct UTC
boundaries keep all 34 trades.

## 11. Which venue to trade this on

The rules are venue-independent; the economics are not. Measured, not assumed:

| | Delta XAUT | MT5 spot gold |
|---|---|---|
| instrument | Tether Gold token — tracks spot at 0.983 correlation but sits at a widening ~$13 (-0.30%) discount | **real spot XAUUSD** |
| dealing cost | 0.030 spread + 0.0001 fee = **0.956 pts** (~10% of a typical R) | 0.200 spread, no commission = **0.200 pts** (~2% of R) |
| smallest workable account | **$100** (0.001 contracts size precisely) | **~$1,000** (0.01 lot minimum risks $1/point, so a $100 account can take 0 of 30 trades at 2% risk) |
| weekends | trades 24/7 on thin unbacked price action | closed, as the method assumes |
| comparable to the mentor | no | **yes — same instrument and feed** |
| other instruments | crypto, stocks, silver all tested negative (`INSTRUMENT_SURVEY.md`) | not tested |

**Delta is viable for XAUT gold and nothing else on it.** Its gold config is the
best result in this project: +26.7% over 60 days at 5% risk, 18.5% drawdown, and
no losing or ruinous outcome across 5000 shuffled trade orderings.

**MT5 spot gold is the better home when the account can reach ~$1,000.** It keeps
roughly five times more of the gross edge, trades the actual instrument, and is
directly comparable to the mentor's 27-trade August benchmark.

So the venue choice is a function of account size, not of the rules:

* under ~$1,000 -> Delta, XAUT only, min R >= 6
* ~$1,000 and up -> MT5 spot gold, where the cost stops mattering

## 12. Still open
* Whether the mentor counts cost-to-cost exits among his 27 August trades.
* Pine and MT5 still carry the zone-marking rules only; the entry, exit and
  sizing logic above is Python-only so far.
