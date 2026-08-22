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
# With complete per-ward/category crawling, one missed successful crawl is
# enough to remove a stale listing from the public dashboard. Failed/partial
# crawls are already marked incomplete and must not deactivate records.
s = re.sub(r'^MAX_MISSING_RUNS\s*=.*$', 'MAX_MISSING_RUNS = 1', s, flags=re.M)

# SUUMO result pages contain recommendation cards for other wards. The old
# parser accepted every matching /nc_/ link and assigned the current ward,
# which polluted the dashboard. Require the parsed physical address to match
# the ward currently being crawled. If the address cannot be parsed, skip it
# rather than publishing a potentially wrong/dead record.
#
# Treat a missing trailing slash as the same stable SUUMO detail URL. Older
# persisted records use the slash form, while current index hrefs can omit it.
# Normalizing only this delimiter preserves the opaque category/ward/tenpo path
# and prevents false new/ended churn without reconstructing listing URLs.
old_listing_parse = '''        listing = parse_common_fields(source, match.group(1), absolute, ward, anchor)
        # Require a real individual URL and at least one useful attribute.
        if not any((listing.title, listing.price_yen, listing.address)):
            continue
        by_url[absolute] = listing
'''
new_listing_parse = '''        if source == "suumo":
            absolute = absolute.rstrip("/") + "/"
        listing = parse_common_fields(source, match.group(1), absolute, ward, anchor)
        # Require a real individual URL and at least one useful attribute.
        if not any((listing.title, listing.price_yen, listing.address)):
            continue
        # SUUMO pages include cross-ward recommendation cards. Never infer the
        # ward from the index page; the listing's own parsed address must match.
        if source == "suumo" and (not listing.address or ward not in listing.address):
            continue
        by_url[absolute] = listing
'''
s = replace_required(s, old_listing_parse, new_listing_parse, "SUUMO stable URL and physical ward validation")

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
s = re.sub(r'^WORKERS\s*=.*$', 'WORKERS = 8', s, flags=re.M)
s = re.sub(r'^TIMEOUT\s*=.*$', 'TIMEOUT = 15.0', s, flags=re.M)
freehold.write_text(s, encoding="utf-8")

print("Ota + SUUMO land runtime scope patch applied with stable SUUMO URLs, strict ward validation and one-run stale removal")
