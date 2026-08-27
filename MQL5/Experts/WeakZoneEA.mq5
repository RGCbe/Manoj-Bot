//+------------------------------------------------------------------+
//|                                                   WeakZoneEA.mq5  |
//|                       Manoj-Bot - the full weak-zone trading bot  |
//|                                                                  |
//|  Trades the finalized rule set (docs/FINAL_CONFIG.md):           |
//|                                                                  |
//|   * weak zones: 3 same-colour candles each breaking the previous |
//|     (3 green -> support, 3 red -> resistance); band body->wick,   |
//|     anchor lookback 8, alternate sides, 2-day life, dies on a     |
//|     full break of the far edge.                                  |
//|   * a zone break arms the NEXT ENTRY only (resistance up -> buy,  |
//|     support down -> sell); taking the entry spends it.            |
//|   * 4 models (engulfing / harami), bodies only, the 2nd candle    |
//|     must break the 1st's low (bull) / high (bear).               |
//|   * order at the 2nd candle close, valid for the 3rd candle only. |
//|   * entry = 2nd extreme + buffer + spread; stop = opposite        |
//|     extreme -/+ the p4 buffer (scales with the raw distance).     |
//|   * zone clearance to the nearest opposing zone must be >= 2.5R.  |
//|   * exits: 1/3 at 1R, 1/3 at 2R (stop -> 1R), 1/3 at 3R;          |
//|     cost-to-cost (+0.5R) if the candle after entry is the         |
//|     opposite colour and fails to break the entry candle; stall    |
//|     (take 1R) if stuck in the 1R-2R band for InpStallBars.        |
//|   * size by risk %; a commission is folded into the sizing, the   |
//|     spread into the entry - never into the stop.                  |
//|                                                                  |
//|  ONE trade at a time. Attach to a 15-minute gold chart.          |
//+------------------------------------------------------------------+
#property copyright "Manoj-Bot"
#property version   "1.00"
#include <Trade/Trade.mqh>

//--- strategy inputs ----------------------------------------------------------
input double InpRiskPct        = 2.0;    // Risk per trade (% of balance)
input int    InpAnchorLookback = 8;      // Zone anchor lookback (candles before the 1st)
input int    InpZoneLifeBars   = 192;    // Zone lifetime in bars (192 = 2 days on 15m)
input bool   InpAlternate      = true;   // Alternate zone sides (support->resistance->support)
input double InpMinZoneR        = 2.5;   // Clearance to opposing zone, in R
input double InpEntryBuffer     = 0.100; // Entry buffer beyond the 2nd candle, in price
input bool   InpUseLiveSpread   = true;  // Add the live spread to the entry
input double InpFixedSpread     = 0.030; // Spread to use if InpUseLiveSpread = false
input double InpCommissionPerLot= 0.0;   // Round-trip commission per 1.0 lot (account ccy); 0 = spread-only
//--- exits --------------------------------------------------------------------
input bool   InpScaleOut        = true;  // Scale out 1/3 at 1R, 1/3 at 2R, 1/3 at 3R
input bool   InpTrailTo1R       = true;  // On reaching 2R, move the stop to 1R
input bool   InpCostToCost      = true;  // Cost-to-cost +0.5R exit
input double InpC2CTake         = 0.5;   // Cost-to-cost profit, in R
input bool   InpStall           = true;  // Stall exit
input int    InpStallBars       = 4;     // Bars stuck in the 1R-2R band before taking 1R
input double InpTP_R            = 3.0;   // Final target, in R (used if scale-out is off)
//--- misc ---------------------------------------------------------------------
input long   InpMagic           = 8675309;
input int    InpSlippage        = 20;    // Max deviation, in points

CTrade   trade;

//--- weak-zone bookkeeping ----------------------------------------------------
struct Zone { bool isSupport; double top; double bottom; datetime bornTime; bool alive; };
Zone     g_zones[];
int      g_lastSide = 0;                 // 1 = last marked support, -1 = resistance
int      g_armed    = 0;                 // +1 next entry must be a buy, -1 a sell, 0 none
datetime g_lastBarTime = 0;

