#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
IMPORT = ROOT / "imports" / "latest.json"
DATA = ROOT / "data"
HISTORY = DATA / "history"
CURRENT = DATA / "current.json"
ENDED = DATA / "ended.json"
HEALTH = DATA / "history_health.json"

CANONICAL_SOURCE = {
    "suumo": "SUUMO",
    "homes": "HOME'S",
    "home's": "HOME'S",
    "fudousan_japan": "fudousan.or.jp",
    "fudousan.or.jp": "fudousan.or.jp",
    "adcast": "ADCAST",
    "ad-cast.info": "ADCAST",
    "adcast.info": "ADCAST",
    "SUUMO": "SUUMO",
    "HOME'S": "HOME'S",
    "ADCAST": "ADCAST",
}
INTERNAL_SOURCE = {
    "SUUMO": "suumo",
    "HOME'S": "homes",
    "fudousan.or.jp": "fudousan_japan",
    "ADCAST": "adcast",
}
LEASEHOLD_RE = re.compile(r"定期借地権|普通借地権|旧法借地権|新法借地権|借地権|地上権|賃借権|転借権|底地")
FREEHOLD_RE = re.compile(r"所有権")
HOMES_ID_RE = re.compile(r"/kodate/(b-[^/?#]+)", re.IGNORECASE)
TARGET_WARDS = {"品川区", "目黒区", "大田区"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def canonical_source(value: Any) -> str:
    text = str(value or "")
    return CANONICAL_SOURCE.get(text, CANONICAL_SOURCE.get(text.lower(), text))


def canonical_url(source: str, value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw

    host = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")

    if source == "HOME'S":
        match = HOMES_ID_RE.search(path)
        if match:
            return f"https://www.homes.co.jp/kodate/{match.group(1)}/"

    if source == "ADCAST":
        query = parse_qs(parsed.query, keep_blank_values=True)
        k_number = (query.get("k_number") or [""])[0]
        if k_number:
            pairs: list[tuple[str, str]] = []
            div = (query.get("div") or [""])[0]
            if div:
                pairs.append(("div", div))
            pairs.append(("k_number", k_number))
            return urlunparse(("https", "www.ad-cast.info", "/sch/detail.php", "", urlencode(pairs), ""))

    if source == "fudousan.or.jp":
        query = parse_qs(parsed.query, keep_blank_values=True)
        p_no = (query.get("p_no") or [""])[0]
        kept = urlencode({"p_no": p_no}) if p_no else ""
        return urlunparse(("https", "www.fudousan.or.jp", path.rstrip("/") or "/", "", kept, ""))

    normalized_path = path.rstrip("/") + "/" if path != "/" else "/"
    scheme = "https" if source in {"SUUMO", "HOME'S", "ADCAST", "fudousan.or.jp"} else parsed.scheme
    return urlunparse((scheme, host, normalized_path, "", "", ""))


def listing_id(source: str, url: str) -> str:
    """Hash the collector's internal source token plus canonical URL.

    Snapshots use presentation names such as ``SUUMO`` while the collector uses
    ``suumo``. Hashing the presentation name produced a second ID for the same
    URL after ingest, causing false new/ended churn on the next crawl.
    """
    canonical = canonical_source(source)
    identity_source = INTERNAL_SOURCE.get(canonical, str(source or "").strip().lower())
    return hashlib.sha1(f"{identity_source}|{url}".encode()).hexdigest()[:20]


def property_id(item: dict[str, Any]) -> str:
    parts = [
        norm(item.get("ward")),
        norm(item.get("address")),
        str(item.get("land_sqm") or item.get("land_area_sqm") or ""),
        str(item.get("building_sqm") or item.get("building_area_sqm") or ""),
        norm(item.get("built") or item.get("built_year_month")),
        norm(item.get("layout")),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def day(value: Any) -> str:
    return str(value)[:10] if value else date.today().isoformat()


def history_points(record: dict[str, Any]) -> list[list[Any]]:
    by_day: dict[str, int] = {}
    for point in record.get("price_history") or []:
        point_day = ""
        point_value: Any = None
        if isinstance(point, list) and len(point) > 1:
            point_day, point_value = str(point[0])[:10], point[1]
        elif isinstance(point, dict):
            point_day = str(point.get("date") or "")[:10]
            point_value = point.get("price_yen")
        if point_day and isinstance(point_value, (int, float)):
            by_day[point_day] = int(point_value)
    return [[point_day, value] for point_day, value in sorted(by_day.items())]


def normalized_right(raw: dict[str, Any], record: dict[str, Any]) -> tuple[str, Any]:
    status = str(raw.get("land_right_status") or "").lower()
    label = raw.get("land_right")
    if status in {"freehold", "leasehold", "unknown"}:
        return status, label
    text = " ".join(str(raw.get(key) or "") for key in ("land_right", "title", "address"))
    leasehold_match = LEASEHOLD_RE.search(text)
    if leasehold_match:
        return "leasehold", label or leasehold_match.group(0)
    if FREEHOLD_RE.search(text):
        return "freehold", label or "所有権"
    previous = str(record.get("land_right_status") or "").lower()
    if previous in {"freehold", "leasehold", "unknown"}:
        return previous, record.get("land_right")
    return "unknown", label


def parse_time(value: Any) -> str:
    return str(value or "")


def nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def record_quality(record: dict[str, Any]) -> tuple[int, str]:
    fields = (
        "title", "address", "price_yen", "land_area_sqm", "building_area_sqm",
        "layout", "built_year_month", "access", "land_right_status",
    )
    return sum(nonempty(record.get(field)) for field in fields), parse_time(record.get("last_seen"))


def merge_history_documents(target_id: str, property_value: str, source: str, old_ids: list[str], record_points: list[list[Any]]) -> tuple[dict[str, Any], int]:
    merged: dict[str, dict[str, float]] = {}
    loaded = 0
    for old_id in dict.fromkeys([target_id, *old_ids]):
        document = load_json(HISTORY / f"{old_id}.json", None)
        if not isinstance(document, dict):
            continue
        loaded += 1
        for series_source, points in (document.get("series") or {}).items():
            canonical_series_source = canonical_source(series_source)
            if canonical_series_source not in INTERNAL_SOURCE:
                canonical_series_source = str(series_source)
            bucket = merged.setdefault(canonical_series_source, {})
            for point in points or []:
                point_day = str(point.get("date") or "")[:10] if isinstance(point, dict) else ""
                point_value = point.get("price_man") if isinstance(point, dict) else None
                if point_day and isinstance(point_value, (int, float)):
                    bucket[point_day] = float(point_value)

    bucket = merged.setdefault(source, {})
    for point_day, price_yen in record_points:
        bucket[str(point_day)[:10]] = float(price_yen) / 10000

    series = {
        series_source: [
            {"date": point_day, "price_man": value}
            for point_day, value in sorted(points.items())
        ]
        for series_source, points in sorted(merged.items())
        if points
    }
    document = {
        "id": target_id,
        "property_id": property_value,
        "series": series,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return document, loaded


def merge_existing_listings(raw_listings: Any) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    if isinstance(raw_listings, list):
        source_items = [
            (str(item.get("listing_id") or item.get("id") or index), item)
            for index, item in enumerate(raw_listings)
            if isinstance(item, dict)
        ]
    elif isinstance(raw_listings, dict):
        source_items = [(str(key), value) for key, value in raw_listings.items() if isinstance(value, dict)]
    else:
        source_items = []

    groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    passthrough: dict[str, dict[str, Any]] = {}
    for old_id, record in source_items:
        source = canonical_source(record.get("source"))
        url = canonical_url(source, record.get("url"))
        if source not in INTERNAL_SOURCE or not url:
            passthrough[old_id] = record
            continue
        groups.setdefault((source, url), []).append((old_id, record))

    merged_listings: dict[str, dict[str, Any]] = dict(passthrough)
    renamed = merged_duplicates = histories_loaded = multi_day = 0

    for (source, url), members in groups.items():
        target_id = listing_id(source, url)
        members.sort(key=lambda pair: record_quality(pair[1]))
        best = dict(members[-1][1])
        old_ids = [old_id for old_id, _record in members]
        if any(old_id != target_id for old_id in old_ids):
            renamed += 1
        merged_duplicates += max(0, len(members) - 1)

        first_values = [parse_time(record.get("first_seen")) for _old_id, record in members if record.get("first_seen")]
        last_values = [parse_time(record.get("last_seen")) for _old_id, record in members if record.get("last_seen")]
        active = any(record.get("active") is not False for _old_id, record in members)

        for _old_id, record in members:
            for key, value in record.items():
                if not nonempty(best.get(key)) and nonempty(value):
                    best[key] = value

        right_statuses = {str(record.get("land_right_status") or "unknown").lower() for _old_id, record in members}
        if "leasehold" in right_statuses:
            best["land_right_status"] = "leasehold"
        elif "freehold" in right_statuses:
            best["land_right_status"] = "freehold"
            best["land_right"] = best.get("land_right") or "所有権"
        else:
            best["land_right_status"] = "unknown"

        merged_points: dict[str, int] = {}
        for _old_id, record in sorted(members, key=lambda pair: parse_time(pair[1].get("last_seen"))):
            for point_day, value in history_points(record):
                merged_points[point_day] = int(value)
            if isinstance(record.get("price_yen"), (int, float)) and record.get("last_seen"):
                merged_points.setdefault(day(record.get("last_seen")), int(record["price_yen"]))
        best["price_history"] = [[point_day, value] for point_day, value in sorted(merged_points.items())]
        if len(best["price_history"]) >= 2:
            multi_day += 1
        if best["price_history"]:
            best["price_yen"] = int(best.get("price_yen") or best["price_history"][-1][1])
            best["price_change_yen"] = int(best["price_yen"]) - int(best["price_history"][0][1])

        best["listing_id"] = target_id
        best["source"] = INTERNAL_SOURCE[source]
        best["url"] = url
        best["first_seen"] = min(first_values) if first_values else best.get("first_seen")
        best["last_seen"] = max(last_values) if last_values else best.get("last_seen")
        best["active"] = active
        if active:
            best["ended_at"] = None
            best["missing_runs"] = 0
        best["property_id"] = best.get("property_id") or property_id(best)

        history_document, loaded = merge_history_documents(
            target_id,
            str(best["property_id"]),
            source,
            old_ids,
            best["price_history"],
        )
        histories_loaded += loaded
        if history_document["series"]:
            dump_json(HISTORY / f"{target_id}.json", history_document)
        merged_listings[target_id] = best

    stats = {
        "input_listing_count": len(source_items),
        "canonical_listing_count": len(merged_listings),
        "canonicalized_group_count": renamed,
        "merged_duplicate_count": merged_duplicates,
        "history_documents_loaded": histories_loaded,
        "embedded_multi_day_count": multi_day,
    }
    return merged_listings, stats


def write_health(listings: dict[str, dict[str, Any]], observed_at: str, migration: dict[str, int]) -> None:
    samples: list[dict[str, Any]] = []
    multi_day = 0
    max_points = 0
    active_freehold = 0
    by_source: dict[str, int] = {name: 0 for name in INTERNAL_SOURCE}

    for lid, record in listings.items():
        source = canonical_source(record.get("source"))
        if source in by_source and record.get("active") is not False and record.get("land_right_status") == "freehold" and record.get("ward") in TARGET_WARDS:
            active_freehold += 1
            by_source[source] += 1
        points = history_points(record)
        max_points = max(max_points, len(points))
        if len(points) >= 2:
            multi_day += 1
            if len(samples) < 12:
                samples.append({
                    "listing_id": lid,
                    "source": source,
                    "url": record.get("url"),
                    "title": record.get("title"),
                    "point_count": len(points),
                    "dates": [point[0] for point in points],
                })

    dump_json(HEALTH, {
        "observed_at": observed_at,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "active_verified_freehold_count": active_freehold,
        "active_verified_freehold_by_source": by_source,
        "records_with_two_or_more_daily_points": multi_day,
        "maximum_daily_point_count": max_points,
        "samples": samples,
        "canonicalization": migration,
    })


def main() -> None:
    snapshot = load_json(IMPORT, {})
    observed_at = str(snapshot.get("observed_at") or datetime.now().astimezone().isoformat(timespec="seconds"))
    observed_day = day(observed_at)
    coverage = snapshot.get("coverage") or {}
    items = snapshot.get("items") or []

    current_doc = load_json(CURRENT, {"listings": {}, "coverage": {}})
    current, migration = merge_existing_listings(current_doc.get("listings") or {})

    seen_by_source: dict[str, set[str]] = {source: set() for source in INTERNAL_SOURCE}
    snapshot_ids: set[str] = set()
    for raw in items:
        source = canonical_source(raw.get("source"))
        if source not in INTERNAL_SOURCE:
            continue
        if raw.get("ward") not in TARGET_WARDS:
            continue
        url = canonical_url(source, raw.get("url"))
        if not url:
            continue
        lid = listing_id(source, url)
        snapshot_ids.add(lid)
        seen_by_source[source].add(lid)
        record = current.get(lid, {})
        previous_price = record.get("price_yen")
        price_man = raw.get("price_man")
        price_yen = int(round(float(price_man) * 10000)) if isinstance(price_man, (int, float)) else previous_price
        status, label = normalized_right(raw, record)
        points = {point[0]: int(point[1]) for point in history_points(record)}
        if price_yen is not None:
            points[observed_day] = int(price_yen)
        first_seen = record.get("first_seen") or observed_at
        property_value = record.get("property_id") or property_id(raw)
        record.update({
            "listing_id": lid,
            "property_id": property_value,
            "source": INTERNAL_SOURCE[source],
            "source_listing_id": record.get("source_listing_id") or raw.get("source_listing_id"),
            "url": url,
            "ward": raw.get("ward"),
            "title": raw.get("title"),
            "price_yen": price_yen,
            "price_text": f"{float(price_man):g}万円" if isinstance(price_man, (int, float)) else record.get("price_text"),
            "address": raw.get("address"),
            "access": raw.get("station"),
            "land_area_sqm": raw.get("land_sqm"),
            "building_area_sqm": raw.get("building_sqm"),
            "layout": raw.get("layout"),
            "built_year_month": raw.get("built"),
            "first_seen": first_seen,
            "last_seen": observed_at,
            "active": True,
            "ended_at": None,
            "missing_runs": 0,
            "land_right_status": status,
            "land_right": label,
            "price_history": [[point_day, value] for point_day, value in sorted(points.items())],
        })
        if record["price_history"] and price_yen is not None:
            record["price_change_yen"] = int(price_yen) - int(record["price_history"][0][1])
        current[lid] = record

        history_document, _loaded = merge_history_documents(
            lid,
            str(property_value),
            source,
            [lid],
            record["price_history"],
        )
        if history_document["series"]:
            dump_json(HISTORY / f"{lid}.json", history_document)

    for lid, record in current.items():
        if record.get("active") is False:
            continue
        source = canonical_source(record.get("source"))
        if source not in INTERNAL_SOURCE:
            continue
        if coverage.get(source) is not True:
            continue
        if lid in seen_by_source[source]:
            continue
        record["active"] = False
        record["ended_at"] = observed_at
        record["missing_runs"] = 0

    current_doc["listings"] = current
    current_doc["coverage"] = {
        INTERNAL_SOURCE[source]: {
            "success": bool(coverage.get(source)),
            "source": INTERNAL_SOURCE[source],
            "coverage_note": "Imported from validated nightly snapshot",
        }
        for source in INTERNAL_SOURCE
    }
    current_doc["updated_at"] = observed_at
    current_doc["observed_date"] = observed_day
    current_doc.setdefault("latest_run", {})["completed_at"] = observed_at
    current_doc["ingest_migration"] = migration
    dump_json(CURRENT, current_doc)

    ended_rows = [dict(record) for record in current.values() if record.get("active") is False]
    ended_rows.sort(key=lambda record: str(record.get("ended_at") or ""), reverse=True)
    dump_json(ENDED, {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "listings": ended_rows})
    write_health(current, observed_at, migration)
    print(json.dumps({
        "observed_at": observed_at,
        "snapshot_items": len(items),
        "snapshot_ids": len(snapshot_ids),
        "current_records": len(current),
        "active_records": sum(record.get("active") is not False for record in current.values()),
        "migration": migration,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
