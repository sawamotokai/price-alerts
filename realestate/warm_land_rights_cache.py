#!/usr/bin/env python3
"""Warm land-right classifications concurrently before strict filtering."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from enforce_freehold import (
    CACHE,
    CURRENT,
    cache_is_fresh,
    classify_record,
    fetch_classification,
    load_json,
    now_iso,
    save_json,
)

WORKERS = max(1, min(8, int(os.getenv("REAL_ESTATE_RIGHTS_WORKERS", "5"))))


def classify_url(url: str) -> tuple[str, dict[str, Any]]:
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
    return url, fetch_classification(session, url)


def main() -> None:
    current = load_json(CURRENT, {"listings": {}})
    listings = current.get("listings") or {}
    if isinstance(listings, list):
        listings = {
            str(item.get("listing_id") or item.get("id")): item for item in listings
        }

    cache_doc = load_json(CACHE, {"entries": {}})
    cache: dict[str, dict[str, Any]] = cache_doc.setdefault("entries", {})
    urls: list[str] = []
    for record in listings.values():
        status, _, _ = classify_record(record)
        url = str(record.get("url") or "")
        entry = cache.get(url)
        if (
            status == "unknown"
            and url.startswith(("http://", "https://"))
            and (not entry or not cache_is_fresh(entry))
        ):
            urls.append(url)

    urls = list(dict.fromkeys(urls))
    print(f"warming {len(urls)} land-right pages with {WORKERS} workers")
    completed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(classify_url, url) for url in urls]
        for future in as_completed(futures):
            url, result = future.result()
            cache[url] = result
            completed += 1
            if completed % 50 == 0 or completed == len(urls):
                print(f"land-right cache {completed}/{len(urls)}")

    cache_doc["updated_at"] = now_iso()
    save_json(CACHE, cache_doc)
    print(json.dumps({"requested": len(urls), "completed": completed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
