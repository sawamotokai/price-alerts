#!/usr/bin/env python3
"""Run the land-right verifier in strict mode with HOME'S URL fixes."""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import requests

import enforce_freehold_v2 as verifier

# Bump the cache version so previously cached HTTP 202/405 results are retried.
verifier.CLASSIFIER_VERSION = 4
verifier.STRICT = True
verifier.UNKNOWN_DAYS = 0
verifier.TIMEOUT = max(verifier.TIMEOUT, 25.0)

_original_canonical = verifier.canonical_dashboard_url
_original_rank = verifier.record_rank


def homes_detail_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.netloc.lower() not in {"www.homes.co.jp", "homes.co.jp"}:
        return ""
    match = re.search(r"/(b-[0-9A-Za-z_-]+)/?", parsed.path)
    return f"https://www.homes.co.jp/kodate/{match.group(1)}/" if match else ""


def canonical_dashboard_url(record):
    raw = str(record.get("url") or "")
    detail = homes_detail_url(raw)
    if detail:
        return detail
    return _original_canonical(record)


def record_rank(record):
    title = str(record.get("title") or "").strip()
    generic = title in {"", "資料請求", "見学予約", "お問い合わせ", "問合せ"}
    old = _original_rank(record)
    return ((0 if generic else 1),) + tuple(old)


def fetch_one(original_url: str):
    target = homes_detail_url(original_url) or original_url
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.5",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    result = {
        "classifier_version": verifier.CLASSIFIER_VERSION,
        "status": "unknown",
        "label": None,
        "evidence": None,
        "checked_at": verifier.now_iso(),
        "http_status": None,
        "error": None,
        "final_url": target,
        "attempts": 0,
    }
    for attempt in range(1, 4):
        result["attempts"] = attempt
        try:
            response = session.get(target, timeout=verifier.TIMEOUT, allow_redirects=True)
            result["http_status"] = response.status_code
            result["final_url"] = response.url
            if response.apparent_encoding:
                response.encoding = response.apparent_encoding
            # HOME'S sometimes returns 202 while including the full public page.
            if 200 <= response.status_code < 300:
                status, label, evidence = verifier.classify_html(response.text)
                result.update(status=status, label=label, evidence=evidence, error=None)
                if status != "unknown":
                    return original_url, result
                result["error"] = f"HTTP {response.status_code}: {evidence}"
            else:
                result["error"] = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        if attempt < 3:
            time.sleep(1.5 * attempt)
    return original_url, result


verifier.canonical_dashboard_url = canonical_dashboard_url
verifier.record_rank = record_rank
verifier.fetch_one = fetch_one

if __name__ == "__main__":
    verifier.main()
