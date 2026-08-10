#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
IMPORT = ROOT / "imports" / "latest.json"
DATA = ROOT / "data"
HISTORY = DATA / "history"
CURRENT = DATA / "current.json"
ENDED = DATA / "ended.json"

CANONICAL_SOURCE = {
    "suumo": "SUUMO",
    "homes": "HOME'S",
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


def listing_id(source: str, url: str) -> str:
    return hashlib.sha1(f"{source}|{url}".encode()).hexdigest()[:20]


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
    points: list[list[Any]] = []
    for point in record.get("price_history") or []:
        if isinstance(point, list) and len(point) > 1 and isinstance(point[1], (int, float)):
            points.append([str(point[0])[:10], int(point[1])])
        elif isinstance(point, dict):
            value = point.get("price_yen")
            if isinstance(value, (int, float)):
                points.append([str(point.get("date") or "")[:10], int(value)])
    return [point for point in points if point[0]]


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


def main() -> None:
    snapshot = load_json(IMPORT, None)
    if not snapshot:
        raise SystemExit("missing imports/latest.json")
    observed_at = snapshot.get("observed_at") or datetime.now().astimezone().isoformat(timespec="seconds")
    observed_day = day(observed_at)
    coverage = snapshot.get("coverage") or {}
    incoming = snapshot.get("items") or []

    current = load_json(CURRENT, {"coverage": {}, "listings": {}})
    listings = current.get("listings") or {}
    if isinstance(listings, list):
        listings = {
            str(item.get("listing_id") or item.get("id") or listing_id(canonical_source(item.get("source")), str(item.get("url") or ""))): item
            for item in listings
            if item.get("url")
        }

    by_key = {
        (canonical_source(record.get("source")), str(record.get("url"))): (lid, record)
        for lid, record in listings.items()
        if record.get("url")
    }
    incoming_keys: set[tuple[str, str]] = set()
    touched_ids: set[str] = set()

    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        source = canonical_source(raw.get("source"))
        url = str(raw.get("url") or "")
        if source not in INTERNAL_SOURCE or not url:
            continue
        key = (source, url)
        incoming_keys.add(key)
        old_pair = by_key.get(key)
        if old_pair:
            lid, record = old_pair
        else:
            lid = listing_id(source, url)
            record = {
                "listing_id": lid,
                "property_id": property_id(raw),
                "source": INTERNAL_SOURCE[source],
                "url": url,
                "first_seen": observed_at,
                "price_history": [],
            }
            listings[lid] = record
            by_key[key] = (lid, record)

        touched_ids.add(lid)
        record["listing_id"] = record.get("listing_id") or lid
        record["property_id"] = record.get("property_id") or property_id(raw)
        record["source"] = INTERNAL_SOURCE[source]
        record["url"] = url
        record["ward"] = raw.get("ward") if raw.get("ward") is not None else record.get("ward")
        record["title"] = raw.get("title") if raw.get("title") is not None else record.get("title")
        record["address"] = raw.get("address") if raw.get("address") is not None else record.get("address")
        record["land_area_sqm"] = raw.get("land_sqm") if raw.get("land_sqm") is not None else record.get("land_area_sqm")
        record["building_area_sqm"] = raw.get("building_sqm") if raw.get("building_sqm") is not None else record.get("building_area_sqm")
        record["layout"] = raw.get("layout") if raw.get("layout") is not None else record.get("layout")
        record["built_year_month"] = raw.get("built") if raw.get("built") is not None else record.get("built_year_month")
        record["access"] = raw.get("station") if raw.get("station") is not None else record.get("access")
        record["property_type"] = raw.get("property_type") if raw.get("property_type") is not None else record.get("property_type")
        right_status, right_label = normalized_right(raw, record)
        record["land_right_status"] = right_status
        record["land_right"] = right_label
        record["active"] = True
        record["ended_at"] = None
        record["missing_runs"] = 0
        record["first_seen"] = record.get("first_seen") or observed_at
        record["last_seen"] = observed_at

        price_man = raw.get("price_man")
        if isinstance(price_man, (int, float)):
            price_yen = int(round(float(price_man) * 10000))
            record["price_yen"] = price_yen
            record["price_text"] = f"{float(price_man):g}万円"
            points = [point for point in history_points(record) if point[0] != observed_day]
            points.append([observed_day, price_yen])
            points.sort(key=lambda point: point[0])
            record["price_history"] = points
            record["price_change_yen"] = price_yen - int(points[0][1]) if points else 0

            history_path = HISTORY / f"{record['listing_id']}.json"
            history = load_json(history_path, {"id": record["listing_id"], "property_id": record["property_id"], "series": {}})
            history["id"] = record["listing_id"]
            history["property_id"] = record["property_id"]
            series = history.setdefault("series", {})
            old_points = [point for point in series.get(source, []) if point.get("date") != observed_day]
            old_points.append({"date": observed_day, "price_man": float(price_man)})
            old_points.sort(key=lambda point: point.get("date", ""))
            series[source] = old_points
            history["updated_at"] = observed_at
            dump_json(history_path, history)

    ended = load_json(ENDED, {"items": []})
    ended_items = ended.get("items", [])
    ended_keys = {(item.get("source"), item.get("url"), item.get("ended_on")) for item in ended_items}
    ended_this_run = 0

    for lid, record in listings.items():
        if lid in touched_ids or record.get("active") is False:
            continue
        # A listing that is now confirmed leasehold is excluded by policy, not
        # declared ended. Unknown-right listings are still tracked.
        if str(record.get("land_right_status") or "").lower() == "leasehold":
            continue
        source = canonical_source(record.get("source"))
        if not bool(coverage.get(source, False)):
            continue
        key = (source, str(record.get("url") or ""))
        if key in incoming_keys:
            continue
        record["active"] = False
        record["ended_at"] = observed_at
        record["missing_runs"] = 0
        ended_key = (source, record.get("url"), observed_day)
        if ended_key not in ended_keys:
            ended_item = {
                "id": record.get("listing_id") or lid,
                "property_id": record.get("property_id"),
                "source": source,
                "url": record.get("url"),
                "ward": record.get("ward"),
                "title": record.get("title"),
                "price_man": (float(record.get("price_yen")) / 10000) if isinstance(record.get("price_yen"), (int, float)) else None,
                "address": record.get("address"),
                "land_sqm": record.get("land_area_sqm"),
                "building_sqm": record.get("building_area_sqm"),
                "layout": record.get("layout"),
                "built": record.get("built_year_month"),
                "station": record.get("access"),
                "property_type": record.get("property_type"),
                "land_right_status": record.get("land_right_status"),
                "land_right": record.get("land_right"),
                "status": "listing-ended",
                "ended_on": observed_day,
                "ended_observed_at": observed_at,
            }
            ended_items.append(ended_item)
            ended_keys.add(ended_key)
            ended_this_run += 1

    current["listings"] = listings
    current["ingest_snapshot"] = {
        "observed_at": observed_at,
        "coverage": coverage,
        "incoming_count": len(incoming),
        "ended_this_run": ended_this_run,
        "ingested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    dump_json(CURRENT, current)
    dump_json(ENDED, {"updated_at": observed_at, "items": ended_items})
    print(json.dumps(current["ingest_snapshot"], ensure_ascii=False))


if __name__ == "__main__":
    main()
