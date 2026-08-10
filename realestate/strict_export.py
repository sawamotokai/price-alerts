#!/usr/bin/env python3
"""Export only positively verified freehold listings from dashboard.json."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CURRENT = DATA / "current.json"
DASHBOARD = DATA / "dashboard.json"
LATEST = ROOT / "imports" / "latest.json"
REPORT = DATA / "nightly_report.json"
SOURCES = ("SUUMO", "HOME'S", "fudousan.or.jp", "ADCAST")
SOURCE_MAP = {
    "suumo": "SUUMO",
    "homes": "HOME'S",
    "home's": "HOME'S",
    "fudousan_japan": "fudousan.or.jp",
    "fudousan.or.jp": "fudousan.or.jp",
    "adcast": "ADCAST",
    "ad-cast.info": "ADCAST",
}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def complete(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, dict) or not value.get("success") or value.get("page_cap_reached"):
        return False
    wards = value.get("wards")
    if isinstance(wards, dict):
        return all(isinstance(v, dict) and v.get("success") and not v.get("page_cap_reached") for v in wards.values())
    return True


def canonical_source(value: Any) -> str:
    return SOURCE_MAP.get(str(value or "").strip().lower(), "")


def changed(record: dict[str, Any]) -> bool:
    values = []
    for point in record.get("price_history") or []:
        if isinstance(point, list) and len(point) > 1 and isinstance(point[1], (int, float)):
            values.append(int(point[1]))
        elif isinstance(point, dict) and isinstance(point.get("price_yen"), (int, float)):
            values.append(int(point["price_yen"]))
    return (len(values) > 1 and values[-1] != values[0]) or bool(record.get("price_change_yen"))


def main() -> None:
    current = load(CURRENT, {})
    dashboard = load(DASHBOARD, {})
    rows = dashboard.get("listings") or []
    if isinstance(rows, dict):
        rows = list(rows.values())

    observed_at = (
        (current.get("latest_run") or {}).get("completed_at")
        or current.get("generated_at")
        or datetime.now().astimezone().isoformat(timespec="seconds")
    )
    observed_day = str(observed_at)[:10]
    raw = current.get("coverage") or {}
    coverage = {
        "SUUMO": complete(raw.get("suumo")),
        "HOME'S": complete(raw.get("homes")),
        "fudousan.or.jp": False,
        "ADCAST": complete(raw.get("adcast")),
    }

    items = []
    counts = {name: 0 for name in SOURCES}
    price_count = new_count = changed_count = 0
    seen = set()
    for record in rows:
        if record.get("active") is False or record.get("land_right_status") != "freehold":
            continue
        source = canonical_source(record.get("source"))
        url = str(record.get("url") or "")
        if not source or not url or (source, url) in seen:
            continue
        seen.add((source, url))
        price_yen = record.get("price_yen")
        price_man = round(float(price_yen) / 10000, 4) if isinstance(price_yen, (int, float)) else None
        items.append({
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
            "land_right_status": "freehold",
            "land_right": "所有権",
        })
        counts[source] += 1
        price_count += price_man is not None
        new_count += str(record.get("first_seen") or "")[:10] == observed_day
        changed_count += changed(record)

    items.sort(key=lambda item: (
        item.get("ward") or "",
        item.get("source") or "",
        item.get("price_man") if isinstance(item.get("price_man"), (int, float)) else 10**18,
        item.get("url") or "",
    ))
    save(LATEST, {"observed_at": observed_at, "coverage": coverage, "items": items})

    listings = current.get("listings") or {}
    all_rows = listings if isinstance(listings, list) else list(listings.values())
    ended = sum(
        record.get("active") is False
        and record.get("land_right_status") == "freehold"
        and str(record.get("ended_at") or "")[:10] == observed_day
        and coverage.get(canonical_source(record.get("source")), False)
        for record in all_rows
    )
    meta = current.get("freehold_filter") or {}
    report = {
        "observed_at": observed_at,
        "coverage": coverage,
        "source_counts": counts,
        "record_count": len(items),
        "price_count": price_count,
        "price_coverage_pct": round(price_count * 100 / len(items), 2) if items else 0,
        "new_count": new_count,
        "price_changed_count": changed_count,
        "listing_ended_candidate_count": ended,
        "fudousan_japan_coverage": coverage["fudousan.or.jp"],
        "adcast_coverage": coverage["ADCAST"],
        "adcast_count": counts["ADCAST"],
        "verified_freehold_count": meta.get("verified_freehold_count", len(items)),
        "confirmed_leasehold_excluded_count": meta.get("leasehold_excluded_count", 0),
        "unknown_right_excluded_count": meta.get("unknown_excluded_count", 0),
        "out_of_scope_excluded_count": meta.get("out_of_scope_excluded_count", 0),
    }
    save(REPORT, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
