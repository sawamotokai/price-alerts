#!/usr/bin/env python3
"""Expand the runtime collectors/dashboard scope to Ota and SUUMO land."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
collector = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "collector.py"
adcast = ROOT / "adcast_collector.py"
freehold = ROOT / "enforce_freehold_v2.py"


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"could not patch {label}")
    return text.replace(old, new, 1)


s = collector.read_text(encoding="utf-8")
s = replace_required(
    s,
    '            "目黒区": "https://suumo.jp/chukoikkodate/tokyo/sc_meguro/",\n        },\n        "listing_pattern": re.compile(r"/(?:chuko)?ikkodate/tokyo/[^?#\\\"\']+/nc_(\\d+)/?"),',
    '            "目黒区": "https://suumo.jp/chukoikkodate/tokyo/sc_meguro/",\n            "大田区": "https://suumo.jp/chukoikkodate/tokyo/sc_ota/",\n        },\n        "land_wards": {\n            "品川区": "https://suumo.jp/tochi/tokyo/sc_shinagawa/",\n            "目黒区": "https://suumo.jp/tochi/tokyo/sc_meguro/",\n            "大田区": "https://suumo.jp/tochi/tokyo/sc_ota/",\n        },\n        "listing_pattern": re.compile(r"/(?:(?:chuko)?ikkodate|tochi)/tokyo/[^?#\\\"\']+/nc_(\\d+)/?"),',
    "SUUMO Ota/land config",
)
s = replace_required(
    s,
    '            "目黒区": "https://www.homes.co.jp/kodate/chuko/tokyo/meguro-city/list/",\n        },',
    '            "目黒区": "https://www.homes.co.jp/kodate/chuko/tokyo/meguro-city/list/",\n            "大田区": "https://www.homes.co.jp/kodate/chuko/tokyo/ota-city/list/",\n        },',
    "HOME'S Ota config",
)
s = s.replace('東京都(?:品川区|目黒区)', '東京都(?:品川区|目黒区|大田区)')
old_loop = '''    for ward, base_url in SOURCE_CONFIGS[source]["wards"].items():
        pages, coverage = crawl_index_pages(fetcher, base_url, source)
        ward_listings: dict[str, Listing] = {}
        for page_url, html in pages:
            for listing in parse_listings_from_page(source, ward, page_url, html):
                ward_listings[listing.listing_id] = listing
                all_listings[listing.listing_id] = listing
        coverage["listing_rows"] = len(ward_listings)
        coverage["price_rows"] = sum(item.price_yen is not None for item in ward_listings.values())
        coverage["individual_url_rows"] = len(ward_listings)
        ward_coverage[ward] = coverage
'''
new_loop = '''    targets = [(ward, ward, url) for ward, url in SOURCE_CONFIGS[source]["wards"].items()]
    if source == "suumo":
        targets.extend((f"{ward}・土地", ward, url) for ward, url in SOURCE_CONFIGS[source].get("land_wards", {}).items())
    for coverage_key, ward, base_url in targets:
        pages, coverage = crawl_index_pages(fetcher, base_url, source)
        ward_listings: dict[str, Listing] = {}
        for page_url, html in pages:
            for listing in parse_listings_from_page(source, ward, page_url, html):
                ward_listings[listing.listing_id] = listing
                all_listings[listing.listing_id] = listing
        coverage["listing_rows"] = len(ward_listings)
        coverage["price_rows"] = sum(item.price_yen is not None for item in ward_listings.values())
        coverage["individual_url_rows"] = len(ward_listings)
        ward_coverage[coverage_key] = coverage
'''
s = replace_required(s, old_loop, new_loop, "multi-index collection loop")
collector.write_text(s, encoding="utf-8")

s = adcast.read_text(encoding="utf-8")
s = replace_required(s, 'TARGETS = {"品川区": "13109", "目黒区": "13110"}', 'TARGETS = {"品川区": "13109", "目黒区": "13110", "大田区": "13111"}', "ADCAST Ota target")
s = s.replace('東京都(?:品川区|目黒区)', '東京都(?:品川区|目黒区|大田区)')
adcast.write_text(s, encoding="utf-8")

s = freehold.read_text(encoding="utf-8")
s = replace_required(s, 'TARGET_WARDS = {"品川区", "目黒区"}', 'TARGET_WARDS = {"品川区", "目黒区", "大田区"}', "freehold ward set")
s = replace_required(
    s,
    'if source == "suumo" and "/sc_shinagawa/" not in url and "/sc_meguro/" not in url:',
    'if source == "suumo" and not any(token in url for token in ("/sc_shinagawa/", "/sc_meguro/", "/sc_ota/")):',
    "freehold SUUMO URL scope",
)
freehold.write_text(s, encoding="utf-8")

print("Ota + SUUMO land runtime scope patch applied")