//--- the one open trade's state ----------------------------------------------
bool     g_hasPos = false;
ulong    g_ticket = 0;
int      g_side   = 0;                   // +1 buy, -1 sell
double   g_entry  = 0.0;
double   g_stop   = 0.0;
double   g_R      = 0.0;
double   g_origLots = 0.0;
double   g_entryCandleHi = 0.0, g_entryCandleLo = 0.0;
datetime g_entryBarTime = 0;
int      g_banked = 0;                   // thirds taken (0..3)
int      g_c2cState = 0;                 // 0 unchecked, 1 checked-not-armed, 2 armed
bool     g_scaling = false;              // volume was splittable into thirds

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   ArrayResize(g_zones, 0);
   g_lastSide = 0; g_armed = 0; g_lastBarTime = 0;
   AdoptExistingPosition();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| p4 buffer table - the stop buffer scales with the raw distance.  |
//+------------------------------------------------------------------+
double SlBufferFor(double points)
{
   if(points <=  5) return 0.5;
   if(points <= 10) return 1.0;
   if(points <= 20) return 1.5;
   if(points <= 30) return 2.0;
   if(points <= 40) return 3.0;
   if(points <= 50) return 4.0;
   return 5.0;
}

//+------------------------------------------------------------------+
int CandleColor(double o, double c) { return (c > o) ? 1 : (c < o ? -1 : 0); }

