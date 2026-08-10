#!/usr/bin/env python3
"""Export a normalized nightly snapshot from persisted collector data.

Confirmed leaseholds are excluded. Listings whose land right is merely
unknown remain visible and are labelled as unknown; absence of evidence is not
silently treated as leasehold.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
CURRENT = ROOT / "data" / "current.json"
LATEST = ROOT / "imports" / "latest.json"
REPORT = ROOT / "data" / "nightly_report.json"
TARGET_WARDS = {"品川区", "目黒区"}

SOURCE_MAP = {
    "suumo": "SUUMO",
    "homes": "HOME'S",
    "fudousan_japan": "fudousan.or.jp",
    "fudousan.or.jp": "fudousan.or.jp",
    "adcast": "ADCAST",
    "ad-cast.info": "ADCAST",
    "adcast.info": "ADCAST",
}
SOURCES = ("SUUMO", "HOME'S", "fudousan.or.jp", "ADCAST")


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_covered(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, dict) or not value.get("success"):
        return False
    if value.get("page_cap_reached"):
        return False
    wards = value.get("wards")
    if isinstance(wards, dict) and wards:
        for ward_status in wards.values():
            if not isinstance(ward_status, dict) or not ward_status.get("success") or ward_status.get("page_cap_reached"):
                return False
    return True


def history_changed(record: dict[str, Any]) -> bool:
    values: list[float] = []
    for point in record.get("price_history") or []:
        if isinstance(point, list) and len(point) > 1 and isinstance(point[1], (int, float)):
            values.append(float(point[1]))
        elif isinstance(point, dict):
            value = point.get("price_yen")
            if isinstance(value, (int, float)):
                values.append(float(value))
    if len(values) >= 2:
        return values[-1] != values[0]
    return bool(record.get("price_change_yen"))


def normalize_url(source: str, url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path_lower = parsed.path.lower()
    if any(part in path_lower for part in ("/inquire/", "/inquiry/", "/contact/", "/request/")):
        return ""
    if source == "ADCAST":
        query = parse_qs(parsed.query, keep_blank_values=True)
        k_number = (query.get("k_number") or [""])[0]
        if "/sch/detail.php" not in path_lower or not k_number:
            return ""
        pairs: list[tuple[str, str]] = []
        div = (query.get("div") or [""])[0]
        if div:
            pairs.append(("div", div))
        pairs.append(("k_number", k_number))
        return urlunparse(("https", "www.ad-cast.info", "/sch/detail.php", "", urlencode(pairs), ""))
    # Listing identity for the other sources is path based. Tracking and UI
    # query parameters create duplicate rows, so remove them.
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", "", ""))


def completeness(record: dict[str, Any]) -> tuple[int, str]:
    fields = ("title", "price_yen", "address", "land_area_sqm", "building_area_sqm", "layout", "built_year_month", "access")
    return sum(record.get(field) not in (None, "", []) for field in fields), str(record.get("last_seen") or "")


def main() -> None:
    current = load(CURRENT, {})
    listings = current.get("listings") or {}
    rows = listings if isinstance(listings, list) else list(listings.values())

    observed_at = (
        (current.get("latest_run") or {}).get("completed_at")
        or current.get("generated_at")
        or datetime.now().astimezone().isoformat(timespec="seconds")
    )
    observed_day = str(observed_at)[:10]
    raw_coverage = current.get("coverage") or {}
    coverage = {
        "SUUMO": source_covered(raw_coverage.get("suumo")),
        "HOME'S": source_covered(raw_coverage.get("homes")),
        # Direct automated scraping is intentionally not used for Fudousan Japan.
        "fudousan.or.jp": False,
        "ADCAST": source_covered(raw_coverage.get("adcast")),
    }

    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    ended_candidates = 0
    confirmed_leasehold_excluded = 0
    invalid_url_excluded = 0
    out_of_scope_excluded = 0

    for record in rows:
        source = SOURCE_MAP.get(str(record.get("source") or "").lower())
        if not source:
            continue
        if record.get("ward") not in TARGET_WARDS:
            out_of_scope_excluded += 1
            continue
        if str(record.get("land_right_status") or "").lower() == "leasehold":
            confirmed_leasehold_excluded += 1
            continue
        url = normalize_url(source, str(record.get("url") or ""))
        if not url:
            invalid_url_excluded += 1
            continue
        if record.get("active") is False:
            ended = str(record.get("ended_at") or "")[:10]
            if ended == observed_day and coverage.get(source, False):
                ended_candidates += 1
            continue
        key = (source, url)
        previous = candidates.get(key)
        if previous is None or completeness(record) > completeness(previous):
            copy = dict(record)
            copy["url"] = url
            candidates[key] = copy

    items: list[dict[str, Any]] = []
    by_source = {source: 0 for source in SOURCES}
    price_count = 0
    new_count = 0
    changed_count = 0
    unknown_right_count = 0

    for (source, url), record in candidates.items():
        price_yen = record.get("price_yen")
        price_man = round(float(price_yen) / 10000, 4) if isinstance(price_yen, (int, float)) else None
        right_status = str(record.get("land_right_status") or "unknown").lower()
        if right_status not in {"freehold", "unknown"}:
            right_status = "unknown"
        item = {
            "source": source,
            "url": url,
            "ward": record.get("ward"),
            "title": record.get("title"),
            "price_man": price_man,
            "address": record.get("address"),
            "land_sqm": record.get("land_area_sqm"),
            "building_sqm": record.get("building_area_sqm"),
            "layout": record.get("layout"),
            "built": record.get("built_year_month"),
            "station": record.get("access"),
            "property_type": record.get("property_type"),
            "land_right_status": right_status,
            "land_right": record.get("land_right"),
        }
        items.append(item)
        by_source[source] += 1
        if price_man is not None:
            price_count += 1
        if str(record.get("first_seen") or "")[:10] == observed_day:
            new_count += 1
        if history_changed(record):
            changed_count += 1
        if right_status == "unknown":
            unknown_right_count += 1

    items.sort(key=lambda item: (
        item.get("ward") or "",
        item.get("source") or "",
        item.get("price_man") if isinstance(item.get("price_man"), (int, float)) else 10**18,
        item.get("url") or "",
    ))
    snapshot = {"observed_at": observed_at, "coverage": coverage, "items": items}
    dump(LATEST, snapshot)

    total = len(items)
    report = {
        "observed_at": observed_at,
        "coverage": coverage,
        "source_counts": by_source,
        "record_count": total,
        "price_count": price_count,
        "price_coverage_pct": round(price_count * 100 / total, 2) if total else 0,
        "new_count": new_count,
        "price_changed_count": changed_count,
        "listing_ended_candidate_count": ended_candidates,
        "fudousan_japan_coverage": coverage["fudousan.or.jp"],
        "adcast_coverage": coverage["ADCAST"],
        "adcast_count": by_source["ADCAST"],
        "confirmed_leasehold_excluded_count": confirmed_leasehold_excluded,
        "unknown_right_included_count": unknown_right_count,
        "invalid_or_non_listing_url_excluded_count": invalid_url_excluded,
        "out_of_scope_excluded_count": out_of_scope_excluded,
    }
    dump(REPORT, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
