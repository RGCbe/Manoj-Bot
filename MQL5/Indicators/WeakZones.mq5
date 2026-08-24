//+------------------------------------------------------------------+
//|                                                     WeakZones.mq5 |
//|                                     Manoj-Bot - Weak Zone marker  |
//|                                                                  |
//|  Marks "weak point / reversal zones" on the chart, implementing  |
//|  the rules from the trade-plan notes (Class Day 3, Day 4, Day 6):|
//|                                                                  |
//|   1. FORMATION - three same-colour candles where each one breaks |
//|      the previous:                                               |
//|        * 3 green -> higher highs -> bullish reversal -> SUPPORT  |
//|        * 3 red   -> lower lows   -> bearish reversal -> RESISTANCE|
//|                                                                  |
//|   2. ZONE BAND - drawn from body to wick, anchored to the        |
//|      nearest low/high (formation candles + a lookback):          |
//|        * support   : top = lowest body, bottom = lowest wick     |
//|        * resistance: top = highest wick, bottom = highest body   |
//|                                                                  |
//|   3. LIVE / DEAD - the zone stays LIVE while price only touches  |
//|      into it. It DIES the moment a wick OR body fully breaks     |
//|      through the far edge, and the box stops at that bar.        |
//+------------------------------------------------------------------+
#property copyright "Manoj-Bot"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs -------------------------------------------------------------------
input int    InpAnchorLookback   = 2;            // Candles before the 1st candle to include in the anchor
input bool   InpAllowDoji        = false;        // Allow a doji (open==close) inside the 3-candle run
input int    InpDeathBufferPts   = 0;            // Extra points past the far edge required to call it DEAD (0 = exact)
input int    InpMaxZones         = 60;           // Max zones kept on the chart
input bool   InpAlternate        = true;         // Alternate sides (support -> resistance -> support)
input bool   InpExtendRight      = true;         // Stretch live zones to the current bar
input bool   InpFill             = true;         // Fill live zones
input color  InpSupportColor     = clrLimeGreen; // Live support (from 3 green)
input color  InpResistColor      = clrTomato;    // Live resistance (from 3 red)
input color  InpDeadColor        = clrGray;      // Dead zone
input string InpPrefix           = "WZ_";        // Chart-object name prefix

//--- one marked zone ----------------------------------------------------------
struct Zone
{
   string   name;
   bool     isSupport;   // true = support (3 green), false = resistance (3 red)
   double   top;         // upper price of the band
   double   bottom;      // lower price of the band
   datetime leftTime;    // left edge (anchor bar)
   datetime rightTime;   // right edge (grows while live, frozen on death)
   bool     alive;
};

Zone     g_zones[];
datetime g_lastBar = 0;
// Weak points alternate: 1 = last marked was a support, -1 = resistance, 0 = none
int      g_lastSide = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   ArrayResize(g_zones,0);
   g_lastBar = 0;
   g_lastSide = 0;
   ObjectsDeleteAll(0,InpPrefix);
   return(INIT_SUCCEEDED);
}
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0,InpPrefix);
   ChartRedraw();
}
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total < 4 + InpAnchorLookback)
      return(rates_total);

   // series indexing: 0 = current (forming) bar, 1 = last closed bar
   ArraySetAsSeries(time,true);
   ArraySetAsSeries(open,true);
   ArraySetAsSeries(high,true);
   ArraySetAsSeries(low,true);
   ArraySetAsSeries(close,true);

   // full rebuild over history on first run / recompile
   if(prev_calculated == 0)
   {
      ObjectsDeleteAll(0,InpPrefix);
      ArrayResize(g_zones,0);
      g_lastSide = 0;
      for(int bar = rates_total - 1; bar >= 1; bar--)
         ProcessBar(bar, time, open, high, low, close, rates_total);
      g_lastBar = time[0];
      ChartRedraw();
      return(rates_total);
   }

   // no new closed bar yet -> only keep live zones stretched to "now"
   if(time[0] == g_lastBar)
   {
      if(InpExtendRight)
         UpdateLiveRightEdges(time[0]);
      return(rates_total);
   }

   // a bar just closed (index 1) -> process it
   g_lastBar = time[0];
   ProcessBar(1, time, open, high, low, close, rates_total);
   if(InpExtendRight)
      UpdateLiveRightEdges(time[0]);
   ChartRedraw();
   return(rates_total);
}

//+------------------------------------------------------------------+
//| Colour of a candle: 1 = green, -1 = red, 0 = doji                |
//+------------------------------------------------------------------+
int CandleColor(const double o, const double c)
{
   if(c > o) return(1);
   if(c < o) return(-1);
   return(0);
}

