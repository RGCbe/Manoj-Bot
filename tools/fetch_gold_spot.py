#!/usr/bin/env python3
"""Fetch real spot XAUUSD 15m candles from Dukascopy (free, no API key).

Dukascopy publishes per-hour tick files as LZMA-compressed .bi5 (20 bytes/tick:
big-endian ms-offset, ask, bid, ask-vol, bid-vol). Prices scale by /1000 for
gold. This aggregates the mid price into 15-minute OHLC bars - close to what
TradingView spot gold shows, unlike Yahoo GC=F futures.

    python3 tools/fetch_gold_spot.py            # last 30 days -> gold_spot.json
"""
from concurrent.futures import ThreadPoolExecutor
UA="Mozilla/5.0"; SCALE=1000.0
def hour_ticks(args):
    inst,dt=args
    url=f"https://datafeed.dukascopy.com/datafeed/{inst}/{dt.year}/{dt.month-1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    for _ in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":UA})
            raw=urllib.request.urlopen(req,timeout=25).read()
            if not raw: return []
            data=lzma.decompress(raw); out=[]
            for i in range(0,len(data),20):
                ms,ask,bid,_,_=struct.unpack(">IIIff",data[i:i+20])
                out.append((dt+datetime.timedelta(milliseconds=ms),(ask+bid)/2000.0))
            return out
        except urllib.error.HTTPError as e:
            if e.code==404: return []
        except Exception: pass
    return []

start=datetime.datetime(2026,7,25,0)   # a bit before Aug for zone history
end=datetime.datetime(2026,8,24,0)
hours=[(("XAUUSD"), start+datetime.timedelta(hours=h)) for h in range(int((end-start).total_seconds()//3600))]
print(f"fetching {len(hours)} hours with 16 threads...", file=sys.stderr)
bars={}
with ThreadPoolExecutor(max_workers=16) as ex:
    for ticks in ex.map(hour_ticks, hours):
        for t,px in ticks:
            b=t.replace(minute=(t.minute//15)*15,second=0,microsecond=0)
            k=int(b.timestamp())
            if k not in bars: bars[k]=[px,px,px,px]
            else:
                o=bars[k]; o[1]=max(o[1],px); o[2]=min(o[2],px); o[3]=px
rows=[{"t":k,"o":v[0],"h":v[1],"l":v[2],"c":v[3]} for k,v in sorted(bars.items())]
json.dump(rows,open("gold_spot_duka.json","w"))
print(f"DONE {len(rows)} bars, {rows[0]['c']:.1f}..{rows[-1]['c']:.1f}")
