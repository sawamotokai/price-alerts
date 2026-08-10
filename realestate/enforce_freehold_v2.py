#!/usr/bin/env python3
"""Classify land rights and publish the non-leasehold dashboard (v3)."""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CURRENT = DATA / "current.json"
DASHBOARD = DATA / "dashboard.json"
CACHE = DATA / "land_rights_cache.json"
EXCLUDED = DATA / "excluded_leasehold.json"
UNKNOWN = DATA / "unknown_land_rights.json"
SCOPE_EXCLUDED = DATA / "excluded_out_of_scope.json"
CLASSIFIER_VERSION = 3
TARGET_WARDS = {"品川区", "目黒区"}

LEASEHOLD_RE = re.compile(
    r"定期借地権|普通借地権|旧法借地権|新法借地権|借地権|"
    r"地上権|賃借権|転借権|借地期間|借地料|地代|底地"
)
FREEHOLD_RE = re.compile(r"所有権")
RIGHT_LABELS = ("土地の権利形態", "土地権利", "土地の権利", "権利形態", "土地所有権")
RECORD_FIELDS = (
    "land_right", "land_rights", "land_ownership", "ownership", "tenure",
    "rights", "property_rights", "土地権利", "権利形態",
)
TEXT_FIELDS = ("title", "address", "description", "remarks", "notes", "catchcopy")
GENERIC_NOTE_RE = re.compile(
    r"※.*(?:権利金を含みます|建築条件付き土地価格|ものは|場合)|"
    r"敷地権利が定期借地権のもの"
)
WORKERS = max(1, min(8, int(os.getenv("REAL_ESTATE_RIGHTS_WORKERS", "5"))))
TIMEOUT = float(os.getenv("REAL_ESTATE_RIGHTS_TIMEOUT", "18"))
CACHE_DAYS = int(os.getenv("REAL_ESTATE_RIGHTS_CACHE_DAYS", "30"))
UNKNOWN_DAYS = int(os.getenv("REAL_ESTATE_RIGHTS_UNKNOWN_RETRY_DAYS", "2"))
STRICT = os.getenv("REAL_ESTATE_STRICT_FREEHOLD", "1") != "0"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def classify(text: str | None) -> tuple[str, str | None]:
    value = " ".join(str(text or "").split())
    if not value or GENERIC_NOTE_RE.search(value):
        return "unknown", None
    match = LEASEHOLD_RE.search(value)
    if match:
        return "leasehold", match.group(0)
    if FREEHOLD_RE.search(value):
        return "freehold", "所有権"
    return "unknown", None


def classify_record(record: dict[str, Any]) -> tuple[str, str | None, str]:
    status, label = classify(" ".join(str(record.get(k) or "") for k in RECORD_FIELDS))
    if status != "unknown":
        return status, label, "record-field"
    text = " ".join(str(record.get(k) or "") for k in TEXT_FIELDS)
    match = LEASEHOLD_RE.search(text)
    if match:
        return "leasehold", match.group(0), "record-text"
    return "unknown", None, "unclassified"


def blocks_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    blocks: list[str] = []
    for tag in soup.find_all(["th", "dt"]):
        label = " ".join(tag.get_text(" ", strip=True).split())
        if any(key in label for key in RIGHT_LABELS):
            row = tag.parent
            if row:
                blocks.append(" ".join(row.get_text(" ", strip=True).split()))
            sibling = tag.find_next_sibling()
            if sibling:
                blocks.append(f"{label} {' '.join(sibling.get_text(' ', strip=True).split())}")
    lines = [" ".join(x.split()) for x in soup.get_text("\n", strip=True).splitlines()]
    for i, line in enumerate(lines):
        if any(key in line for key in RIGHT_LABELS):
            blocks.append(" ".join(lines[i:i + 3]))
    return [block for block in dict.fromkeys(blocks) if block and not GENERIC_NOTE_RE.search(block)]