//+------------------------------------------------------------------+
double SpreadPrice()
{
   if(InpUseLiveSpread)
      return (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * _Point;
   return InpFixedSpread;
}

//+------------------------------------------------------------------+
//| Main loop.                                                       |
//+------------------------------------------------------------------+
void OnTick()
{
   // manage an open position on every tick, so intrabar targets fire
   if(g_hasPos)
   {
      if(!PositionSelectByTicket(g_ticket)) { ResetPos(); }
      else ManageOpenPosition();
   }

   // act once per closed M15 bar
   datetime t0 = iTime(_Symbol, PERIOD_M15, 0);
   if(t0 == g_lastBarTime) return;
   g_lastBarTime = t0;

   int bars = iBars(_Symbol, PERIOD_M15);
   if(bars < InpAnchorLookback + 6) return;

   RebuildZonesIfNeeded();
   AgeZonesOnClosedBar();      // ages zones against bar 1, arms direction on a break
   CancelStalePending();       // a pending order that survived its 3rd candle

   if(g_hasPos) { OnNewBarManage(); return; }   // cost-to-cost / stall checks
   if(HasPendingOrder()) return;                // one at a time

   LookForEntry();
}

//+------------------------------------------------------------------+
//| Rebuild the whole zone history once (first run / after restart). |
//+------------------------------------------------------------------+
bool     g_built = false;
datetime g_lastZoneBarTime = 0;                 // last bar already folded into the zones
void RebuildZonesIfNeeded()
{
   if(g_built) return;
   g_built = true;
   int bars = iBars(_Symbol, PERIOD_M15);
   ArrayResize(g_zones, 0);
   g_lastSide = 0; g_armed = 0;
   for(int b = bars - 1; b >= 1; b--)
      ProcessBarForZones(b, bars, false);
   g_lastZoneBarTime = iTime(_Symbol, PERIOD_M15, 1);   // bar 1 is already included
}

//+------------------------------------------------------------------+
//| Age live zones against the just-closed bar (index 1) and, if one |
//| dies, arm the next entry with the break direction. Only fold in  |
//| a bar the rebuild has not already seen.                          |
//+------------------------------------------------------------------+
void AgeZonesOnClosedBar()
{
   datetime t1 = iTime(_Symbol, PERIOD_M15, 1);
   if(t1 == g_lastZoneBarTime) return;
   g_lastZoneBarTime = t1;
   ProcessBarForZones(1, iBars(_Symbol, PERIOD_M15), true);
}

//+------------------------------------------------------------------+
//| Age + (optionally) detect a new formation completing on bar b.   |
//| b is a series index: 1 = last closed bar.                        |
//+------------------------------------------------------------------+
void ProcessBarForZones(const int b, const int bars, const bool armOnBreak)
{
   double lo = iLow(_Symbol, PERIOD_M15, b);
   double hi = iHigh(_Symbol, PERIOD_M15, b);

   // (a) age
   for(int i = 0; i < ArraySize(g_zones); i++)
   {
      if(!g_zones[i].alive) continue;
      int age = iBarShift(_Symbol, PERIOD_M15, g_zones[i].bornTime);
      bool aged  = (InpZoneLifeBars > 0 && age >= InpZoneLifeBars);
      bool broke = g_zones[i].isSupport ? (lo < g_zones[i].bottom) : (hi > g_zones[i].top);
      if(aged || broke)
      {
         g_zones[i].alive = false;
         if(armOnBreak && broke)
            g_armed = g_zones[i].isSupport ? -1 : +1;   // support down -> sell, resistance up -> buy
      }
   }

   // (b) formation completing on bar b (c3=b, c2=b+1, c1=b+2)
   int c3 = b, c2 = b + 1, c1 = b + 2;
   int wEnd = c1 + InpAnchorLookback;
   if(wEnd > bars - 1) return;

   int col1 = CandleColor(iOpen(_Symbol,PERIOD_M15,c1), iClose(_Symbol,PERIOD_M15,c1));
   int col2 = CandleColor(iOpen(_Symbol,PERIOD_M15,c2), iClose(_Symbol,PERIOD_M15,c2));
   int col3 = CandleColor(iOpen(_Symbol,PERIOD_M15,c3), iClose(_Symbol,PERIOD_M15,c3));
   if(col1 == 0 || col2 == 0 || col3 == 0) return;
   if(!(col1 == col2 && col2 == col3)) return;
   bool isGreen = (col1 == 1);

   double h1=iHigh(_Symbol,PERIOD_M15,c1), h2=iHigh(_Symbol,PERIOD_M15,c2), h3=iHigh(_Symbol,PERIOD_M15,c3);
   double l1=iLow(_Symbol,PERIOD_M15,c1),  l2=iLow(_Symbol,PERIOD_M15,c2),  l3=iLow(_Symbol,PERIOD_M15,c3);
   bool breaks = isGreen ? (h2 > h1 && h3 > h2) : (l2 < l1 && l3 < l2);
   if(!breaks) return;
   if(InpAlternate && g_lastSide == (isGreen ? 1 : -1)) return;

   // band over the anchor window
   double top, bottom;
   if(isGreen)
   {
      bottom = l3; top = MathMin(iOpen(_Symbol,PERIOD_M15,c3), iClose(_Symbol,PERIOD_M15,c3));
      for(int k = c3; k <= wEnd; k++)
      {
         bottom = MathMin(bottom, iLow(_Symbol,PERIOD_M15,k));
         top    = MathMin(top, MathMin(iOpen(_Symbol,PERIOD_M15,k), iClose(_Symbol,PERIOD_M15,k)));
      }
   }
   else
   {
      top = h3; bottom = MathMax(iOpen(_Symbol,PERIOD_M15,c3), iClose(_Symbol,PERIOD_M15,c3));
      for(int k = c3; k <= wEnd; k++)
      {
         top    = MathMax(top, iHigh(_Symbol,PERIOD_M15,k));
         bottom = MathMax(bottom, MathMax(iOpen(_Symbol,PERIOD_M15,k), iClose(_Symbol,PERIOD_M15,k)));
      }
   }
   if(top <= bottom) top = bottom + _Point;

   for(int i = 0; i < ArraySize(g_zones); i++)
      if(g_zones[i].alive && g_zones[i].isSupport == isGreen &&
         !(top < g_zones[i].bottom || bottom > g_zones[i].top))
         return;                                       // overlaps a live same-type zone

   Zone z; z.isSupport = isGreen; z.top = top; z.bottom = bottom;
   z.bornTime = iTime(_Symbol, PERIOD_M15, c3); z.alive = true;
   int n = ArraySize(g_zones); ArrayResize(g_zones, n + 1); g_zones[n] = z;
   g_lastSide = isGreen ? 1 : -1;
}

//+------------------------------------------------------------------+
//| Nearest live opposing zone must sit >= InpMinZoneR * R beyond    |
//| entry, or there is no zone in the way.                           |
//+------------------------------------------------------------------+
bool ZoneClearanceOk(double entry, double R, int side)
{
   double nearest = 0.0; bool found = false;
   for(int i = 0; i < ArraySize(g_zones); i++)
   {
      if(!g_zones[i].alive) continue;
      if(side > 0)                       // buy blocked by resistance above
      {
         if(g_zones[i].isSupport) continue;
         double edge = g_zones[i].bottom;
         if(edge <= entry) continue;
         if(!found || edge < nearest) { nearest = edge; found = true; }
      }
      else                                // sell blocked by support below
      {
         if(!g_zones[i].isSupport) continue;
         double edge = g_zones[i].top;
         if(edge >= entry) continue;
         if(!found || edge > nearest) { nearest = edge; found = true; }
      }
   }
   if(!found) return true;
   return MathAbs(nearest - entry) >= InpMinZoneR * R;
}

//+------------------------------------------------------------------+
//| Look for a setup on the two just-closed candles (c1=2, c2=1).    |
//+------------------------------------------------------------------+
void LookForEntry()
{
   if(g_armed == 0) return;

   double o1=iOpen(_Symbol,PERIOD_M15,2), c1=iClose(_Symbol,PERIOD_M15,2);
   double h1=iHigh(_Symbol,PERIOD_M15,2), l1=iLow(_Symbol,PERIOD_M15,2);
   double o2=iOpen(_Symbol,PERIOD_M15,1), c2=iClose(_Symbol,PERIOD_M15,1);
   double h2=iHigh(_Symbol,PERIOD_M15,1), l2=iLow(_Symbol,PERIOD_M15,1);

   int side = 0;
   // body extents
   double b1lo=MathMin(o1,c1), b1hi=MathMax(o1,c1);
   double b2lo=MathMin(o2,c2), b2hi=MathMax(o2,c2);
   bool bull_engulf = (CandleColor(o1,c1)==-1 && CandleColor(o2,c2)==1 && b2lo<=b1lo && b2hi>=b1hi && l2<l1);
   bool bear_engulf = (CandleColor(o1,c1)==1  && CandleColor(o2,c2)==-1&& b2lo<=b1lo && b2hi>=b1hi && h2>h1);
   bool bull_harami = (CandleColor(o1,c1)==-1 && CandleColor(o2,c2)==1 && b1lo<=b2lo && b1hi>=b2hi && l2<l1);
   bool bear_harami = (CandleColor(o1,c1)==1  && CandleColor(o2,c2)==-1&& b1lo<=b2lo && b1hi>=b2hi && h2>h1);
   if(bull_engulf || bull_harami) side = +1;
   else if(bear_engulf || bear_harami) side = -1;
   if(side == 0) return;
   if(side != g_armed) return;                          // must match the armed direction

   double spread = SpreadPrice();
   double entry, stop, raw;
   if(side > 0) { entry = h2 + InpEntryBuffer + spread; raw = MathMin(l1,l2); stop = raw - SlBufferFor(entry-raw); }
   else         { entry = l2 - InpEntryBuffer - spread; raw = MathMax(h1,h2); stop = raw + SlBufferFor(raw-entry); }
   double R = MathAbs(entry - stop);
   if(R <= 0) return;
   if(!ZoneClearanceOk(entry, R, side)) return;

   double lots = LotsForRisk(R);
   if(lots <= 0) return;

   PlacePending(side, entry, stop, lots);
}

//+------------------------------------------------------------------+
//| Risk-based sizing. The commission is folded in; the spread is    |
//| already in the entry, never in the stop.                         |
//+------------------------------------------------------------------+
double LotsForRisk(double R)
{
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0) return 0.0;

   double riskUsd    = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0;
   double lossPerLot = (R / tickSize) * tickVal + InpCommissionPerLot;   // fold commission in
   if(lossPerLot <= 0) return 0.0;

   double lots = riskUsd / lossPerLot;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots / step) * step;
   if(lots < minL) return 0.0;                          // too wide for the account -> skip
   if(lots > maxL) lots = maxL;
   return lots;
}

