# Which instruments this method actually works on

Five instrument classes tested on Delta Exchange, 15m, 60 days
(25 Jun – 24 Aug 2026), identical rules from `FINAL_CONFIG.md`. Baskets are
reported as aggregates, never as the best member — picking the winner after
seeing the results is how a backtest passes and live trading fails.

## Result

| class | trades | gross R/trade | fee as % of risk | net | verdict |
|---|---|---|---|---|---|
| **GOLD (XAUTUSD)** | 93 | **+0.376** | **~10%** | **+26R** | **works** |
| US stocks (8 names) | 90 | +0.141 | 16.4% | −2R | fee cancels it |
| Crypto (6 names) | 509 | +0.096 | **44.2%** | −176R | fee destroys it |
| BTC alone | 101 | −0.079 | 58.5% | −67R | no edge either |
| Silver (SLVONUSD) | 67 | −0.303 | — | — | no edge |

## The two things that decide it

**1. Fee relative to R, not fee in absolute terms.** The cost in points is
`price x taker x 2`, and what matters is that against the stop distance:

| | taker | round trip | typical 15m R | **fee / risk** |
|---|---|---|---|---|
| Gold | 0.0001 | 0.02% of price | ~0.2% of price | **~10%** |
| US stocks | 0.0002 | 0.04% of price | small (cheap tokens) | ~16% |
| Crypto | **0.0005** | **0.1% of price** | ~0.3% of price | **~44%** |

Delta's crypto tier is five times gold's. On a tight-stop method that is the
whole ballgame — a third to a half of every trade's risk goes to the exchange.

**2. Gold is the only one where the machinery adds value.** Measured with no
fees at all, pure signal:

| | patterns only | + direction rule | full rules |
|---|---|---|---|
| GOLD | −0.074 | −0.003 | **+0.376** |
| SILVER | +0.063 | +0.021 | **−0.303** |
| BTC | −0.011 | +0.006 | **−0.079** |

On gold the weak-zone and direction rules turn losing patterns into a strong
edge. On silver and BTC the same rules **invert** it. The zones-and-breaks
structure reads something real about gold's 15m behaviour that does not
generalise.

## So: is Delta a good venue?

**For XAUT gold, yes** — 0.0001 fees, 0.001 contracts (so a small account can
size precisely, which MT5's 0.01 lot minimum makes impossible), and the edge
clears the cost. The finalized config returns +26.9% over 60 days at 5% risk
with an 18.5% drawdown.

**For everything else on Delta, no.** Crypto and stocks both showed a mild
positive *gross* edge (+0.096 and +0.141 R/trade) that their fee tiers wiped
out. That is a venue problem, not a method problem: on a spread-priced broker
those might clear. On Delta they do not.

**Trade gold on Delta. Do not trade crypto, stocks or silver on Delta.**

## Caveats

* 60 days. Gold's two months were not alike — July moved 19 points net, August
  578 — and most of gold's profit is August.
* Basket members individually run 8–14 trades (stocks) or 59–101 (crypto). Only
  the aggregates carry meaning; the per-name figures are noise.
* Tokenised stocks and silver are wrappers, not the underlying: SLVONUSD tracks
  the iShares Silver Trust, the xStock/bStock tokens track their equities.
  Stocks were restricted to the US cash session because 29–62% of their bars
  are otherwise flat.