def classify_html(html: str) -> tuple[str, str | None, str]:
    blocks = blocks_from_html(html)
    for block in blocks:
        status, label = classify(block)
        if status == "leasehold":
            return status, label, block[:240]
    for block in blocks:
        status, label = classify(block)
        if status == "freehold":
            return status, label, block[:240]
    return "unknown", None, blocks[0][:240] if blocks else "property-right-label-not-found"


def fresh(entry: dict[str, Any]) -> bool:
    if entry.get("classifier_version") != CLASSIFIER_VERSION:
        return False
    try:
        checked = datetime.fromisoformat(str(entry.get("checked_at")))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    days = UNKNOWN_DAYS if entry.get("status") == "unknown" else CACHE_DAYS
    return datetime.now(timezone.utc) - checked.astimezone(timezone.utc) < timedelta(days=days)


def fetch_one(url: str) -> tuple[str, dict[str, Any]]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; personal-price-monitor/1.0; +https://github.com/sawamotokai/price-alerts)",
        "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    })
    result: dict[str, Any] = {
        "classifier_version": CLASSIFIER_VERSION,
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
            status, label, evidence = classify_html(response.text)
            result.update(status=status, label=label, evidence=evidence)
        else:
            result["error"] = f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return url, result


def in_scope(record: dict[str, Any]) -> bool:
    if record.get("ward") not in TARGET_WARDS:
        return False
    source = str(record.get("source") or "").lower()
    url = str(record.get("url") or "")
    if source == "suumo" and "/sc_shinagawa/" not in url and "/sc_meguro/" not in url:
        return False
    return True


def canonical_dashboard_url(record: dict[str, Any]) -> str:
    source = str(record.get("source") or "").lower()
    raw_url = str(record.get("url") or "")
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path_lower = parsed.path.lower()
    if any(part in path_lower for part in ("/inquire/", "/inquiry/", "/contact/", "/request/")):
        return ""
    if str(record.get("title") or "").strip() == "資料請求":
        return ""
    if source == "adcast":
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
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", "", ""))


def record_rank(record: dict[str, Any]) -> tuple[int, str]:
    fields = (
        "title", "price_yen", "address", "land_area_sqm", "building_area_sqm",
        "layout", "built_year_month", "access",
    )
    return (
        sum(record.get(field) not in (None, "", []) for field in fields),
        str(record.get("last_seen") or ""),
    )


def price_change(record: dict[str, Any]) -> int:
    values = [
        int(point[1])
        for point in record.get("price_history") or []
        if isinstance(point, list) and len(point) > 1 and point[1]
    ]
    if values:
        return int(record.get("price_yen") or values[-1]) - values[0]
    return int(record.get("price_change_yen") or 0)


def main() -> None:
    current = load(CURRENT, {"coverage": {}, "listings": {}})
    dashboard = load(DASHBOARD, {"listings": []})
    listings = current.get("listings") or {}
    if isinstance(listings, list):
        listings = {str(item.get("listing_id") or item.get("id")): item for item in listings}
    cache_doc = load(CACHE, {"entries": {}})
    cache: dict[str, dict[str, Any]] = cache_doc.setdefault("entries", {})

    scope_ids = {lid for lid, record in listings.items() if in_scope(record)}
    out_of_scope = [record for lid, record in listings.items() if lid not in scope_ids]
    pending: list[str] = []
    initial: dict[str, tuple[str, str | None, str]] = {}
    for lid in scope_ids:
        record = listings[lid]
        initial[lid] = classify_record(record)
        url = str(record.get("url") or "")
        entry = cache.get(url)
        if initial[lid][0] == "unknown" and url.startswith(("http://", "https://")) and (not entry or not fresh(entry)):
            pending.append(url)
    pending = list(dict.fromkeys(pending))
    print(f"checking {len(pending)} land-right pages with {WORKERS} workers")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fetch_one, url) for url in pending]
        for index, future in enumerate(as_completed(futures), start=1):
            url, result = future.result()
            cache[url] = result
            if index % 50 == 0 or index == len(futures):
                print(f"land-right pages {index}/{len(futures)}")

    included_ids: set[str] = set()
    verified_freehold_ids: set[str] = set()
    leasehold: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for lid in scope_ids:
        record = listings[lid]
        status, label, evidence = initial[lid]
        if status == "unknown":
            entry = cache.get(str(record.get("url") or ""), {})
            status = str(entry.get("status") or "unknown")
            label = entry.get("label")
            evidence = str(entry.get("evidence") or entry.get("error") or evidence)
        record["land_right_status"] = status
        record["land_right"] = label
        record["land_right_checked_at"] = now_iso()
        audit = {
            key: record.get(key)
            for key in ("listing_id", "property_id", "source", "title", "address", "url")
        }
        audit.update(land_right_status=status, land_right=label, evidence=evidence)
        if status == "freehold":
            verified_freehold_ids.add(lid)
            included_ids.add(lid)
        elif status == "leasehold":
            leasehold.append(audit)
        else:
            unknown.append(audit)
            if not STRICT:
                included_ids.add(lid)

    current["listings"] = listings
    current["freehold_filter"] = {
        "classifier_version": CLASSIFIER_VERSION,
        "strict": STRICT,
        "included_nonleasehold_count": len(included_ids),
        "verified_freehold_count": len(verified_freehold_ids),
        "leasehold_excluded_count": len(leasehold),
        "unknown_included_count": len(unknown) if not STRICT else 0,
        "unknown_excluded_count": len(unknown) if STRICT else 0,
        "out_of_scope_excluded_count": len(out_of_scope),
        "classified_at": now_iso(),
        "detail_pages_fetched": len(pending),
    }
    save(CURRENT, current)

    # Rebuild the dashboard directly from current.json. Re-filtering the old
    # dashboard silently dropped newly added sources such as ADCAST.
    by_listing: dict[tuple[str, str], dict[str, Any]] = {}
    for lid in included_ids:
        record = listings[lid]
        if record.get("active") is False:
            continue
        url = canonical_dashboard_url(record)
        if not url:
            continue
        source = str(record.get("source") or "").lower()
        key = (source, url)
        candidate = dict(record)
        candidate["url"] = url
        previous = by_listing.get(key)
        if previous is None or record_rank(candidate) > record_rank(previous):
            by_listing[key] = candidate

    filtered = sorted(
        by_listing.values(),
        key=lambda record: (
            str(record.get("ward") or ""),
            str(record.get("source") or ""),
            int(record.get("price_yen") or 10**18),
            str(record.get("url") or ""),
        ),
    )
    dashboard["coverage"] = current.get("coverage") or {}
    dashboard["listings"] = filtered
    dashboard["freehold_filter"] = current["freehold_filter"]
    dashboard["generated_at"] = now_iso()
    latest = dict(current.get("latest_run") or dashboard.get("latest_run") or {})
    metrics = dict(latest.get("metrics") or {})
    metrics["active_count"] = len(filtered)
    metrics["price_changed_count"] = sum(price_change(record) != 0 for record in filtered)
    metrics["price_drop_count"] = sum(price_change(record) < 0 for record in filtered)
    latest["metrics"] = metrics
    dashboard["latest_run"] = latest
    save(DASHBOARD, dashboard)

    generated_at = now_iso()
    save(EXCLUDED, {"generated_at": generated_at, "count": len(leasehold), "items": leasehold})
    save(UNKNOWN, {
        "generated_at": generated_at,
        "strictly_excluded": STRICT,
        "count": len(unknown),
        "items": unknown,
    })
    save(SCOPE_EXCLUDED, {"generated_at": generated_at, "count": len(out_of_scope), "items": out_of_scope})
    cache_doc["classifier_version"] = CLASSIFIER_VERSION
    cache_doc["updated_at"] = generated_at
    save(CACHE, cache_doc)
    print(json.dumps({
        "raw": len(listings),
        "dashboard": len(filtered),
        "included_nonleasehold": len(included_ids),
        "verified_freehold": len(verified_freehold_ids),
        "leasehold": len(leasehold),
        "unknown": len(unknown),
        "out_of_scope": len(out_of_scope),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
