#!/usr/bin/env python3
"""
weak_zones_ref.py  -  reference implementation of the Manoj-Bot weak-zone rule.

This mirrors, 1:1, the logic in MQL5/Indicators/WeakZones.mq5 so you can verify
on a chart (here, or against your own data) that the bot marks weak zones the
same way you do by hand.

Rules (from the trade-plan notes, pages 1-3):
  1. FORMATION - 3 same-colour candles, each breaking the previous
        3 green -> higher highs -> bullish reversal -> SUPPORT zone
        3 red   -> lower  lows  -> bearish reversal -> RESISTANCE zone
  2. BAND - drawn body->wick, anchored to the nearest low/high
        support   : top = lowest body,  bottom = lowest wick
        resistance: top = highest wick, bottom = highest body
  3. LIVE / DEAD - stays LIVE while price only touches into the band;
     DIES when a wick OR body fully breaks through the far edge, and the
     box stops (right edge frozen) at that bar.

A candle is a 4-tuple: (open, high, low, close).
No third-party dependencies are required to compute zones; rendering a PNG
uses PyMuPDF only if it is installed.
"""

from __future__ import annotations

O, H, L, C = 0, 1, 2, 3   # tuple indices


def candle_color(c):
    """1 = green (bullish), -1 = red (bearish), 0 = doji."""
    if c[C] > c[O]:
        return 1
    if c[C] < c[O]:
        return -1
    return 0


def detect_weak_zones(candles, lookback=2, allow_doji=False, death_buffer=0.0):
    """Return the list of zones marked over `candles` (processed chronologically)."""
    n = len(candles)
    zones = []

    for j in range(n):
        # (a) age every live zone against bar j
        for z in zones:
            if not z["alive"] or j <= z["create_idx"]:
                continue
            if z["is_support"]:
                died = candles[j][L] < z["bottom"] - death_buffer
            else:
                died = candles[j][H] > z["top"] + death_buffer
            z["right_idx"] = j
            if died:
                z["alive"] = False
                z["death_idx"] = j

        # (b) formation completing on bar j: c3=j, c2=j-1, c1=j-2
        c3, c2, c1 = j, j - 1, j - 2
        w_end = c1 - lookback                      # oldest bar in the anchor window
        if c1 < 0 or w_end < 0:
            continue

        cols = [candle_color(candles[c1]), candle_color(candles[c2]), candle_color(candles[c3])]
        sign, non_doji, conflict = 0, 0, False
        for cc in cols:
            if cc == 0:
                continue
            non_doji += 1
            if sign == 0:
                sign = cc
            elif sign != cc:
                conflict = True
        if conflict or sign == 0:
            continue
        if not allow_doji and non_doji < 3:
            continue

        is_green = (sign == 1)

        # each candle breaks the previous
        if is_green:
            breaks = candles[c2][H] > candles[c1][H] and candles[c3][H] > candles[c2][H]
        else:
            breaks = candles[c2][L] < candles[c1][L] and candles[c3][L] < candles[c2][L]
        if not breaks:
            continue

        window = list(range(w_end, c3 + 1))
        if is_green:
            ext = min(window, key=lambda k: candles[k][L])                    # lowest-low candle
            bottom = candles[ext][L]                                          # low wick
            top = min(min(candles[k][O], candles[k][C]) for k in window)      # low body
        else:
            ext = max(window, key=lambda k: candles[k][H])                    # highest-high candle
            top = candles[ext][H]                                             # high wick
            bottom = max(max(candles[k][O], candles[k][C]) for k in window)   # high body
        if top <= bottom:
            top = bottom + 1e-9

        # skip if it overlaps a still-live zone of the same type
        overlaps = any(
            z["alive"] and z["is_support"] == is_green
            and not (top < z["bottom"] or bottom > z["top"])
            for z in zones
        )
        if overlaps:
            continue

        zones.append({
            "is_support": is_green,
            "top": top, "bottom": bottom,
            "left_idx": ext, "create_idx": c3, "right_idx": c3,   # box starts at the lowest/highest candle
            "alive": True, "death_idx": None,
        })

    return zones


