#!/usr/bin/env python3
"""Keep the v1 dashboard UI and hydrate its charts from repaired current.json history.

This intentionally changes only the data-loading path. The v1 layout, the all-property
canvas, price-drop cards, desktop table, mobile cards and detail sheet remain intact.
"""
from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
DASHBOARD_URL = "https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data/dashboard.json"
CURRENT_URL = "https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data/current.json"

source = PATH.read_text(encoding="utf-8")

required_markers = (
    'id="marketCanvas"',
    '全物件の掲載価格推移',
    "function drawMarketChart(scope)",
    "function drawDetail(h)",
)
missing = [marker for marker in required_markers if marker not in source]
if missing:
    raise SystemExit(f"Refusing to patch a non-v1 dashboard; missing markers: {missing}")

old_const = f"const DATA_URL='{DASHBOARD_URL}';const PAGE_SIZE=50;"
new_const = (
    f"const DATA_URL='{DASHBOARD_URL}';"
    f"const CURRENT_URL='{CURRENT_URL}';"
    "const PAGE_SIZE=50;"
)
if old_const in source:
    source = source.replace(old_const, new_const, 1)
elif new_const not in source:
    raise SystemExit("Could not locate the v1 DATA_URL declaration")

loader_start = "(async()=>{try{let r=await fetch(DATA_URL"
start = source.find(loader_start)
if start < 0:
    # Idempotency: an already-patched loader starts with Promise.all.
    loader_start = "(async()=>{try{let [r,currentResponse]=await Promise.all("
    start = source.find(loader_start)
if start < 0:
    raise SystemExit("Could not locate the v1 dashboard loader")
end = source.find("\n</script>", start)
if end < 0:
    raise SystemExit("Could not locate the end of the v1 dashboard script")

loader = r'''(async()=>{try{let [r,currentResponse]=await Promise.all([fetch(DATA_URL,{cache:'no-store'}),fetch(CURRENT_URL,{cache:'no-store'})]);if(!r.ok)throw new Error('HTTP '+r.status);let data=await r.json(),current=currentResponse.ok?await currentResponse.json():{},raw=Array.isArray(data.listings)?data.listings:Object.values(data.listings||{}),currentRaw=Array.isArray(current.listings)?current.listings:Object.values(current.listings||{});function canonicalSource(value){let v=String(value||'').toLowerCase();if(v==='suumo')return'SUUMO';if(v==='homes'||v==="home's")return"HOME'S";if(v==='adcast'||v==='ad-cast.info'||v==='adcast.info')return'ADCAST';if(v.includes('fudousan'))return'fudousan.or.jp';return v}function canonicalUrl(value,source){try{let u=new URL(String(value||''));u.hash='';let s=canonicalSource(source);if(s==='ADCAST'){let div=u.searchParams.get('div'),number=u.searchParams.get('k_number');u.search='';if(div)u.searchParams.set('div',div);if(number)u.searchParams.set('k_number',number)}else u.search='';u.pathname=(u.pathname.replace(/\/+$/,'')||'/')+'/';return u.toString()}catch(_){return String(value||'').replace(/[?#].*$/,'').replace(/\/+$/,'')+'/'} }function identity(record){return canonicalSource(record.source)+'|'+canonicalUrl(record.url,record.source)}function points(value){let map=new Map();for(let point of value||[]){let date='',price=NaN;if(Array.isArray(point)){date=String(point[0]||'').slice(0,10);price=Number(point[1])}else if(point&&typeof point==='object'){date=String(point.date||'').slice(0,10);price=Number(point.price_yen??(Number(point.price_man)*10000))}if(date&&Number.isFinite(price)&&price>0)map.set(date,price)}return[...map.entries()].sort((a,b)=>a[0].localeCompare(b[0]))}let byId=new Map(),byIdentity=new Map();for(let record of currentRaw){let id=String(record.listing_id||record.id||'');if(id){let previous=byId.get(id);if(!previous||points(record.price_history).length>points(previous.price_history).length)byId.set(id,record)}let key=identity(record),previous=byIdentity.get(key);if(key!=='|'&&(!previous||points(record.price_history).length>points(previous.price_history).length))byIdentity.set(key,record)}raw=raw.map(record=>{let match=byId.get(String(record.listing_id||record.id||''))||byIdentity.get(identity(record));if(!match)return record;let merged=new Map(points(record.price_history));for(let [date,price] of points(match.price_history))merged.set(date,price);return{...record,price_history:[...merged.entries()].sort((a,b)=>a[0].localeCompare(b[0])),price_change_yen:match.price_change_yen??record.price_change_yen,first_seen:record.first_seen??match.first_seen,last_seen:match.last_seen??record.last_seen}});items=raw.map(normalize).filter(x=>x.id&&x.active!==false&&!String(x.url||'').includes('/inquire/')&&String(x.title||'')!=='資料請求'&&!isNonFreehold(x));populateSources();$('updated').textContent='最終更新: '+dateOnly(current.ingest_snapshot?.observed_at||data.generated_at||data.latest_run?.completed_at);$('metricChanged').textContent=items.filter(x=>{let h=priceHistory(x);return h.length>1&&h[0][1]!==h.at(-1)[1]}).length.toLocaleString('ja-JP');render();if(items[0]&&!isMobile())show(items[0].id)}catch(e){console.error(e);$('status').classList.add('error');$('status').textContent='データの読み込みに失敗しました。'}})();'''

source = source[:start] + loader + source[end:]
PATH.write_text(source, encoding="utf-8")
print(f"patched v1 history loader in {PATH}")
