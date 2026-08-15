#!/usr/bin/env python3
"""Decorate every market-chart observation with a persistent circular point."""
from pathlib import Path
import re

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
s = PATH.read_text(encoding="utf-8")
original = s

if "MARKET_POINT_DOTS_VERSION=1" not in s:
    # Rename the existing renderer and wrap it so dots are always painted after
    # lines/axes have finished rendering and marketGeometry has been populated.
    pattern = r"function\s+drawMarketChart\s*\(scope\)\s*\{"
    if not re.search(pattern, s):
        raise SystemExit("Could not locate drawMarketChart(scope)")
    s = re.sub(pattern, "function drawMarketChartBase(scope){", s, count=1)

    marker = "function nearestMarketPoint(e,maxDistance=32){"
    if marker not in s:
        raise SystemExit("Could not locate nearestMarketPoint marker")

    patch = r'''const MARKET_POINT_DOTS_VERSION=1;
function decorateMarketPoints(){
  const canvas=$('marketCanvas');
  if(!canvas||!marketGeometry?.length)return;
  const ctx=canvas.getContext('2d');
  if(!ctx)return;
  const radius=isMobile()?3.8:3.1;
  ctx.save();
  for(const series of marketGeometry){
    const id=series?.item?.id??'';
    const fill=typeof colorFor==='function'?colorFor(id,.92):'#2563eb';
    for(const point of series.geom||[]){
      if(!Number.isFinite(point.px)||!Number.isFinite(point.py))continue;
      ctx.beginPath();
      ctx.arc(point.px,point.py,radius,0,Math.PI*2);
      ctx.fillStyle=fill;
      ctx.fill();
      ctx.lineWidth=1.35;
      ctx.strokeStyle='rgba(255,255,255,.96)';
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
    s = s.replace(marker, patch + marker, 1)

PATH.write_text(s, encoding="utf-8")
print("market point dots applied" if s != original else "market point dots already present")

# Workflow trigger marker: 2026-08-15
