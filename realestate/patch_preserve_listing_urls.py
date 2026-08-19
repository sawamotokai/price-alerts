#!/usr/bin/env python3
"""Make dashboard outbound links use the stored source URL verbatim.

The data pipeline already stores the category, ward and optional SUUMO /tenpo/
suffix in each record. Reconstructing a URL from only the nc_ number destroys
that information and turns every SUUMO land record into a dead used-house URL.
"""
from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
MARKER = "const LISTING_URL_PRESERVATION_VERSION=1;"
START = "function listingUrl(x){"
LINK_START = "function linkHtml(x,label='物件を開く'){"

source = PATH.read_text(encoding="utf-8")

replacement = r'''const LISTING_URL_PRESERVATION_VERSION=1;
function listingUrl(x){let raw=String(x.url||'').trim();if(!raw)return'';if(sourceLabel(x.source)==='SUUMO'){try{let u=new URL(raw);u.hash='';u.search='';u.pathname=(u.pathname.replace(/\/+$/,'')||'/')+'/';return u.toString()}catch(_){return raw.replace(/[?#].*$/,'').replace(/\/+$/,'')+'/'}}return raw}
function linkHtml(x,label='物件を開く'){'''

listing_start = source.find(START)
if listing_start < 0:
    raise SystemExit("listingUrl function not found")
link_start = source.find(LINK_START, listing_start)
if link_start < 0:
    raise SystemExit("linkHtml function not found after listingUrl")
if source.find(START, listing_start + 1) >= 0:
    raise SystemExit("multiple listingUrl functions found")
if source.find(LINK_START, link_start + 1) >= 0:
    raise SystemExit("multiple linkHtml functions found")

# Repatch idempotently by replacing an existing marker together with the block.
marker_start = source.rfind(MARKER, max(0, listing_start - len(MARKER) - 4), listing_start)
replace_start = marker_start if marker_start >= 0 else listing_start
replace_end = link_start + len(LINK_START)
source = source[:replace_start] + replacement + source[replace_end:]

for forbidden in (
    "https://suumo.jp/chukoikkodate/tokyo/sc_${scope}/nc_${id}/",
    "x.ward==='目黒区'?'meguro':'shinagawa'",
):
    if forbidden in source:
        raise SystemExit(f"hard-coded SUUMO URL reconstruction remains: {forbidden}")
if source.count(MARKER) != 1:
    raise SystemExit("listing URL preservation marker missing or duplicated")
if source.count(START) != 1 or source.count(LINK_START) != 1:
    raise SystemExit("listing URL functions were duplicated while patching")

PATH.write_text(source, encoding="utf-8")
print(f"preserved exact outbound listing URLs in {PATH}")
