#!/usr/bin/env python3
"""Repair canonical listing histories from the append-only daily price ledger.

The first collector stored valid daily observations in history/YYYY-MM.jsonl,
while later normalized listing IDs could point at a different per-listing JSON
file. This script reconciles those real observations without inventing prices:

* direct listing-id matches are always accepted;
* property-id matches are accepted only when the current source/property pair
  maps to exactly one canonical listing, avoiding ambiguous broker duplicates;
* one price is kept per date and source, with the latest observation winning;
* current.json and history/<listing_id>.json are updated together.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HISTORY = DATA / "history"
CURRENT = DATA / "current.json"
HEALTH = DATA / "history_health.json"

SOURCE_MAP = {
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
TARGET_WARDS = {"品川区", "目黒区"}


def canonical_source(value: Any) -> str:
    text = str(value or "")
    return SOURCE_MAP.get(text, SOURCE_MAP.get(text.lower(), text))


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def date_only(value: Any) -> str:
    return str(value or "")[:10]


def stable_property_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("listing:"):
        return ""
    return text


def embedded_points(record: dict[str, Any], source: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for point in record.get("price_history") or []:
        point_date = ""
        price_yen: Any = None
        if isinstance(point, list) and len(point) > 1:
            point_date, price_yen = date_only(point[0]), point[1]
        elif isinstance(point, dict):
            point_date = date_only(point.get("date"))
            price_yen = point.get("price_yen")
            if not isinstance(price_yen, (int, float)) and isinstance(point.get("price_man"), (int, float)):
                price_yen = float(point["price_man"]) * 10000
        if point_date and isinstance(price_yen, (int, float)):
            result.append({
                "date": point_date,
                "price_yen": int(round(float(price_yen))),
                "source": source,
                "observed_at": point_date,
                "origin": "current",
            })
    return result


def load_legacy_ledger() -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[str, int],
]:
    by_listing: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_property: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    stats = {"ledger_files": 0, "ledger_rows": 0, "valid_ledger_rows": 0}

    for path in sorted(HISTORY.glob("*.jsonl")):
        stats["ledger_files"] += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stats["ledger_rows"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            source = canonical_source(row.get("source"))
            point_date = date_only(row.get("date") or row.get("observed_at"))
            price_yen = row.get("price_yen")
            listing_id = str(row.get("listing_id") or "").strip()
            property_id = stable_property_id(row.get("property_id"))
            if not source or not point_date or not isinstance(price_yen, (int, float)):
                continue
            point = {
                "date": point_date,
                "price_yen": int(round(float(price_yen))),
                "source": source,
                "observed_at": str(row.get("observed_at") or point_date),
                "origin": path.name,
            }
            stats["valid_ledger_rows"] += 1
            if listing_id:
                by_listing[(source, listing_id)].append(point)
            if property_id:
                by_property[(source, property_id)].append(point)

    return by_listing, by_property, stats


def load_existing_history(listing_id: str) -> list[dict[str, Any]]:
    document = load_json(HISTORY / f"{listing_id}.json", {})
    result: list[dict[str, Any]] = []
    for raw_source, series in (document.get("series") or {}).items():
        source = canonical_source(raw_source)
        for point in series or []:
            if not isinstance(point, dict):
                continue
            point_date = date_only(point.get("date"))
            price_man = point.get("price_man")
            if point_date and isinstance(price_man, (int, float)):
                result.append({
                    "date": point_date,
                    "price_yen": int(round(float(price_man) * 10000)),
                    "source": source,
                    "observed_at": point_date,
                    "origin": "history-json",
                })
    return result


def merge_points(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    # Latest observation wins for an identical date/source. Origin order makes
    # current.json authoritative when timestamps are otherwise equal.
    origin_rank = {"history-json": 1, "current": 2}
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for point in sorted(
        points,
        key=lambda item: (
            str(item.get("observed_at") or ""),
            origin_rank.get(str(item.get("origin") or ""), 0),
        ),
    ):
        source = canonical_source(point.get("source"))
        point_date = date_only(point.get("date"))
        price_yen = point.get("price_yen")
        if source and point_date and isinstance(price_yen, (int, float)):
            selected[(source, point_date)] = {
                "date": point_date,
                "price_yen": int(price_yen),
                "source": source,
            }

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in selected.values():
        by_source[point["source"]].append(point)
    for series in by_source.values():
        series.sort(key=lambda item: item["date"])
    return dict(by_source)


def main() -> None:
    current = load_json(CURRENT, None)
    if not isinstance(current, dict):
        raise SystemExit("missing or invalid realestate/data/current.json")

    raw_listings = current.get("listings") or {}
    if isinstance(raw_listings, list):
        listings = {
            str(record.get("listing_id") or record.get("id")): record
            for record in raw_listings
            if isinstance(record, dict) and (record.get("listing_id") or record.get("id"))
        }
    elif isinstance(raw_listings, dict):
        listings = {str(key): value for key, value in raw_listings.items() if isinstance(value, dict)}
    else:
        listings = {}

    by_listing, by_property, ledger_stats = load_legacy_ledger()

    current_property_members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for listing_id, record in listings.items():
        source = canonical_source(record.get("source"))
        property_id = stable_property_id(record.get("property_id"))
        if source and property_id and record.get("active") is not False:
            current_property_members[(source, property_id)].append(listing_id)

    matched_direct = matched_property = ambiguous_property = 0
    records_with_two_days = maximum_points = 0
    repaired_records = 0
    samples: list[dict[str, Any]] = []

    for listing_id, record in listings.items():
        source = canonical_source(record.get("source"))
        if not source:
            continue
        property_id = stable_property_id(record.get("property_id"))
        points: list[dict[str, Any]] = []
        points.extend(load_existing_history(listing_id))
        points.extend(embedded_points(record, source))

        direct = by_listing.get((source, listing_id), [])
        if direct:
            matched_direct += 1
            points.extend(direct)

        property_points: list[dict[str, Any]] = []
        if property_id:
            members = current_property_members.get((source, property_id), [])
            if len(members) == 1 and members[0] == listing_id:
                property_points = by_property.get((source, property_id), [])
                if property_points:
                    matched_property += 1
                    points.extend(property_points)
            elif by_property.get((source, property_id)):
                ambiguous_property += 1

        # Preserve the latest real observation already represented by the
        # active record. This is not synthetic: price_yen and last_seen were
        # emitted together by the collector.
        if isinstance(record.get("price_yen"), (int, float)) and record.get("last_seen"):
            points.append({
                "date": date_only(record.get("last_seen")),
                "price_yen": int(record["price_yen"]),
                "source": source,
                "observed_at": str(record.get("last_seen")),
                "origin": "current",
            })

        merged = merge_points(points)
        own_series = merged.get(source, [])
        if own_series:
            previous = embedded_points(record, source)
            new_embedded = [[point["date"], point["price_yen"]] for point in own_series]
            if new_embedded != [[point["date"], point["price_yen"]] for point in previous]:
                repaired_records += 1
            record["price_history"] = new_embedded
            if isinstance(record.get("price_yen"), (int, float)):
                record["price_change_yen"] = int(record["price_yen"]) - int(own_series[0]["price_yen"])

        series_document = {
            "id": listing_id,
            "property_id": record.get("property_id"),
            "series": {
                series_source: [
                    {"date": point["date"], "price_man": point["price_yen"] / 10000}
                    for point in series
                ]
                for series_source, series in sorted(merged.items())
                if series
            },
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if series_document["series"]:
            dump_json(HISTORY / f"{listing_id}.json", series_document)

        day_count = len({point["date"] for series in merged.values() for point in series})
        point_count = sum(len(series) for series in merged.values())
        maximum_points = max(maximum_points, point_count)
        if day_count >= 2:
            records_with_two_days += 1
            if len(samples) < 20 and record.get("active") is not False and record.get("ward") in TARGET_WARDS:
                samples.append({
                    "listing_id": listing_id,
                    "source": source,
                    "title": record.get("title"),
                    "url": record.get("url"),
                    "dates": sorted({point["date"] for series in merged.values() for point in series}),
                    "point_count": point_count,
                    "matched_by_property": bool(property_points),
                })

    current["listings"] = listings
    repair_meta = {
        **ledger_stats,
        "repaired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repaired_record_count": repaired_records,
        "direct_listing_matches": matched_direct,
        "unambiguous_property_matches": matched_property,
        "ambiguous_property_matches_skipped": ambiguous_property,
        "records_with_two_or_more_daily_points": records_with_two_days,
        "maximum_daily_point_count": maximum_points,
    }
    current["history_repair"] = repair_meta
    dump_json(CURRENT, current)

    previous_health = load_json(HEALTH, {})
    health = {
        **previous_health,
        "generated_at": repair_meta["repaired_at"],
        "history_repair": repair_meta,
        "records_with_two_or_more_daily_points": records_with_two_days,
        "maximum_daily_point_count": maximum_points,
        "samples": samples,
    }
    dump_json(HEALTH, health)
    print(json.dumps(repair_meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
