#!/usr/bin/env python3
import hashlib, json, re
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMPORT = ROOT / 'imports' / 'latest.json'
DATA = ROOT / 'data'
HISTORY = DATA / 'history'
CURRENT = DATA / 'current.json'
ENDED = DATA / 'ended.json'


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def dump_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def norm(s):
    return re.sub(r'\s+', '', str(s or '')).lower()


def listing_id(source, url):
    return hashlib.sha1(f'{source}|{url}'.encode()).hexdigest()[:20]


def property_id(item):
    parts = [norm(item.get('ward')), norm(item.get('address')),
             str(item.get('land_sqm') or ''), str(item.get('building_sqm') or ''),
             norm(item.get('built')), norm(item.get('layout'))]
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:20]


def day(s):
    return str(s)[:10] if s else date.today().isoformat()


def days_between(a, b):
    try:
        return max(0, (date.fromisoformat(b) - date.fromisoformat(a)).days)
    except Exception:
        return 0


def main():
    snap = load_json(IMPORT, None)
    if not snap:
        raise SystemExit('missing imports/latest.json')
    observed_at = snap.get('observed_at') or datetime.now().astimezone().isoformat(timespec='seconds')
    observed_day = day(observed_at)
    coverage = snap.get('coverage') or {}
    incoming = snap.get('items') or []

    previous = load_json(CURRENT, {'items': []})
    old_by_key = {(x.get('source'), x.get('url')): x for x in previous.get('items', []) if x.get('source') and x.get('url')}
    incoming_keys = set()
    out = []

    for raw in incoming:
        source = raw.get('source')
        url = raw.get('url')
        if not source or not url:
            continue
        key = (source, url)
        incoming_keys.add(key)
        old = old_by_key.get(key, {})
        first_seen = old.get('first_seen') or observed_day
        rec = dict(old)
        rec.update({k: v for k, v in raw.items() if v is not None})
        rec['id'] = old.get('id') or listing_id(source, url)
        rec['property_id'] = old.get('property_id') or property_id(rec)
        rec['first_seen'] = first_seen
        rec['last_seen'] = observed_day
        rec['listing_days'] = days_between(first_seen, observed_day) + 1
        rec['status'] = 'active'
        out.append(rec)

        price = rec.get('price_man')
        if isinstance(price, (int, float)):
            hp = HISTORY / f"{rec['id']}.json"
            hist = load_json(hp, {'id': rec['id'], 'property_id': rec['property_id'], 'series': {}})
            pts = hist.setdefault('series', {}).setdefault(source, [])
            point = {'date': observed_day, 'price_man': price}
            pts = [p for p in pts if p.get('date') != observed_day]
            pts.append(point)
            pts.sort(key=lambda p: p.get('date', ''))
            hist['series'][source] = pts
            hist['updated_at'] = observed_at
            dump_json(hp, hist)

    ended = load_json(ENDED, {'items': []})
    ended_items = ended.get('items', [])
    ended_keys = {(x.get('source'), x.get('url'), x.get('ended_on')) for x in ended_items}

    for key, old in old_by_key.items():
        if key in incoming_keys:
            continue
        source = key[0]
        if not bool(coverage.get(source, False)):
            carry = dict(old)
            carry['status'] = 'stale-source-unverified'
            out.append(carry)
            continue
        ended_key = (old.get('source'), old.get('url'), observed_day)
        if ended_key not in ended_keys:
            e = dict(old)
            e['status'] = 'listing-ended'
            e['ended_on'] = observed_day
            e['ended_observed_at'] = observed_at
            ended_items.append(e)

    out.sort(key=lambda x: (x.get('ward') or '', x.get('price_man') if isinstance(x.get('price_man'), (int,float)) else 10**18, x.get('id') or ''))
    dump_json(CURRENT, {'observed_at': observed_at, 'coverage': coverage, 'count': len(out), 'items': out})
    dump_json(ENDED, {'updated_at': observed_at, 'items': ended_items})


if __name__ == '__main__':
    main()