//+------------------------------------------------------------------+
//| Process one closed bar `b`: age existing zones, then look for a  |
//| new formation that COMPLETED on that bar (c3=b, c2=b+1, c1=b+2). |
//+------------------------------------------------------------------+
void ProcessBar(const int b,
                const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const int rates_total)
{
   double buf = InpDeathBufferPts * _Point;

   //--- (a) age every live zone against bar b -----------------------------
   for(int i = 0; i < ArraySize(g_zones); i++)
   {
      if(!g_zones[i].alive) continue;

      bool died = g_zones[i].isSupport ? (low[b]  < g_zones[i].bottom - buf)   // fully below the band
                                       : (high[b] > g_zones[i].top    + buf);  // fully above the band
      g_zones[i].rightTime = time[b];
      if(died)
         g_zones[i].alive = false;
      DrawZone(g_zones[i]);
   }

   //--- (b) detect a formation completing on bar b ------------------------
   int c3 = b, c2 = b + 1, c1 = b + 2;
   int wEnd = c1 + InpAnchorLookback;          // oldest bar in the anchor window
   if(wEnd > rates_total - 1) return;

   int cc[3];
   cc[0] = CandleColor(open[c1], close[c1]);
   cc[1] = CandleColor(open[c2], close[c2]);
   cc[2] = CandleColor(open[c3], close[c3]);

   int sign = 0, nonDoji = 0;
   bool conflict = false;
   for(int k = 0; k < 3; k++)
   {
      if(cc[k] == 0) continue;
      nonDoji++;
      if(sign == 0) sign = cc[k];
      else if(sign != cc[k]) conflict = true;
   }
   if(conflict) return;                         // mixed colours
   if(sign == 0) return;                        // all doji
   if(!InpAllowDoji && nonDoji < 3) return;     // doji present but not allowed

   bool isGreen = (sign == 1);

   // each candle breaks the previous (higher highs / lower lows)
   bool breaks = isGreen ? (high[c2] > high[c1] && high[c3] > high[c2])
                         : (low[c2]  < low[c1]  && low[c3]  < low[c2]);
   if(!breaks) return;

   // weak points alternate: a support is followed by a resistance, and back
   if(InpAlternate && g_lastSide == (isGreen ? 1 : -1)) return;

   //--- build the band from the anchor window -----------------------------
   //    (extremeIdx = the lowest / highest candle; the box starts there)
   double top, bottom;
   int    extremeIdx = c3;
   if(isGreen)
   {
      bottom = low[c3];                  // low wick
      top    = MathMin(open[c3], close[c3]); // low body
      for(int k = c3; k <= wEnd; k++)
      {
         if(low[k] < bottom) { bottom = low[k]; extremeIdx = k; }
         top = MathMin(top, MathMin(open[k], close[k]));
      }
   }
   else
   {
      top    = high[c3];                 // high wick
      bottom = MathMax(open[c3], close[c3]); // high body
      for(int k = c3; k <= wEnd; k++)
      {
         if(high[k] > top) { top = high[k]; extremeIdx = k; }
         bottom = MathMax(bottom, MathMax(open[k], close[k]));
      }
   }
   if(top <= bottom) top = bottom + _Point;     // guarantee some thickness

   //--- skip if it overlaps a still-live zone of the same type ------------
   for(int i = 0; i < ArraySize(g_zones); i++)
   {
      if(g_zones[i].alive && g_zones[i].isSupport == isGreen)
      {
         bool overlap = !(top < g_zones[i].bottom || bottom > g_zones[i].top);
         if(overlap) return;
      }
   }

   //--- create it ---------------------------------------------------------
   Zone z;
   z.isSupport = isGreen;
   z.top       = top;
   z.bottom    = bottom;
   z.leftTime  = time[extremeIdx];   // box starts at the lowest/highest candle
   z.rightTime = time[c3];
   z.alive     = true;
   z.name      = InpPrefix + (isGreen ? "S_" : "R_") + IntegerToString((long)time[c3]);
   AddZone(z);
   g_lastSide = isGreen ? 1 : -1;
   DrawZone(z);
}

//+------------------------------------------------------------------+
void AddZone(Zone &z)
{
   int n = ArraySize(g_zones);
   ArrayResize(g_zones, n + 1);
   g_zones[n] = z;

   // enforce the cap by dropping the oldest zones
   int total = ArraySize(g_zones);
   if(total > InpMaxZones)
   {
      int remove = total - InpMaxZones;
      for(int i = 0; i < remove; i++)
         ObjectDelete(0, g_zones[i].name);
      for(int i = 0; i + remove < total; i++)
         g_zones[i] = g_zones[i + remove];
      ArrayResize(g_zones, total - remove);
   }
}

//+------------------------------------------------------------------+
void UpdateLiveRightEdges(const datetime tnow)
{
   for(int i = 0; i < ArraySize(g_zones); i++)
   {
      if(g_zones[i].alive)
      {
         g_zones[i].rightTime = tnow;
         ObjectSetInteger(0, g_zones[i].name, OBJPROP_TIME, 1, tnow);
      }
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
void DrawZone(Zone &z)
{
   if(ObjectFind(0, z.name) < 0)
      ObjectCreate(0, z.name, OBJ_RECTANGLE, 0, z.leftTime, z.top, z.rightTime, z.bottom);

   ObjectSetInteger(0, z.name, OBJPROP_TIME,  0, z.leftTime);
   ObjectSetDouble (0, z.name, OBJPROP_PRICE, 0, z.top);
   ObjectSetInteger(0, z.name, OBJPROP_TIME,  1, z.rightTime);
   ObjectSetDouble (0, z.name, OBJPROP_PRICE, 1, z.bottom);

   color c = z.alive ? (z.isSupport ? InpSupportColor : InpResistColor) : InpDeadColor;
   ObjectSetInteger(0, z.name, OBJPROP_COLOR,      c);
   ObjectSetInteger(0, z.name, OBJPROP_FILL,       z.alive ? InpFill : false);
   ObjectSetInteger(0, z.name, OBJPROP_BACK,       true);
   ObjectSetInteger(0, z.name, OBJPROP_STYLE,      z.alive ? STYLE_SOLID : STYLE_DOT);
   ObjectSetInteger(0, z.name, OBJPROP_WIDTH,      1);
   ObjectSetInteger(0, z.name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, z.name, OBJPROP_HIDDEN,     true);
}
//+------------------------------------------------------------------+
