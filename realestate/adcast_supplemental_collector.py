#!/usr/bin/env python3
"""Supplement ADCAST land discovery from public recommendation indexes.

The primary collector walks /sch/list.php for each ward. Some public ADCAST
listings are exposed on /sch/recommend_near.php but are absent from the primary
index. This collector walks every discovered public recommendation page for
Shinagawa, Meguro and Ota, keeps only real detail URLs, and merges them into
current.json. ADCAST coverage remains true only when both the primary and this
supplemental traversal complete without errors/page caps.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from adcast_collector import (
    BASE_URL,
    DELAY,
    TARGETS,
    canonical_url,
    history_points,
    listing_id,
    parse_listing,
    property_id,
)

ROOT = Path(__file__).resolve().parent
CURRENT = ROOT / "data" / "current.json"
REPORT = ROOT / "data" / "adcast_report.json"
MAX_PAGES = max(1, int(os.getenv("ADCAST_SUPPLEMENTAL_MAX_PAGES", "40")))
TIMEOUT = max(5.0, float(os.getenv("ADCAST_TIMEOUT", "25")))
PAGE_RE = re.compile(r"(?:^|[?&])page_num=([0-9]+)(?:&|$)")


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def page_url(city_cd: str, page_num: int) -> str:
    params = {
        "b_area": "",
        "chikunen": "0",
        "city_cd": city_cd,
        "eki_walk": "0",
        "gazo": "",
        "kind": "1",
        "l_area": "",
        "madori": "",
        "page_num": str(page_num),
        "price": "",
        "sort": "1",
        "upddate": "",
    }
    return f"{BASE_URL}/sch/recommend_near.php?{urlencode(params)}"


def parse_public_page(html: str, ward: str) -> tuple[list[dict[str, Any]], set[int]]:
    soup = BeautifulSoup(html, "lxml")
    pages: set[int] = {1}
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "")
        match = PAGE_RE.search(href)
        if match:
            pages.add(int(match.group(1)))

    items: dict[str, dict[str, Any]] = {}
    for anchor in soup.select('a[href*="detail.php"]'):
        # parse_listing requires a real public detail URL plus a card containing
        # price/address/land area, so member-only placeholders do not become rows.
        item = parse_listing(anchor, ward)
        if item:
            items[str(item["url"])] = item
    return list(items.values()), pages


def fetch_ward(session: requests.Session, ward: str, city_cd: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    fetched: list[int] = []
    errors: list[str] = []
    pages: set[int] = {1}

    def get(page: int) -> str | None:
        try:
            response = session.get(page_url(city_cd, page), timeout=TIMEOUT, allow_redirects=True)
            if response.status_code != 200:
                errors.append(f"page {page}: HTTP {response.status_code}")
                return None
            if "物件" not in response.text:
                errors.append(f"page {page}: result marker missing")
                return None
            return response.text
        except requests.RequestException as exc:
            errors.append(f"page {page}: {type(exc).__name__}: {exc}")
            return None

    first = get(1)
    if first is None:
        return [], {"success": False, "pages_fetched": [], "pages_expected": None, "page_cap_reached": False, "parsed_count": 0, "errors": errors}
    first_items, discovered = parse_public_page(first, ward)
    fetched.append(1)
    pages |= discovered
    for item in first_items:
        items[str(item["url"])] = item

    max_page = max(pages)
    page_cap_reached = max_page > MAX_PAGES
    if page_cap_reached:
        errors.append(f"page cap reached: discovered {max_page}, cap {MAX_PAGES}")
        max_page = MAX_PAGES

    page = 2
    while page <= max_page:
        time.sleep(DELAY)
        html = get(page)
        if html is not None:
            page_items, discovered = parse_public_page(html, ward)
            fetched.append(page)
            pages |= discovered
            discovered_max = max(pages)
            if discovered_max > max_page:
                if discovered_max > MAX_PAGES:
                    page_cap_reached = True
                    errors.append(f"page cap reached: discovered {discovered_max}, cap {MAX_PAGES}")
                else:
                    max_page = discovered_max
            for item in page_items:
                items[str(item["url"])] = item
        page += 1

    success = set(fetched) == set(range(1, max_page + 1)) and not errors and not page_cap_reached
    return list(items.values()), {
        "success": success,
        "pages_fetched": fetched,
        "pages_expected": max_page,
        "page_cap_reached": page_cap_reached,
        "parsed_count": len(items),
        "errors": errors,
    }


def main() -> None:
    observed_at = now_iso()
    observed_day = observed_at[:10]
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; personal-price-monitor/1.0; +https://github.com/sawamotokai/price-alerts)",
        "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    })

    all_items: list[dict[str, Any]] = []
    statuses: dict[str, dict[str, Any]] = {}
    for index, (ward, city_cd) in enumerate(TARGETS.items()):
        if index:
            time.sleep(DELAY)
        ward_items, status = fetch_ward(session, ward, city_cd)
        all_items.extend(ward_items)
        statuses[ward] = status

    supplemental_success = all(status.get("success") is True for status in statuses.values())
    current = load(CURRENT, {"coverage": {}, "listings": {}})
    listings = current.get("listings") or {}
    if isinstance(listings, list):
        listings = {str(item.get("listing_id") or item.get("id") or listing_id(str(item.get("url") or ""))): item for item in listings if item.get("url")}

    existing_by_url = {
        str(record.get("url")): (str(lid), record)
        for lid, record in listings.items()
        if str(record.get("source") or "").lower() == "adcast" and record.get("url")
    }
    added = updated = 0
    sanno1_urls: list[str] = []
    for item in all_items:
        url = canonical_url(str(item.get("url") or ""))
        if not url:
            continue
        pair = existing_by_url.get(url)
        if pair:
            lid, record = pair
            updated += 1
        else:
            lid = listing_id(url)
            record = {
                "listing_id": lid,
                "property_id": property_id(item),
                "source": "adcast",
                "url": url,
                "first_seen": observed_at,
                "price_history": [],
            }
            listings[lid] = record
            existing_by_url[url] = (lid, record)
            added += 1

        price_yen = int(round(float(item["price_man"]) * 10000))
        record.update({
            "listing_id": record.get("listing_id") or lid,
            "property_id": record.get("property_id") or property_id(item),
            "source": "adcast",
            "url": url,
            "ward": item.get("ward"),
            "title": item.get("title"),
            "address": item.get("address"),
            "land_area_sqm": item.get("land_sqm"),
            "building_area_sqm": None,
            "layout": None,
            "built_year_month": None,
            "access": item.get("station"),
            "property_type": "land",
            "active": True,
            "ended_at": None,
            "missing_runs": 0,
            "last_seen": observed_at,
            "price_yen": price_yen,
            "price_text": f"{item['price_man']:g}万円",
        })
        record.setdefault("land_right_status", "unknown")
        record.setdefault("land_right", None)
        points = [point for point in history_points(record) if point[0] != observed_day]
        points.append([observed_day, price_yen])
        points.sort(key=lambda point: point[0])
        record["price_history"] = points
        record["price_change_yen"] = price_yen - int(points[0][1]) if points else 0

        address = str(item.get("address") or "")
        if item.get("ward") == "大田区" and ("山王１丁目" in address or "山王1丁目" in address or "山王１" in address or "山王1" in address):
            sanno1_urls.append(url)

    base = (current.get("coverage") or {}).get("adcast")
    base_success = bool(base.get("success")) if isinstance(base, dict) else bool(base)
    combined_success = base_success and supplemental_success
    current.setdefault("coverage", {})["adcast"] = {
        "source": "adcast",
        "success": combined_success,
        "primary_success": base_success,
        "supplemental_success": supplemental_success,
        "supplemental_wards": statuses,
        "supplemental_public_count": len({item.get('url') for item in all_items if item.get('url')}),
        "supplemental_sanno1_urls": sorted(set(sanno1_urls)),
        "observed_at": observed_at,
    }
    current["listings"] = listings
    save(CURRENT, current)

    report = load(REPORT, {})
    report["coverage"] = combined_success
    report["supplemental"] = {
        "success": supplemental_success,
        "record_count": len({item.get('url') for item in all_items if item.get('url')}),
        "added_count": added,
        "updated_count": updated,
        "sanno1_urls": sorted(set(sanno1_urls)),
        "wards": statuses,
        "observed_at": observed_at,
    }
    save(REPORT, report)
    print(json.dumps(report["supplemental"], ensure_ascii=False))


if __name__ == "__main__":
    main()
