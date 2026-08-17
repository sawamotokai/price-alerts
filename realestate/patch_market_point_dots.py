#!/usr/bin/env python3
"""Decorate every market-chart observation with a visible circular point."""
from pathlib import Path
import re

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
s = PATH.read_text(encoding="utf-8")
original = s

DOT_CODE = r'''const MARKET_POINT_DOTS_VERSION=2;
function decorateMarketPoints(){
  const canvas=$('marketCanvas');
  if(!canvas||!marketGeometry?.length)return;
  const ctx=canvas.getContext('2d');
  if(!ctx)return;

  // marketGeometry is stored in CSS-pixel coordinates. Canvas backing pixels
  // are devicePixelRatio-scaled, so explicitly restore that mapping here.
  const cssWidth=canvas.clientWidth||canvas.getBoundingClientRect().width||canvas.width;
  const cssHeight=canvas.clientHeight||canvas.getBoundingClientRect().height||canvas.height;
  const scaleX=cssWidth?canvas.width/cssWidth:1;
  const scaleY=cssHeight?canvas.height/cssHeight:1;
  const radius=isMobile()?5.2:4.4;

  ctx.save();
  ctx.setTransform(scaleX,0,0,scaleY,0,0);
  for(const series of marketGeometry){
    const id=series?.item?.id??'';
    const fill=typeof colorFor==='function'?colorFor(id,.98):'#2563eb';
    for(const point of series.geom||[]){
      if(!Number.isFinite(point.px)||!Number.isFinite(point.py))continue;

      // White halo makes the point visible even when many horizontal lines overlap.
      ctx.beginPath();
      ctx.arc(point.px,point.py,radius+1.7,0,Math.PI*2);
      ctx.fillStyle='rgba(255,255,255,.98)';
      ctx.fill();

      ctx.beginPath();
      ctx.arc(point.px,point.py,radius,0,Math.PI*2);
      ctx.fillStyle=fill;
      ctx.fill();
      ctx.lineWidth=1.15;
      ctx.strokeStyle='rgba(15,23,42,.32)';
      ctx.stroke();
    }
  }
  ctx.restore();
}
function drawMarketChart(scope){
  drawMarketChartBase(scope);
  decorateMarketPoints();
}
'''

if "MARKET_POINT_DOTS_VERSION=2" not in s:
    if "MARKET_POINT_DOTS_VERSION=1" in s:
        start = s.index("const MARKET_POINT_DOTS_VERSION=1;")
        end = s.index("function nearestMarketPoint(e,maxDistance=32){", start)
        s = s[:start] + DOT_CODE + s[end:]
    else:
        pattern = r"function\s+drawMarketChart\s*\(scope\)\s*\{"
        if not re.search(pattern, s):
            raise SystemExit("Could not locate drawMarketChart(scope)")
        s = re.sub(pattern, "function drawMarketChartBase(scope){", s, count=1)
        marker = "function nearestMarketPoint(e,maxDistance=32){"
        if marker not in s:
            raise SystemExit("Could not locate nearestMarketPoint marker")
        s = s.replace(marker, DOT_CODE + marker, 1)

PATH.write_text(s, encoding="utf-8")
print("market point dots v2 applied" if s != original else "market point dots v2 already present")
