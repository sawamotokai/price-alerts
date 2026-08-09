#!/usr/bin/env python3
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMPORT = ROOT / 'imports' / 'latest.json'
DATA = ROOT / 'data'
HISTORY = DATA / 'history'
CURRENT = DATA / 'current.json'
ENDED = DATA / 'ended.json'

CANONICAL_SOURCE = {
    'suumo': 'SUUMO',
    'homes': "HOME'S",
    'fudousan_japan': 'fudousan.or.jp',
    'fudousan.or.jp': 'fudousan.or.jp',
    'SUUMO': 'SUUMO',
    "HOME'S": "HOME'S",
}
INTERNAL_SOURCE = {
    'SUUMO': 'suumo',
    "HOME'S": 'homes',
    'fudousan.or.jp': 'fudousan_japan',
}


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def dump_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def norm(s):
    return re.sub(r'\s+', '', str(s or '')).lower()


def canonical_source(s):
    return CANONICAL_SOURCE.get(str(s or ''), CANONICAL_SOURCE.get(str(s or '').lower(), str(s or '')))


def listing_id(source, url):
    return hashlib.sha1(f'{source}|{url}'.encode()).hexdigest()[:20]


def property_id(item):
    parts = [norm(item.get('ward')), norm(item.get('address')),
             str(item.get('land_sqm') or item.get('land_area_sqm') or ''),
             str(item.get('building_sqm') or item.get('building_area_sqm') or ''),
             norm(item.get('built') or item.get('built_year_month')),
             norm(item.get('layout'))]
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:20]


def day(s):
    return str(s)[:10] if s else date.today().isoformat()


def days_between(a, b):
    try:
        return max(0, (date.fromisoformat(day(a)) - date.fromisoformat(day(b))).days)
    except Exception:
        return 0


def history_points(rec):
    out = []
    for p in rec.get('price_history') or []:
        if isinstance(p, list) and len(p) > 1 and isinstance(p[1], (int, float)):
            out.append([str(p[0])[:10], int(p[1])])
        elif isinstance(p, dict):
            v = p.get('price_yen')
            if isinstance(v, (int, float)):
                out.append([str(p.get('date') or '')[:10], int(v)])
    return [p for p in out if p[0]]


