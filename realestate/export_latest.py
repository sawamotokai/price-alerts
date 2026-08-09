#!/usr/bin/env python3
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CURRENT = ROOT / 'data' / 'current.json'
LATEST = ROOT / 'imports' / 'latest.json'
REPORT = ROOT / 'data' / 'nightly_report.json'

SOURCE_MAP = {
    'suumo': 'SUUMO',
    'homes': "HOME'S",
    'fudousan_japan': 'fudousan.or.jp',
    'fudousan.or.jp': 'fudousan.or.jp',
}


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def source_covered(cov):
    if not isinstance(cov, dict) or not cov.get('success'):
        return False
    wards = cov.get('wards')
    if isinstance(wards, dict) and wards:
        for wc in wards.values():
            if not isinstance(wc, dict) or not wc.get('success') or wc.get('page_cap_reached'):
                return False
    return True


def history_changed(rec):
    vals = []
    for p in rec.get('price_history') or []:
        if isinstance(p, list) and len(p) > 1 and isinstance(p[1], (int, float)):
            vals.append(float(p[1]))
        elif isinstance(p, dict):
            v = p.get('price_yen')
            if isinstance(v, (int, float)):
                vals.append(float(v))
    if len(vals) >= 2:
        return vals[-1] != vals[0]
    return bool(rec.get('price_change_yen'))


def main():
    cur = load(CURRENT, {})
    listings = cur.get('listings') or {}
    if isinstance(listings, list):
        rows = listings
    else:
        rows = list(listings.values())

    observed_at = (
        (cur.get('latest_run') or {}).get('completed_at')
        or cur.get('generated_at')
        or datetime.now().astimezone().isoformat(timespec='seconds')
    )
    observed_day = str(observed_at)[:10]
    raw_cov = cur.get('coverage') or {}

    coverage = {
        'SUUMO': source_covered(raw_cov.get('suumo')),
        "HOME'S": source_covered(raw_cov.get('homes')),
        # Direct automated scraping is intentionally not used for Fudousan Japan.
        # The existing import explicitly says full-site coverage is not guaranteed,
        # so coverage must remain false unless a future compliant feed proves completeness.
        'fudousan.or.jp': False,
    }

    items = []
    by_source = {'SUUMO': 0, "HOME'S": 0, 'fudousan.or.jp': 0}
    price_count = 0
    new_count = 0
    changed_count = 0
    ended_candidates = 0

    for rec in rows:
        source = SOURCE_MAP.get(str(rec.get('source') or '').lower())
        if not source:
            continue
        # Strictly exclude all leasehold/unknown-right records from the published snapshot.
        if rec.get('land_right_status') != 'freehold':
            continue
        if rec.get('active') is False:
            ended = str(rec.get('ended_at') or '')[:10]
            if ended == observed_day and coverage.get(source, False):
                ended_candidates += 1
            continue
        url = rec.get('url')
        if not url or '/inquire/' in str(url):
            continue
        price_yen = rec.get('price_yen')
        price_man = round(float(price_yen) / 10000, 4) if isinstance(price_yen, (int, float)) else None
        item = {
            'source': source,
            'url': url,
            'ward': rec.get('ward'),
            'title': rec.get('title'),
            'price_man': price_man,
            'address': rec.get('address'),
            'land_sqm': rec.get('land_area_sqm'),
            'building_sqm': rec.get('building_area_sqm'),
            'layout': rec.get('layout'),
            'built': rec.get('built_year_month'),
            'station': rec.get('access'),
        }
        items.append(item)
        by_source[source] += 1
        if price_man is not None:
            price_count += 1
        if str(rec.get('first_seen') or '')[:10] == observed_day:
            new_count += 1
        if history_changed(rec):
            changed_count += 1

    items.sort(key=lambda x: (x.get('ward') or '', x.get('source') or '', x.get('price_man') if isinstance(x.get('price_man'), (int, float)) else 10**18, x.get('url') or ''))
    snap = {'observed_at': observed_at, 'coverage': coverage, 'items': items}
    dump(LATEST, snap)

    total = len(items)
    freehold_meta = cur.get('freehold_filter') or {}
    report = {
        'observed_at': observed_at,
        'coverage': coverage,
        'source_counts': by_source,
        'record_count': total,
        'price_count': price_count,
        'price_coverage_pct': round(price_count * 100 / total, 2) if total else 0,
        'new_count': new_count,
        'price_changed_count': changed_count,
        'listing_ended_candidate_count': ended_candidates,
        'fudousan_japan_coverage': coverage['fudousan.or.jp'],
        'leasehold_excluded_count': freehold_meta.get('leasehold_excluded_count'),
        'unknown_right_excluded_count': freehold_meta.get('unknown_excluded_count'),
        'verified_freehold_count': freehold_meta.get('verified_freehold_count'),
    }
    dump(REPORT, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
