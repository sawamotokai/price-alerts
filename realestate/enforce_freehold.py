#!/usr/bin/env python3
"""Enrich land rights and publish a freehold-only dashboard.

The raw collector output remains in current.json. This pass classifies each listing's
land rights, caches detail-page results, writes audit files, and filters the
user-facing dashboard to verified freehold land / land-and-building records only.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CURRENT = DATA / "current.json"
DASHBOARD = DATA / "dashboard.json"
CACHE = DATA / "land_rights_cache.json"
EXCLUDED = DATA / "excluded_leasehold.json"
UNKNOWN = DATA / "unknown_land_rights.json"

LEASEHOLD_RE = re.compile(
    r"定期借地権|普通借地権|旧法借地権|新法借地権|借地権|"
    r"地上権|賃借権|転借権|借地期間|借地料|地代|底地"
)
FREEHOLD_RE = re.compile(r"所有権")
RIGHT_LABELS = (
    "土地の権利形態",
    "土地権利",
    "土地の権利",
    "権利形態",
    "敷地権利",
    "土地所有権",
)
RECORD_FIELDS = (
    "land_right",
    "land_rights",
    "land_ownership",
    "ownership",
    "tenure",
    "rights",
    "property_rights",
    "土地権利",
    "権利形態",
)
TEXT_FIELDS = ("title", "address", "description", "remarks", "notes", "catchcopy")
CACHE_TTL_DAYS = int(os.getenv("REAL_ESTATE_RIGHTS_CACHE_DAYS", "30"))
UNKNOWN_TTL_DAYS = int(os.getenv("REAL_ESTATE_RIGHTS_UNKNOWN_RETRY_DAYS", "2"))
REQUEST_DELAY = float(os.getenv("REAL_ESTATE_RIGHTS_DELAY", "0.18"))
TIMEOUT = float(os.getenv("REAL_ESTATE_RIGHTS_TIMEOUT", "18"))
STRICT_FREEHOLD = os.getenv("REAL_ESTATE_STRICT_FREEHOLD", "1") != "0"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def classify_text(text: str | None) -> tuple[str, str | None]:
    compact = " ".join(str(text or "").split())
    if not compact:
        return "unknown", None
    match = LEASEHOLD_RE.search(compact)
    if match:
        return "leasehold", match.group(0)
    if FREEHOLD_RE.search(compact):
        return "freehold", "所有権"
    return "unknown", None


def classify_record(record: dict[str, Any]) -> tuple[str, str | None, str]:
    explicit = " ".join(str(record.get(key) or "") for key in RECORD_FIELDS)
    status, label = classify_text(explicit)
    if status != "unknown":
        return status, label, "record-field"

    descriptive = " ".join(str(record.get(key) or "") for key in TEXT_FIELDS)
    match = LEASEHOLD_RE.search(descriptive)
    if match:
        return "leasehold", match.group(0), "record-text"
    return "unknown", None, "unclassified"


def extract_right_blocks(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    blocks: list[str] = []

    for tag in soup.find_all(["th", "dt"]):
        label = tag.get_text(" ", strip=True)
        if any(key in label for key in RIGHT_LABELS):
            parent = tag.parent
            if parent:
                blocks.append(parent.get_text(" ", strip=True))
            sibling = tag.find_next_sibling()
            if sibling:
                blocks.append(f"{label} {sibling.get_text(' ', strip=True)}")

    lines = [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]
    for index, line in enumerate(lines):
        if any(key in line for key in RIGHT_LABELS):
            blocks.append(" ".join(lines[index : index + 4]))

    return list(dict.fromkeys(block for block in blocks if block))


def classify_page(html: str) -> tuple[str, str | None, str]:
    blocks = extract_right_blocks(html)
    for block in blocks:
        status, label = classify_text(block)
        if status == "leasehold":
            return status, label, block[:240]
    for block in blocks:
        status, label = classify_text(block)
        if status == "freehold":
            return status, label, block[:240]
    return "unknown", None, blocks[0][:240] if blocks else "rights-label-not-found"


def cache_is_fresh(entry: dict[str, Any]) -> bool:
    checked = entry.get("checked_at")
    if not checked:
        return False
    try:
        at = datetime.fromisoformat(str(checked))
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    days = UNKNOWN_TTL_DAYS if entry.get("status") == "unknown" else CACHE_TTL_DAYS
    return datetime.now(timezone.utc) - at.astimezone(timezone.utc) < timedelta(days=days)


def fetch_classification(session: requests.Session, url: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unknown",
        "label": None,
        "evidence": None,
        "checked_at": now_iso(),
        "http_status": None,
        "error": None,
    }
    try:
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        result["http_status"] = response.status_code
        result["final_url"] = response.url
        if response.status_code == 200:
            status, label, evidence = classify_page(response.text)
            result.update(status=status, label=label, evidence=evidence)
        else:
            result["error"] = f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def history_change(record: dict[str, Any]) -> int:
    history = record.get("price_history") or []
    values = [
        int(point[1])
        for point in history
        if isinstance(point, list) and len(point) >= 2 and point[1]
    ]
    if not values:
        return int(record.get("price_change_yen") or 0)
    current = int(record.get("price_yen") or values[-1])
    return current - values[0]


def main() -> None:
    current = load_json(CURRENT, {"coverage": {}, "listings": {}})
    dashboard = load_json(DASHBOARD, {"listings": []})
    raw_listings = current.get("listings") or {}
    if isinstance(raw_listings, list):
        raw_listings = {
            str(item.get("listing_id") or item.get("id")): item for item in raw_listings
        }

    cache_doc = load_json(CACHE, {"entries": {}})
    cache: dict[str, dict[str, Any]] = cache_doc.setdefault("entries", {})
    excluded: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    freehold_ids: set[str] = set()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        }
    )

    fetched = 0
    total = len(raw_listings)
    for index, (listing_id, record) in enumerate(raw_listings.items(), start=1):
        status, label, evidence = classify_record(record)
        url = str(record.get("url") or "")
        if status == "unknown" and url.startswith(("http://", "https://")):
            entry = cache.get(url)
            if not entry or not cache_is_fresh(entry):
                entry = fetch_classification(session, url)
                cache[url] = entry
                fetched += 1
                if REQUEST_DELAY:
                    time.sleep(REQUEST_DELAY)
            status = str(entry.get("status") or "unknown")
            label = entry.get("label")
            evidence = str(entry.get("evidence") or entry.get("error") or "cache")

        record["land_right_status"] = status
        record["land_right"] = label
        record["land_right_checked_at"] = now_iso()

        audit = {
            "listing_id": listing_id,
            "property_id": record.get("property_id"),
            "source": record.get("source"),
            "title": record.get("title"),
            "address": record.get("address"),
            "url": record.get("url"),
            "land_right_status": status,
            "land_right": label,
            "evidence": evidence,
        }
        if status == "leasehold":
            excluded.append(audit)
        elif status == "freehold":
            freehold_ids.add(listing_id)
        else:
            unknown.append(audit)
            if not STRICT_FREEHOLD:
                freehold_ids.add(listing_id)

        if index % 50 == 0 or index == total:
            print(
                f"land-rights {index}/{total}: freehold={len(freehold_ids)} "
                f"leasehold={len(excluded)} unknown={len(unknown)} fetched={fetched}"
            )

    current["listings"] = raw_listings
    current["freehold_filter"] = {
        "strict": STRICT_FREEHOLD,
        "verified_freehold_count": sum(
            1
            for record in raw_listings.values()
            if record.get("land_right_status") == "freehold"
        ),
        "leasehold_excluded_count": len(excluded),
        "unknown_excluded_count": len(unknown) if STRICT_FREEHOLD else 0,
        "classified_at": now_iso(),
        "detail_pages_fetched": fetched,
    }
    save_json(CURRENT, current)

    dashboard_listings = dashboard.get("listings") or []
    if isinstance(dashboard_listings, dict):
        dashboard_listings = list(dashboard_listings.values())
    filtered: list[dict[str, Any]] = []
    for record in dashboard_listings:
        listing_id = str(record.get("listing_id") or record.get("id") or "")
        enriched = raw_listings.get(listing_id, record)
        if listing_id in freehold_ids:
            enriched["land_right_status"] = enriched.get("land_right_status", "freehold")
            enriched["land_right"] = enriched.get("land_right") or "所有権"
            filtered.append(enriched)

    dashboard["listings"] = filtered
    dashboard["freehold_filter"] = current["freehold_filter"]
    dashboard["generated_at"] = now_iso()
    latest = dashboard.setdefault("latest_run", {})
    metrics = latest.setdefault("metrics", {})
    metrics["active_count"] = len(filtered)
    metrics["price_changed_count"] = sum(
        1 for record in filtered if history_change(record) != 0
    )
    metrics["price_drop_count"] = sum(
        1 for record in filtered if history_change(record) < 0
    )
    observed_date = str(latest.get("observed_date") or "")
    metrics["new_count"] = sum(
        1
        for record in filtered
        if observed_date and str(record.get("first_seen") or "").startswith(observed_date)
    )
    save_json(DASHBOARD, dashboard)

    save_json(
        EXCLUDED,
        {
            "generated_at": now_iso(),
            "count": len(excluded),
            "reason": "leasehold",
            "items": excluded,
        },
    )
    save_json(
        UNKNOWN,
        {
            "generated_at": now_iso(),
            "strictly_excluded": STRICT_FREEHOLD,
            "count": len(unknown),
            "items": unknown,
        },
    )
    cache_doc["updated_at"] = now_iso()
    save_json(CACHE, cache_doc)

    print(
        json.dumps(
            {
                "raw": len(raw_listings),
                "freehold": len(freehold_ids),
                "leasehold": len(excluded),
                "unknown": len(unknown),
                "fetched": fetched,
                "strict": STRICT_FREEHOLD,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