def main():
    snap = load_json(IMPORT, None)
    if not snap:
        raise SystemExit('missing imports/latest.json')
    observed_at = snap.get('observed_at') or datetime.now().astimezone().isoformat(timespec='seconds')
    observed_day = day(observed_at)
    coverage = snap.get('coverage') or {}
    incoming = snap.get('items') or []

    current = load_json(CURRENT, {'coverage': {}, 'listings': {}})
    listings = current.get('listings') or {}
    if isinstance(listings, list):
        listings = {str(x.get('listing_id') or x.get('id') or listing_id(canonical_source(x.get('source')), x.get('url'))): x for x in listings if x.get('url')}

    by_url = {str(x.get('url')): (lid, x) for lid, x in listings.items() if x.get('url')}
    incoming_urls = set()
    touched_ids = set()

    for raw in incoming:
        source = canonical_source(raw.get('source'))
        url = raw.get('url')
        if source not in INTERNAL_SOURCE or not url:
            continue
        incoming_urls.add(str(url))
        old_pair = by_url.get(str(url))
        if old_pair:
            lid, rec = old_pair
        else:
            lid = listing_id(source, str(url))
            rec = {
                'listing_id': lid,
                'property_id': property_id(raw),
                'source': INTERNAL_SOURCE[source],
                'url': url,
                'first_seen': observed_at,
                'price_history': [],
            }
            listings[lid] = rec
            by_url[str(url)] = (lid, rec)

        touched_ids.add(lid)
        rec['listing_id'] = rec.get('listing_id') or lid
        rec['property_id'] = rec.get('property_id') or property_id(raw)
        rec['source'] = INTERNAL_SOURCE[source]
        rec['url'] = url
        rec['ward'] = raw.get('ward') if raw.get('ward') is not None else rec.get('ward')
        rec['title'] = raw.get('title') if raw.get('title') is not None else rec.get('title')
        rec['address'] = raw.get('address') if raw.get('address') is not None else rec.get('address')
        rec['land_area_sqm'] = raw.get('land_sqm') if raw.get('land_sqm') is not None else rec.get('land_area_sqm')
        rec['building_area_sqm'] = raw.get('building_sqm') if raw.get('building_sqm') is not None else rec.get('building_area_sqm')
        rec['layout'] = raw.get('layout') if raw.get('layout') is not None else rec.get('layout')
        rec['built_year_month'] = raw.get('built') if raw.get('built') is not None else rec.get('built_year_month')
        rec['access'] = raw.get('station') if raw.get('station') is not None else rec.get('access')
        rec['land_right_status'] = 'freehold'
        rec['land_right'] = rec.get('land_right') or '所有権'
        rec['active'] = True
        rec['ended_at'] = None
        rec['missing_runs'] = 0
        rec['first_seen'] = rec.get('first_seen') or observed_at
        rec['last_seen'] = observed_at

        price_man = raw.get('price_man')
        if isinstance(price_man, (int, float)):
            price_yen = int(round(float(price_man) * 10000))
            rec['price_yen'] = price_yen
            rec['price_text'] = rec.get('price_text') or f'{price_man:g}万円'
            pts = [p for p in history_points(rec) if p[0] != observed_day]
            pts.append([observed_day, price_yen])
            pts.sort(key=lambda p: p[0])
            rec['price_history'] = pts
            if pts:
                rec['price_change_yen'] = price_yen - int(pts[0][1])

            hp = HISTORY / f"{rec['listing_id']}.json"
            hist = load_json(hp, {'id': rec['listing_id'], 'property_id': rec['property_id'], 'series': {}})
            hist['id'] = rec['listing_id']
            hist['property_id'] = rec['property_id']
            series = hist.setdefault('series', {})
            old_pts = [p for p in series.get(source, []) if p.get('date') != observed_day]
            old_pts.append({'date': observed_day, 'price_man': float(price_man)})
            old_pts.sort(key=lambda p: p.get('date', ''))
            series[source] = old_pts
            hist['updated_at'] = observed_at
            dump_json(hp, hist)

    ended = load_json(ENDED, {'items': []})
    ended_items = ended.get('items', [])
    ended_keys = {(x.get('source'), x.get('url'), x.get('ended_on')) for x in ended_items}
    ended_this_run = 0

    for lid, rec in listings.items():
        if lid in touched_ids or rec.get('active') is False:
            continue
        if rec.get('land_right_status') != 'freehold':
            continue
        source = canonical_source(rec.get('source'))
        if source not in coverage or not bool(coverage.get(source, False)):
            continue
        if str(rec.get('url') or '') in incoming_urls:
            continue
        rec['active'] = False
        rec['ended_at'] = observed_at
        rec['missing_runs'] = 0
        ended_key = (source, rec.get('url'), observed_day)
        if ended_key not in ended_keys:
            e = {
                'id': rec.get('listing_id') or lid,
                'property_id': rec.get('property_id'),
                'source': source,
                'url': rec.get('url'),
                'ward': rec.get('ward'),
                'title': rec.get('title'),
                'price_man': (float(rec.get('price_yen')) / 10000) if isinstance(rec.get('price_yen'), (int, float)) else None,
                'address': rec.get('address'),
                'land_sqm': rec.get('land_area_sqm'),
                'building_sqm': rec.get('building_area_sqm'),
                'layout': rec.get('layout'),
                'built': rec.get('built_year_month'),
                'station': rec.get('access'),
                'status': 'listing-ended',
                'ended_on': observed_day,
                'ended_observed_at': observed_at,
            }
            ended_items.append(e)
            ended_keys.add(ended_key)
            ended_this_run += 1

    current['listings'] = listings
    current['ingest_snapshot'] = {
        'observed_at': observed_at,
        'coverage': coverage,
        'incoming_count': len(incoming),
        'ended_this_run': ended_this_run,
        'ingested_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    dump_json(CURRENT, current)
    dump_json(ENDED, {'updated_at': observed_at, 'items': ended_items})
    print(json.dumps(current['ingest_snapshot'], ensure_ascii=False))


if __name__ == '__main__':
    main()