# --------------------------------------------------------------------------- #
#  Rendering (SVG -> optional PNG). Pure standard library for the SVG.
# --------------------------------------------------------------------------- #
def render_svg(candles, zones, callouts=None, width=1100, height=640,
               title="", subtitle=""):
    callouts = callouts or []
    ml, mr, mt, mb = 78, 210, 64, 44
    plot_w = width - ml - mr
    plot_h = height - mt - mb
    n = len(candles)
    slot = plot_w / n
    body_w = slot * 0.6

    pmax = max(c[H] for c in candles)
    pmin = min(c[L] for c in candles)
    pad = (pmax - pmin) * 0.08
    pmax += pad
    pmin -= pad

    def x(i):   # centre of candle i
        return ml + (i + 0.5) * slot

    def y(p):
        return mt + (pmax - p) / (pmax - pmin) * plot_h

    s = []
    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Arial, sans-serif">')
    s.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    if title:
        s.append(f'<text x="24" y="30" font-size="18" font-weight="700" fill="#0f172a">{title}</text>')
    if subtitle:
        s.append(f'<text x="24" y="52" font-size="13" fill="#475569">{subtitle}</text>')

    # price gridlines
    steps = 6
    for k in range(steps + 1):
        p = pmin + (pmax - pmin) * k / steps
        yy = y(p)
        s.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+plot_w}" y2="{yy:.1f}" stroke="#eef2f7" stroke-width="1"/>')
        s.append(f'<text x="{ml-8}" y="{yy+4:.1f}" font-size="11" fill="#64748b" text-anchor="end">{p:,.0f}</text>')

    # zones (behind candles)
    for z in zones:
        xl = ml + z["left_idx"] * slot
        xr = ml + (z["right_idx"] + 1) * slot
        yt, yb = y(z["top"]), y(z["bottom"])
        if z["alive"]:
            fill = "#22c55e" if z["is_support"] else "#ef4444"
            stroke = "#16a34a" if z["is_support"] else "#dc2626"
            dash = ""
        else:
            fill = "#94a3b8"
            stroke = "#64748b"
            dash = ' stroke-dasharray="6 4"'
        s.append(f'<rect x="{xl:.1f}" y="{yt:.1f}" width="{xr-xl:.1f}" height="{yb-yt:.1f}" '
                 f'fill="{fill}" fill-opacity="0.15" stroke="{stroke}" stroke-width="1.6"{dash}/>')

    # candles
    for i, c in enumerate(candles):
        up = c[C] >= c[O]
        stroke = "#16a34a" if up else "#dc2626"
        fill = "#22c55e" if up else "#f87171"
        cx = x(i)
        s.append(f'<line x1="{cx:.1f}" y1="{y(c[H]):.1f}" x2="{cx:.1f}" y2="{y(c[L]):.1f}" stroke="{stroke}" stroke-width="1.4"/>')
        by = y(max(c[O], c[C]))
        bh = max(1.5, abs(y(c[O]) - y(c[C])))
        s.append(f'<rect x="{cx-body_w/2:.1f}" y="{by:.1f}" width="{body_w:.1f}" height="{bh:.1f}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')

    # callouts: dict(idx, price, text, color, dy)
    for co in callouts:
        cx = x(co["idx"])
        cy = y(co["price"])
        col = co.get("color", "#0f172a")
        dy = co.get("dy", 0)
        if co.get("vline"):
            s.append(f'<line x1="{cx:.1f}" y1="{mt}" x2="{cx:.1f}" y2="{mt+plot_h}" '
                     f'stroke="{col}" stroke-width="1.4" stroke-dasharray="5 4"/>')
        s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{col}"/>')
        s.append(f'<text x="{cx+8:.1f}" y="{cy+dy:.1f}" font-size="12" font-weight="600" fill="{col}">{co["text"]}</text>')

    s.append('</svg>')
    return "\n".join(s)


