#!/usr/bin/env python3
"""Canonicalize outbound listing URLs before export and dashboard publication."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent
CURRENT = ROOT / "data" / "current.json"
DASHBOARD = ROOT / "data" / "dashboard.json"
LATEST = ROOT / "imports" / "latest.json"

SUUMO_RE = re.compile(
    r"/(chukoikkodate|tochi)/tokyo/sc_(shinagawa|meguro|ota)/nc_(\d+)(?:/tenpo)?/?",
    re.IGNORECASE,
)
SUUMO_ID_RE = re.compile(r"/nc_(\d+)(?:/tenpo)?/?", re.IGNORECASE)
HOMES_RE = re.compile(r"/kodate/(b-[^/?#]+)/?", re.IGNORECASE)
WARD_SCOPE = {"品川区": "shinagawa", "目黒区": "meguro", "大田区": "ota"}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "suumo":
        return "SUUMO"
    if text in {"homes", "home's"}:
        return "HOME'S"
    if text in {"adcast", "ad-cast.info", "adcast.info"}:
        return "ADCAST"
    if "fudousan" in text:
        return "fudousan.or.jp"
    return str(value or "")


def canonical_url(source: Any, raw: Any, ward: Any = None) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    name = source_name(source)
    try:
        parsed = urlparse(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if name == "SUUMO":
        match = SUUMO_RE.search(path)
        if match:
            category, scope, listing_number = match.groups()
        else:
            id_match = SUUMO_ID_RE.search(path)
            if not id_match:
                return value
            listing_number = id_match.group(1)
            scope = WARD_SCOPE.get(str(ward or ""), "")
            if not scope:
                return value
            category = "tochi" if "/tochi/" in path.lower() else "chukoikkodate"
        return f"https://suumo.jp/{category.lower()}/tokyo/sc_{scope.lower()}/nc_{listing_number}/"

    if name == "HOME'S":
        match = HOMES_RE.search(path)
        if match:
            return f"https://www.homes.co.jp/kodate/{match.group(1)}/"

    if name == "ADCAST":
        query = parse_qs(parsed.query, keep_blank_values=True)
        number = (query.get("k_number") or [""])[0]
        if number:
            pairs: list[tuple[str, str]] = []
            division = (query.get("div") or [""])[0]
            if division:
                pairs.append(("div", division))
            pairs.append(("k_number", number))
            return urlunparse(("https", "www.ad-cast.info", "/sch/detail.php", "", urlencode(pairs), ""))

    normalized = path if path == "/" else path.rstrip("/") + "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), normalized, "", parsed.query, ""))


def update_records(records: Any) -> int:
    changed = 0
    rows = records if isinstance(records, list) else list(records.values()) if isinstance(records, dict) else []
    for record in rows:
        if not isinstance(record, dict):
            continue
        previous = str(record.get("url") or "")
        normalized = canonical_url(record.get("source"), previous, record.get("ward"))
        if normalized and normalized != previous:
            record["url"] = normalized
            changed += 1
    return changed


def main() -> None:
    counts: dict[str, int] = {}
    current = load(CURRENT, None)
    if isinstance(current, dict):
        counts["current"] = update_records(current.get("listings"))
        save(CURRENT, current)
    dashboard = load(DASHBOARD, None)
    if isinstance(dashboard, dict):
        counts["dashboard"] = update_records(dashboard.get("listings"))
        save(DASHBOARD, dashboard)
    latest = load(LATEST, None)
    if isinstance(latest, dict):
        counts["latest"] = update_records(latest.get("items"))
        save(LATEST, latest)
    print(json.dumps({"canonicalized_urls": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