//+------------------------------------------------------------------+
void PlacePending(int side, double entry, double stop, double lots)
{
   entry = NormalizeDouble(entry, _Digits);
   stop  = NormalizeDouble(stop, _Digits);
   // GTC for broker compatibility; CancelStalePending() enforces "3rd candle
   // only" by deleting the order once its bar has passed unfilled.
   bool ok;
   if(side > 0)
      ok = trade.BuyStop(lots, entry, _Symbol, stop, 0.0, ORDER_TIME_GTC, 0, "WZ buy");
   else
      ok = trade.SellStop(lots, entry, _Symbol, stop, 0.0, ORDER_TIME_GTC, 0, "WZ sell");
   if(ok)
   {
      // remember the intended trade; the fill is picked up in OnTradeTransaction
      g_side  = side; g_entry = entry; g_stop = stop; g_R = MathAbs(entry-stop);
      g_origLots = lots;
   }
}

//+------------------------------------------------------------------+
bool HasPendingOrder()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong tk = OrderGetTicket(i);
      if(OrderGetInteger(ORDER_MAGIC) == InpMagic && OrderGetString(ORDER_SYMBOL) == _Symbol)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Delete a pending order that was not triggered by its 3rd candle. |
//| (Belt-and-braces: the broker expiration should already do this.) |
//+------------------------------------------------------------------+
void CancelStalePending()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong tk = OrderGetTicket(i);
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic || OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      datetime setup = (datetime)OrderGetInteger(ORDER_TIME_SETUP);
      // if a full bar has passed since it was placed, its 3rd candle is gone
      if(iTime(_Symbol, PERIOD_M15, 0) - setup >= PeriodSeconds(PERIOD_M15))
         trade.OrderDelete(tk);
   }
}