def save_png(svg_text, png_path):
    """Convert the SVG to PNG via PyMuPDF if available; else write the .svg."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=svg_text.encode("utf-8"), filetype="svg")
        pdf = pymupdf.open("pdf", doc.convert_to_pdf())
        pix = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2))
        pix.save(png_path)
        return png_path
    except Exception as e:
        svg_path = png_path.rsplit(".", 1)[0] + ".svg"
        with open(svg_path, "w") as f:
            f.write(svg_text)
        return svg_path


# --------------------------------------------------------------------------- #
#  Demo dataset - one full life-cycle of a support zone (LIVE -> DEAD)
# --------------------------------------------------------------------------- #
DEMO = [
    (76500, 76540, 76350, 76380),  # 0  red   \
    (76380, 76420, 76180, 76220),  # 1  red    | down-move
    (76220, 76260, 75980, 76020),  # 2  red    |
    (76020, 76060, 75600, 75900),  # 3  red   /  capitulation: wick 75600, body 75900
    (75900, 76080, 75870, 76050),  # 4  green  \
    (76050, 76240, 76020, 76210),  # 5  green   | 3-green reversal (higher highs)
    (76210, 76400, 76180, 76370),  # 6  green  /  FORMATION completes -> support zone
    (76370, 76520, 76330, 76480),  # 7  green  \  rally
    (76480, 76600, 76420, 76450),  # 8  red    /
    (76450, 76470, 75720, 76050),  # 9  red       wick dips to 75720 (into band) -> LIVE
    (76050, 76300, 76000, 76260),  # 10 green  \  bounce off the zone
    (76260, 76420, 76230, 76390),  # 11 green  /
    (76390, 76430, 76300, 76340),  # 12 red
    (76340, 76500, 76300, 76470),  # 13 green
    (76470, 76490, 75500, 75700),  # 14 red       wick to 75500 (< 75600) -> DEAD, box stops
    (75700, 75780, 75600, 75750),  # 15 green
    (75750, 75800, 75550, 75600),  # 16 red
    (75600, 75720, 75560, 75690),  # 17 green
]


def _demo():
    zones = detect_weak_zones(DEMO, lookback=2)
    print("Zones marked:")
    for z in zones:
        state = "LIVE" if z["alive"] else f"DEAD @ bar {z['death_idx']}"
        kind = "support" if z["is_support"] else "resistance"
        print(f"  {kind:10s} band {z['bottom']:,.0f} - {z['top']:,.0f}  "
              f"(formed @ bar {z['create_idx']}, left @ bar {z['left_idx']}, {state})")

    callouts = [
        {"idx": 5, "price": 76500, "text": "3 GREEN - each breaks the previous", "color": "#0f9d63", "dy": -6},
        {"idx": 3, "price": 75900, "text": "low body 75,900", "color": "#b45309", "dy": -4},
        {"idx": 3, "price": 75600, "text": "low wick 75,600", "color": "#b45309", "dy": 14},
        {"idx": 9, "price": 75720, "text": "wick touches in -> still LIVE", "color": "#2563eb", "dy": 4},
        {"idx": 14, "price": 75500, "text": "wick fully below -> DEAD, box stops", "color": "#dc2626", "dy": 16, "vline": True},
    ]
    svg = render_svg(
        DEMO, zones, callouts,
        title="WeakZones - reference output (support zone: LIVE then DEAD)",
        subtitle="Zone = low body -> low wick. Stays live while price only wicks in; dies when a wick/body fully breaks below.",
    )
    out = save_png(svg, "weak_zones_demo.png")
    print(f"\nChart written to: {out}")


if __name__ == "__main__":
    _demo()
