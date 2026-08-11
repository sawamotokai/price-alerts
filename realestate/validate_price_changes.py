#!/usr/bin/env python3
"""Build a conservative, validated price history for dashboard decisions.

Raw observations remain untouched in ``price_history`` and the append-only ledger.
The dashboard-facing ``price_history_validated`` excludes isolated price regimes
that imply an extreme change without enough observations on both sides.

Policy:
* changes up to 35% are accepted from one daily observation per side;
* changes above 35% are accepted only when both adjacent price regimes contain
  at least two daily observations;
* an isolated middle spike is removed before regime validation;
* the latest/current price is always retained, but an unconfirmed extreme
  transition is not labelled as a price reduction;
* every excluded observation is written to an audit JSON, never silently lost.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CURRENT = DATA / "current.json"
DASHBOARD = DATA / "dashboard.json"
ANOMALIES = DATA / "price_history_anomalies.json"

MAX_UNCONFIRMED_CHANGE_PCT = max(
    0.10,
    min(0.90, float(os.getenv("REAL_ESTATE_MAX_UNCONFIRMED_PRICE_CHANGE_PCT", "0.35"))),
)
MIN_REGIME_OBSERVATIONS = max(
    2,
    int(os.getenv("REAL_ESTATE_MIN_PRICE_REGIME_OBSERVATIONS", "2")),
)
NEIGHBOUR_SIMILARITY_PCT = max(
    0.01,
    min(0.30, float(os.getenv("REAL_ESTATE_PRICE_NEIGHBOUR_SIMILARITY_PCT", "0.12"))),
)

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


def canonical_source(value: Any) -> str:
    text = str(value or "")
    return SOURCE_MAP.get(text, SOURCE_MAP.get(text.lower(), text))


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
    path = (parsed.path or "/").replace("//", "/")
    if source == "ADCAST":
        query = parse_qs(parsed.query, keep_blank_values=True)
        k_number = (query.get("k_number") or [""])[0]
        pairs: list[tuple[str, str]] = []
        div = (query.get("div") or [""])[0]
        if div:
            pairs.append(("div", div))
        if k_number:
            pairs.append(("k_number", k_number))
        return urlunparse(("https", "www.ad-cast.info", "/sch/detail.php", "", urlencode(pairs), ""))

    normalized_path = path.rstrip("/") + "/" if path != "/" else "/"
    return urlunparse(("https", host, normalized_path, "", "", ""))


def relative_change(left: int, right: int) -> float:
    if left <= 0 or right <= 0:
        return 0.0
    return abs(right - left) / float(left)


def extract_points(record: dict[str, Any]) -> list[dict[str, Any]]:
    by_day: dict[str, int] = {}
    for point in record.get("price_history") or []:
        point_day = ""
        price_yen: Any = None
        if isinstance(point, list) and len(point) > 1:
            point_day, price_yen = date_only(point[0]), point[1]
        elif isinstance(point, dict):
            point_day = date_only(point.get("date"))
            price_yen = point.get("price_yen")
            if not isinstance(price_yen, (int, float)) and isinstance(point.get("price_man"), (int, float)):
                price_yen = float(point["price_man"]) * 10000
        if point_day and isinstance(price_yen, (int, float)) and float(price_yen) > 0:
            by_day[point_day] = int(round(float(price_yen)))

    current_price = record.get("price_yen")
    current_day = date_only(record.get("last_seen"))
    if current_day and isinstance(current_price, (int, float)) and float(current_price) > 0:
        by_day[current_day] = int(round(float(current_price)))

    return [
        {"date": point_day, "price_yen": price_yen}
        for point_day, price_yen in sorted(by_day.items())
    ]


def price_runs(points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    runs: list[list[dict[str, Any]]] = []
    for point in points:
        if runs and int(runs[-1][-1]["price_yen"]) == int(point["price_yen"]):
            runs[-1].append(point)
        else:
            runs.append([point])
    return runs


def remove_isolated_middle_spikes(
    points: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned = list(points)
    removed: list[dict[str, Any]] = []
    changed = True
    while changed:
        changed = False
        runs = price_runs(cleaned)
        if len(runs) < 3:
            break
        offset = 0
        for index in range(1, len(runs) - 1):
            previous, current, following = runs[index - 1], runs[index], runs[index + 1]
            current_count = len(current)
            previous_price = int(previous[-1]["price_yen"])
            current_price = int(current[-1]["price_yen"])
            following_price = int(following[-1]["price_yen"])
            neighbours_similar = relative_change(previous_price, following_price) <= NEIGHBOUR_SIMILARITY_PCT
            isolated_from_previous = relative_change(previous_price, current_price) > MAX_UNCONFIRMED_CHANGE_PCT
            isolated_from_following = relative_change(current_price, following_price) > MAX_UNCONFIRMED_CHANGE_PCT
            if current_count == 1 and neighbours_similar and isolated_from_previous and isolated_from_following:
                target = current[0]
                target_index = offset + len(previous)
                removed.append({
                    **target,
                    "reason": "isolated-middle-price-spike",
                    "previous_price_yen": previous_price,
                    "next_price_yen": following_price,
                })
                del cleaned[target_index]
                changed = True
                break
            offset += len(previous)
    return cleaned, removed


def validate_points(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if len(points) <= 1:
        return points, [], "insufficient-history"

    cleaned, anomalies = remove_isolated_middle_spikes(points)
    if len(cleaned) <= 1:
        return cleaned, anomalies, "quarantined-unconfirmed-large-change"

    # Build contiguous regimes separated only by an extreme adjacent change.
    regimes: list[list[dict[str, Any]]] = [[cleaned[0]]]
    for point in cleaned[1:]:
        previous = regimes[-1][-1]
        if relative_change(int(previous["price_yen"]), int(point["price_yen"])) > MAX_UNCONFIRMED_CHANGE_PCT:
            regimes.append([point])
        else:
            regimes[-1].append(point)

    # Starting from the current/latest regime, include older regimes only when
    # both sides of the extreme boundary have enough independent daily points.
    first_valid_regime = len(regimes) - 1
    for boundary in range(len(regimes) - 2, -1, -1):
        older = regimes[boundary]
        newer = regimes[boundary + 1]
        if len(older) >= MIN_REGIME_OBSERVATIONS and len(newer) >= MIN_REGIME_OBSERVATIONS:
            first_valid_regime = boundary
            continue
        break

    validated = [point for regime in regimes[first_valid_regime:] for point in regime]
    excluded = [point for regime in regimes[:first_valid_regime] for point in regime]
    if excluded:
        boundary_old = int(excluded[-1]["price_yen"])
        boundary_new = int(validated[0]["price_yen"])
        for point in excluded:
            anomalies.append({
                **point,
                "reason": "unconfirmed-extreme-price-regime",
                "boundary_old_price_yen": boundary_old,
                "boundary_new_price_yen": boundary_new,
                "boundary_change_pct": round(relative_change(boundary_old, boundary_new) * 100, 2),
            })
        return validated, anomalies, "quarantined-unconfirmed-large-change"

    if anomalies:
        return validated, anomalies, "quarantined-isolated-spike"
    if len(validated) <= 1:
        return validated, [], "insufficient-history"
    if int(validated[0]["price_yen"]) == int(validated[-1]["price_yen"]):
        return validated, [], "unchanged"
    return validated, [], "confirmed"


def apply_validation(record: dict[str, Any]) -> dict[str, Any] | None:
    raw_points = extract_points(record)
    validated, anomalies, status = validate_points(raw_points)
    record["price_history_validated"] = [
        [point["date"], int(point["price_yen"])] for point in validated
    ]
    record["price_change_status"] = status
    record["price_history_anomaly_count"] = len(anomalies)
    record["price_history_validation"] = {
        "validated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "max_unconfirmed_change_pct": MAX_UNCONFIRMED_CHANGE_PCT,
        "min_regime_observations": MIN_REGIME_OBSERVATIONS,
        "raw_point_count": len(raw_points),
        "validated_point_count": len(validated),
        "anomaly_count": len(anomalies),
    }
    if len(validated) >= 2:
        delta = int(validated[-1]["price_yen"]) - int(validated[0]["price_yen"])
    else:
        delta = 0
    record["price_change_yen_validated"] = delta

    if not anomalies:
        return None
    return {
        "listing_id": record.get("listing_id") or record.get("id"),
        "property_id": record.get("property_id"),
        "source": canonical_source(record.get("source")),
        "url": record.get("url"),
        "ward": record.get("ward"),
        "title": record.get("title"),
        "address": record.get("address"),
        "current_price_yen": record.get("price_yen"),
        "status": status,
        "raw_points": raw_points,
        "validated_points": validated,
        "excluded_points": anomalies,
    }


def listing_map(raw: Any) -> tuple[dict[str, dict[str, Any]], bool]:
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}, False
    if isinstance(raw, list):
        return {
            str(record.get("listing_id") or record.get("id") or index): record
            for index, record in enumerate(raw)
            if isinstance(record, dict)
        }, True
    return {}, False


def main() -> None:
    current = load_json(CURRENT, None)
    if not isinstance(current, dict):
        raise SystemExit("missing or invalid realestate/data/current.json")

    listings, was_list = listing_map(current.get("listings") or {})
    anomalies: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}

    for listing_id, record in listings.items():
        record["listing_id"] = record.get("listing_id") or listing_id
        anomaly = apply_validation(record)
        if anomaly:
            anomalies.append(anomaly)
        by_id[str(record["listing_id"])] = record
        source = canonical_source(record.get("source"))
        url = canonical_url(source, record.get("url"))
        if source and url:
            by_identity[(source, url)] = record

    current["listings"] = list(listings.values()) if was_list else listings
    current["price_history_validation"] = {
        "validated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "max_unconfirmed_change_pct": MAX_UNCONFIRMED_CHANGE_PCT,
        "min_regime_observations": MIN_REGIME_OBSERVATIONS,
        "records_checked": len(listings),
        "records_with_quarantined_points": len(anomalies),
        "quarantined_point_count": sum(len(item["excluded_points"]) for item in anomalies),
    }
    dump_json(CURRENT, current)

    dashboard = load_json(DASHBOARD, {})
    dashboard_rows = dashboard.get("listings") or []
    rows = dashboard_rows if isinstance(dashboard_rows, list) else list(dashboard_rows.values())
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = canonical_source(row.get("source"))
        match = by_id.get(str(row.get("listing_id") or row.get("id") or ""))
        if not match:
            match = by_identity.get((source, canonical_url(source, row.get("url"))))
        if not match:
            continue
        for key in (
            "price_history_validated",
            "price_change_yen_validated",
            "price_change_status",
            "price_history_anomaly_count",
            "price_history_validation",
        ):
            row[key] = match.get(key)

    dashboard["listings"] = rows if isinstance(dashboard_rows, list) else {
        str(row.get("listing_id") or row.get("id") or index): row
        for index, row in enumerate(rows)
    }
    latest = dashboard.setdefault("latest_run", {})
    metrics = latest.setdefault("metrics", {})
    visible = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("active") is not False
        and row.get("land_right_status") == "freehold"
    ]
    metrics["price_changed_count"] = sum(
        int(row.get("price_change_yen_validated") or 0) != 0
        and row.get("price_change_status") == "confirmed"
        for row in visible
    )
    metrics["price_drop_count"] = sum(
        int(row.get("price_change_yen_validated") or 0) < 0
        and row.get("price_change_status") == "confirmed"
        for row in visible
    )
    dashboard["price_history_validation"] = current["price_history_validation"]
    dump_json(DASHBOARD, dashboard)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy": {
            "max_unconfirmed_change_pct": MAX_UNCONFIRMED_CHANGE_PCT,
            "min_regime_observations": MIN_REGIME_OBSERVATIONS,
            "neighbour_similarity_pct": NEIGHBOUR_SIMILARITY_PCT,
        },
        "record_count": len(listings),
        "records_with_quarantined_points": len(anomalies),
        "quarantined_point_count": sum(len(item["excluded_points"]) for item in anomalies),
        "items": sorted(
            anomalies,
            key=lambda item: max(
                [float(point.get("boundary_change_pct") or 0) for point in item["excluded_points"]] or [0]
            ),
            reverse=True,
        ),
    }
    dump_json(ANOMALIES, report)
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