//+------------------------------------------------------------------+
//| Pick up a fill.                                                  |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req,
                        const MqlTradeResult &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(g_hasPos) return;
   if(!PositionSelectByTicket(trans.position)) return;
   if(PositionGetInteger(POSITION_MAGIC) != InpMagic || PositionGetString(POSITION_SYMBOL) != _Symbol) return;

   g_hasPos = true;
   g_ticket = trans.position;
   g_side   = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? +1 : -1;
   g_entry  = PositionGetDouble(POSITION_PRICE_OPEN);
   g_stop   = PositionGetDouble(POSITION_SL);
   g_R      = MathAbs(g_entry - g_stop);
   g_origLots = PositionGetDouble(POSITION_VOLUME);
   g_entryCandleHi = iHigh(_Symbol, PERIOD_M15, 0);
   g_entryCandleLo = iLow(_Symbol, PERIOD_M15, 0);
   g_entryBarTime  = iTime(_Symbol, PERIOD_M15, 0);
   g_banked = 0; g_c2cState = 0;

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double third = MathFloor((g_origLots/3.0)/step)*step;
   g_scaling = (InpScaleOut && third >= minL);          // can we take clean thirds?

   g_armed = 0;                                         // the break is now spent
}

//+------------------------------------------------------------------+
//| Intrabar management of the open position: scale-out + c2c target.|
//+------------------------------------------------------------------+
void ManageOpenPosition()
{
   double price = (g_side > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                               : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // cost-to-cost target takes the whole remainder at +InpC2CTake R
   if(g_c2cState == 2)
   {
      double t = g_entry + g_side * InpC2CTake * g_R;
      if((g_side > 0 && price >= t) || (g_side < 0 && price <= t))
         { trade.PositionClose(g_ticket); ResetPos(); }
      return;
   }

   if(!g_scaling)                                       // single exit at InpTP_R
   {
      double t = g_entry + g_side * InpTP_R * g_R;
      if((g_side > 0 && price >= t) || (g_side < 0 && price <= t))
         { trade.PositionClose(g_ticket); ResetPos(); }
      return;
   }

   // scale-out ladder
   double l1 = g_entry + g_side * 1.0 * g_R;
   double l2 = g_entry + g_side * 2.0 * g_R;
   double l3 = g_entry + g_side * 3.0 * g_R;
   bool hit1 = (g_side > 0) ? price >= l1 : price <= l1;
   bool hit2 = (g_side > 0) ? price >= l2 : price <= l2;
   bool hit3 = (g_side > 0) ? price >= l3 : price <= l3;

   if(g_banked == 0 && hit1) { ClosePartialThird(); g_banked = 1; }
   if(g_banked == 1 && hit2)
   {
      ClosePartialThird(); g_banked = 2;
      if(InpTrailTo1R)
      {
         double newSL = NormalizeDouble(g_entry + g_side * 1.0 * g_R, _Digits);
         trade.PositionModify(g_ticket, newSL, 0.0);
         g_stop = newSL;
      }
   }
   if(g_banked == 2 && hit3) { trade.PositionClose(g_ticket); ResetPos(); }
}

//+------------------------------------------------------------------+
//| Close one third of the ORIGINAL volume.                          |
//+------------------------------------------------------------------+
void ClosePartialThird()
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vol  = MathFloor((g_origLots/3.0)/step)*step;
   if(!PositionSelectByTicket(g_ticket)) { ResetPos(); return; }
   double cur = PositionGetDouble(POSITION_VOLUME);
   if(vol >= cur) { trade.PositionClose(g_ticket); ResetPos(); return; }
   trade.PositionClosePartial(g_ticket, vol);
}

