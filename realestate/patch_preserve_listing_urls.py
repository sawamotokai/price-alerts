#!/usr/bin/env python3
"""Make dashboard outbound links use the stored source URL verbatim.

The data pipeline already stores the category, ward and optional SUUMO /tenpo/
suffix in each record. Reconstructing a URL from only the nc_ number destroys
that information and turns every SUUMO land record into a dead used-house URL.
"""
from __future__ import annotations

import re
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
MARKER = "const LISTING_URL_PRESERVATION_VERSION=1;"

source = PATH.read_text(encoding="utf-8")

replacement = r'''const LISTING_URL_PRESERVATION_VERSION=1;
function listingUrl(x){let raw=String(x.url||'').trim();if(!raw)return'';if(sourceLabel(x.source)==='SUUMO'){try{let u=new URL(raw);u.hash='';u.search='';u.pathname=(u.pathname.replace(/\/+$/,'')||'/')+'/';return u.toString()}catch(_){return raw.replace(/[?#].*$/,'').replace(/\/+$/,'')+'/'}}return raw}
function linkHtml(x,label='物件を開く'){'''

pattern = re.compile(
    r"(?:const LISTING_URL_PRESERVATION_VERSION=1;\s*)?"
    r"function listingUrl\(x\)\{.*?\}"
    r"function linkHtml\(x,label='物件を開く'\)\{",
    flags=re.S,
)

matches = list(pattern.finditer(source))
if len(matches) != 1:
    raise SystemExit(f"expected exactly one listingUrl/linkHtml block, found {len(matches)}")
source = pattern.sub(lambda _: replacement, source, count=1)

# The old implementation is the regression signature. It must never survive.
for forbidden in (
    "https://suumo.jp/chukoikkodate/tokyo/sc_${scope}/nc_${id}/",
    "x.ward==='目黒区'?'meguro':'shinagawa'",
):
    if forbidden in source:
        raise SystemExit(f"hard-coded SUUMO URL reconstruction remains: {forbidden}")
if source.count(MARKER) != 1:
    raise SystemExit("listing URL preservation marker missing or duplicated")

PATH.write_text(source, encoding="utf-8")
print(f"preserved exact outbound listing URLs in {PATH}")
