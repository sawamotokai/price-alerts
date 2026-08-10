#!/usr/bin/env python3
"""Collect public ADCAST land listings for Shinagawa and Meguro.

The collector only reads public, non-member search-result pages. It records
real detail-page URLs and marks coverage true only when every discovered page
was fetched and the number of unique parsed listings matches the site's public
result count.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent
CURRENT = ROOT / "data" / "current.json"
REPORT = ROOT / "data" / "adcast_report.json"
BASE_URL = "https://www.ad-cast.info"
TARGETS = {"品川区": "13109", "目黒区": "13110"}
SOURCE = "adcast"
MAX_PAGES = max(1, int(os.getenv("ADCAST_MAX_PAGES", "20")))
DELAY = max(0.5, float(os.getenv("ADCAST_REQUEST_DELAY", "1.5")))
TIMEOUT = max(5.0, float(os.getenv("ADCAST_TIMEOUT", "25")))

PRICE_RE = re.compile(r"販売価格\s*([0-9,]+(?:\.[0-9]+)?)\s*万円")
ADDRESS_RE = re.compile(r"所在地\s*(東京都(?:品川区|目黒区).*?)\s*交通")
LAND_RE = re.compile(r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:m²|㎡)")
STATION_RE = re.compile(r"交通\s*[「\"]([^」\"]+)[」\"]駅?\s*徒歩\s*([0-9]+)分")
COUNT_RE = re.compile(r"([0-9,]+)\s*件の物件が見つかりました")
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


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def listing_id(url: str) -> str:
    return hashlib.sha1(f"ADCAST|{url}".encode()).hexdigest()[:20]


def property_id(item: dict[str, Any]) -> str:
    parts = [norm(item.get("ward")), norm(item.get("address")), str(item.get("land_sqm") or ""), norm(item.get("title"))]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def canonical_url(href: str) -> str:
    absolute = urljoin(BASE_URL, href)
    parsed = urlparse(absolute)
    if not parsed.path.endswith("/sch/detail.php") and "/sch/detail.php" not in parsed.path:
        return ""
    query = parse_qs(parsed.query, keep_blank_values=True)
    k_number = (query.get("k_number") or [""])[0]
    if not k_number:
        return ""
    compact: list[tuple[str, str]] = []
    if (query.get("div") or [""])[0]:
        compact.append(("div", query["div"][0]))
    compact.append(("k_number", k_number))
    return urlunparse(("https", "www.ad-cast.info", "/sch/detail.php", "", urlencode(compact), ""))


def page_url(city_cd: str, page_num: int) -> str:
    params = {
        "b_area": "",
        "chikunen": "0",
        "city_cd": city_cd,
        "eki_cd": "",
        "eki_walk": "0",
        "ensen_cd": "",
        "gazo": "",
        "kind": "1",
        "l_area": "",
        "madori": "",
        "page_num": str(page_num),
        "price": "",
        "school_cd": "",
        "sort": "29",
        "status": "",
        "upddate": "",
    }
    return f"{BASE_URL}/sch/list.php?{urlencode(params)}"


def smallest_card(anchor: Tag) -> Tag | None:
    node: Tag | None = anchor
    fallback: Tag | None = None
    for _ in range(12):
        if node is None:
            break
        text = " ".join(node.get_text(" ", strip=True).split())
        if "販売価格" in text and "所在地" in text and "土地面積" in text:
            fallback = node
            if len(PRICE_RE.findall(text)) == 1:
                return node
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None
    return fallback


def clean_title(anchor: Tag, card: Tag) -> str:
    candidates: list[str] = []
    for selector in ("h1", "h2", "h3", "h4", ".title", ".name"):
        tag = card.select_one(selector)
        if tag:
            candidates.append(" ".join(tag.get_text(" ", strip=True).split()))
    candidates.append(" ".join(anchor.get_text(" ", strip=True).split()))
    for value in candidates:
        value = re.sub(r"^(?:NEW\s*)?\[?土地\]?\s*", "", value, flags=re.IGNORECASE).strip()
        if value and "販売価格" not in value and len(value) <= 160:
            return value
    return ""


def parse_listing(anchor: Tag, ward: str) -> dict[str, Any] | None:
    href = canonical_url(str(anchor.get("href") or ""))
    if not href:
        return None
    card = smallest_card(anchor)
    if card is None:
        return None
    text = " ".join(card.get_text(" ", strip=True).split())
    price_match = PRICE_RE.search(text)
    address_match = ADDRESS_RE.search(text)
    land_match = LAND_RE.search(text)
    if not (price_match and address_match and land_match):
        return None
    address = " ".join(address_match.group(1).split())
    if ward not in address:
        return None
    station_match = STATION_RE.search(text)
    station = None
    if station_match:
        station = f"{station_match.group(1)}駅 徒歩{station_match.group(2)}分"
    title = clean_title(anchor, card)
    if not title:
        title = address.replace("東京都", "") + " 土地"
    return {
        "source": "ADCAST",
        "url": href,
        "ward": ward,
        "title": title,
        "price_man": float(price_match.group(1).replace(",", "")),
        "address": address,
        "land_sqm": float(land_match.group(1).replace(",", "")),
        "building_sqm": None,
        "layout": None,
        "built": None,
        "station": station,
        "property_type": "land",
        "land_right_status": "unknown",
        "land_right": None,
    }


def parse_page(html: str, ward: str) -> tuple[list[dict[str, Any]], int | None, set[int]]:
    soup = BeautifulSoup(html, "lxml")
    text = " ".join(soup.get_text(" ", strip=True).split())
    count_match = COUNT_RE.search(text)
    expected = int(count_match.group(1).replace(",", "")) if count_match else None
    pages: set[int] = {1}
    for tag in soup.select("a[href]"):
        href = str(tag.get("href") or "")
        match = PAGE_RE.search(href)
        if match:
            pages.add(int(match.group(1)))
    items: dict[str, dict[str, Any]] = {}
    for anchor in soup.select('a[href*="detail.php"]'):
        item = parse_listing(anchor, ward)
        if item:
            items[item["url"]] = item
    return list(items.values()), expected, pages


def fetch_ward(session: requests.Session, ward: str, city_cd: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_items: dict[str, dict[str, Any]] = {}
    expected: int | None = None
    pages: set[int] = {1}
    fetched_pages: list[int] = []
    errors: list[str] = []

    def get(page: int) -> str | None:
        url = page_url(city_cd, page)
        try:
            response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if response.status_code != 200:
                errors.append(f"page {page}: HTTP {response.status_code}")
                return None
            if "物件が見つかりました" not in response.text:
                errors.append(f"page {page}: result marker missing")
                return None
            return response.text
        except requests.RequestException as exc:
            errors.append(f"page {page}: {type(exc).__name__}: {exc}")
            return None

    first = get(1)
    if first is None:
        return [], {"success": False, "expected_count": None, "parsed_count": 0, "pages_fetched": [], "errors": errors}
    first_items, expected, discovered = parse_page(first, ward)
    fetched_pages.append(1)
    pages |= discovered
    for item in first_items:
        all_items[item["url"]] = item

    max_page = max(pages)
    if max_page > MAX_PAGES:
        errors.append(f"page cap reached: discovered {max_page}, cap {MAX_PAGES}")
        max_page = MAX_PAGES

    page = 2
    while page <= max_page:
        time.sleep(DELAY)
        html = get(page)
        if html is None:
            page += 1
            continue
        page_items, page_expected, discovered = parse_page(html, ward)
        fetched_pages.append(page)
        if expected is not None and page_expected is not None and page_expected != expected:
            errors.append(f"page {page}: expected count changed {expected}->{page_expected}")
        pages |= discovered
        if max(pages) > max_page:
            if max(pages) > MAX_PAGES:
                errors.append(f"page cap reached: discovered {max(pages)}, cap {MAX_PAGES}")
            else:
                max_page = max(pages)
        for item in page_items:
            all_items[item["url"]] = item
        page += 1

    complete_pages = set(fetched_pages) == set(range(1, max_page + 1))
    count_matches = expected is not None and len(all_items) == expected
    success = complete_pages and count_matches and not errors
    return list(all_items.values()), {
        "success": success,
        "expected_count": expected,
        "parsed_count": len(all_items),
        "pages_expected": max_page,
        "pages_fetched": fetched_pages,
        "page_cap_reached": any("page cap reached" in error for error in errors),
        "errors": errors,
    }


def history_points(record: dict[str, Any]) -> list[list[Any]]:
    points: list[list[Any]] = []
    for point in record.get("price_history") or []:
        if isinstance(point, list) and len(point) > 1 and isinstance(point[1], (int, float)):
            points.append([str(point[0])[:10], int(point[1])])
        elif isinstance(point, dict) and isinstance(point.get("price_yen"), (int, float)):
            points.append([str(point.get("date") or "")[:10], int(point["price_yen"])])
    return [point for point in points if point[0]]


def main() -> None:
    observed_at = now_iso()
    observed_day = observed_at[:10]
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; personal-price-monitor/1.0; +https://github.com/sawamotokai/price-alerts)",
        "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    })

    collected: list[dict[str, Any]] = []
    ward_status: dict[str, dict[str, Any]] = {}
    for index, (ward, city_cd) in enumerate(TARGETS.items()):
        if index:
            time.sleep(DELAY)
        items, status = fetch_ward(session, ward, city_cd)
        collected.extend(items)
        ward_status[ward] = status

    coverage = all(status.get("success") is True for status in ward_status.values())
    current = load(CURRENT, {"coverage": {}, "listings": {}})
    listings = current.get("listings") or {}
    if isinstance(listings, list):
        listings = {str(item.get("listing_id") or item.get("id") or listing_id(str(item.get("url") or ""))): item for item in listings if item.get("url")}

    existing_by_url = {
        str(record.get("url")): (lid, record)
        for lid, record in listings.items()
        if str(record.get("source") or "").lower() == SOURCE and record.get("url")
    }
    seen_urls: set[str] = set()
    new_count = 0
    changed_count = 0

    for item in collected:
        url = str(item["url"])
        seen_urls.add(url)
        pair = existing_by_url.get(url)
        if pair:
            lid, record = pair
        else:
            lid = listing_id(url)
            record = {
                "listing_id": lid,
                "property_id": property_id(item),
                "source": SOURCE,
                "url": url,
                "first_seen": observed_at,
                "price_history": [],
            }
            listings[lid] = record
            existing_by_url[url] = (lid, record)
            new_count += 1

        old_price = record.get("price_yen")
        price_yen = int(round(float(item["price_man"]) * 10000))
        if isinstance(old_price, (int, float)) and int(old_price) != price_yen:
            changed_count += 1
        record.update({
            "listing_id": record.get("listing_id") or lid,
            "property_id": record.get("property_id") or property_id(item),
            "source": SOURCE,
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

    ended_count = 0
    if coverage:
        for url, (_, record) in existing_by_url.items():
            if url in seen_urls or record.get("active") is False:
                continue
            record["active"] = False
            record["ended_at"] = observed_at
            record["missing_runs"] = 0
            ended_count += 1

    current["listings"] = listings
    raw_coverage = current.setdefault("coverage", {})
    raw_coverage[SOURCE] = {
        "success": coverage,
        "blocked": False,
        "page_cap_reached": any(status.get("page_cap_reached") for status in ward_status.values()),
        "wards": ward_status,
        "count": len(collected),
        "observed_at": observed_at,
    }
    latest_run = current.setdefault("latest_run", {})
    latest_run["completed_at"] = observed_at
    latest_run.setdefault("source_stats", {})[SOURCE] = {
        "count": len(collected),
        "new_count": new_count,
        "price_changed_count": changed_count,
        "ended_count": ended_count,
        "coverage": coverage,
    }
    save(CURRENT, current)

    report = {
        "observed_at": observed_at,
        "coverage": coverage,
        "record_count": len(collected),
        "new_count": new_count,
        "price_changed_count": changed_count,
        "listing_ended_candidate_count": ended_count,
        "wards": ward_status,
    }
    save(REPORT, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