//+------------------------------------------------------------------+
//| On a new closed bar: cost-to-cost arming and the stall exit.     |
//+------------------------------------------------------------------+
void OnNewBarManage()
{
   if(!PositionSelectByTicket(g_ticket)) { ResetPos(); return; }
   int barsSince = iBarShift(_Symbol, PERIOD_M15, g_entryBarTime) ; // bars since entry bar

   // cost-to-cost: on the FIRST full candle after entry, opposite colour and
   // failing to break the entry candle means the move died -> take +0.5R.
   // The entry candle sits at index barsSince, the candle after it at barsSince-1;
   // reading them here uses their final (closed) high/low, not the partial ones.
   if(InpCostToCost && g_c2cState == 0 && barsSince >= 2)
   {
      int ia = barsSince - 1, ie = barsSince;          // after-candle, entry-candle
      int col = CandleColor(iOpen(_Symbol,PERIOD_M15,ia), iClose(_Symbol,PERIOD_M15,ia));
      double hA = iHigh(_Symbol,PERIOD_M15,ia), lA = iLow(_Symbol,PERIOD_M15,ia);
      double hE = iHigh(_Symbol,PERIOD_M15,ie), lE = iLow(_Symbol,PERIOD_M15,ie);
      bool died = (g_side > 0) ? (col == -1 && hA <= hE)
                               : (col == +1 && lA >= lE);
      g_c2cState = died ? 2 : 1;
   }

   // stall: reached 1R (banked one third) but stuck below 2R for InpStallBars.
   if(InpStall && g_scaling && g_banked == 1 && barsSince >= InpStallBars)
   {
      trade.PositionClose(g_ticket);
      ResetPos();
   }
}

//+------------------------------------------------------------------+
void ResetPos()
{
   g_hasPos = false; g_ticket = 0; g_side = 0; g_banked = 0; g_c2cState = 0;
}

//+------------------------------------------------------------------+
//| Re-adopt a position that already exists (EA restart).            |
//+------------------------------------------------------------------+
void AdoptExistingPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(PositionGetInteger(POSITION_MAGIC) == InpMagic && PositionGetString(POSITION_SYMBOL) == _Symbol)
      {
         g_hasPos = true; g_ticket = tk;
         g_side  = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? +1 : -1;
         g_entry = PositionGetDouble(POSITION_PRICE_OPEN);
         g_stop  = PositionGetDouble(POSITION_SL);
         g_R     = MathAbs(g_entry - g_stop);
         g_origLots = PositionGetDouble(POSITION_VOLUME);
         g_entryBarTime = iTime(_Symbol, PERIOD_M15, 0);
         g_banked = 0; g_c2cState = 1; g_scaling = false;  // manage conservatively after a restart
         return;
      }
   }
}
//+------------------------------------------------------------------+
