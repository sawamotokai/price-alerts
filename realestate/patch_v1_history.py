#!/usr/bin/env python3
"""Keep the v1 UI while hydrating charts from validated durable history.

Only data plumbing and price-change safety are patched. The v1 layout, its
all-property canvas, price-drop cards, desktop table, mobile cards and detail
sheet remain intact.
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

old_normalize = "function normalize(r){return{...r,id:r.listing_id||r.id,propertyId:r.property_id||r.listing_id||r.id,source:String(r.source||''),priceYen:r.price_yen==null?null:Number(r.price_yen),land:r.land_area_sqm??r.land_sqm??null,building:r.building_area_sqm??r.building_sqm??null,built:r.built_year_month??r.built??null,station:r.access??r.station??null,days:Number(r.observed_days??r.listing_days??0),firstSeen:r.first_seen??null,history:Array.isArray(r.price_history)?r.price_history:[]}}"
new_normalize = "function normalize(r){let validated=Array.isArray(r.price_history_validated)?r.price_history_validated:null;return{...r,id:r.listing_id||r.id,propertyId:r.property_id||r.listing_id||r.id,source:String(r.source||''),priceYen:r.price_yen==null?null:Number(r.price_yen),land:r.land_area_sqm??r.land_sqm??null,building:r.building_area_sqm??r.building_sqm??null,built:r.built_year_month??r.built??null,station:r.access??r.station??null,days:Number(r.observed_days??r.listing_days??0),firstSeen:r.first_seen??null,history:validated??(Array.isArray(r.price_history)?r.price_history:[]),priceChangeStatus:String(r.price_change_status||''),priceChangeValidated:Number(r.price_change_yen_validated??r.price_change_yen??0)}}"
if old_normalize in source:
    source = source.replace(old_normalize, new_normalize, 1)
elif new_normalize not in source:
    raise SystemExit("Could not locate the v1 normalize function")

old_drop = "function priceDrop(x){let h=priceHistory(x),current=x.priceYen;if(h.length){let first=h[0][1],latest=current??h.at(-1)[1],amount=first-latest;if(amount>0)return{first,current:latest,amount,pct:amount/first*100,date:h.at(-1)[0]}}let raw=Number(x.price_change_yen||0);if(raw<0&&current!=null){let first=current-raw,amount=-raw;return{first,current,amount,pct:amount/first*100,date:dateOnly(x.last_seen)}}return null}"
new_drop = "function priceDrop(x){if(String(x.priceChangeStatus||'').startsWith('quarantined'))return null;let h=priceHistory(x),current=x.priceYen;if(h.length>1){let first=h[0][1],latest=h.at(-1)[1],amount=first-latest;if(amount>0)return{first,current:latest,amount,pct:amount/first*100,date:h.at(-1)[0]}}let raw=Number(x.priceChangeValidated||0);if(raw<0&&current!=null&&x.priceChangeStatus==='confirmed'){let first=current-raw,amount=-raw;return{first,current,amount,pct:amount/first*100,date:dateOnly(x.last_seen)}}return null}"
if old_drop in source:
    source = source.replace(old_drop, new_drop, 1)
elif new_drop not in source:
    raise SystemExit("Could not locate the v1 priceDrop function")

loader_start = "(async()=>{try{let r=await fetch(DATA_URL"
start = source.find(loader_start)
if start < 0:
    loader_start = "(async()=>{try{let [r,currentResponse]=await Promise.all("
    start = source.find(loader_start)
if start < 0:
    raise SystemExit("Could not locate the v1 dashboard loader")
end = source.find("\n</script>", start)
if end < 0:
    raise SystemExit("Could not locate the end of the v1 dashboard script")

loader = r'''(async()=>{try{let [r,currentResponse]=await Promise.all([fetch(DATA_URL,{cache:'no-store'}),fetch(CURRENT_URL,{cache:'no-store'})]);if(!r.ok)throw new Error('HTTP '+r.status);let data=await r.json(),current=currentResponse.ok?await currentResponse.json():{},raw=Array.isArray(data.listings)?data.listings:Object.values(data.listings||{}),currentRaw=Array.isArray(current.listings)?current.listings:Object.values(current.listings||{});function canonicalSource(value){let v=String(value||'').toLowerCase();if(v==='suumo')return'SUUMO';if(v==='homes'||v==="home's")return"HOME'S";if(v==='adcast'||v==='ad-cast.info'||v==='adcast.info')return'ADCAST';if(v.includes('fudousan'))return'fudousan.or.jp';return v}function canonicalUrl(value,source){try{let u=new URL(String(value||''));u.hash='';let s=canonicalSource(source);if(s==='ADCAST'){let div=u.searchParams.get('div'),number=u.searchParams.get('k_number');u.search='';if(div)u.searchParams.set('div',div);if(number)u.searchParams.set('k_number',number)}else u.search='';u.pathname=(u.pathname.replace(/\/+$/,'')||'/')+'/';return u.toString()}catch(_){return String(value||'').replace(/[?#].*$/,'').replace(/\/+$/,'')+'/'} }function identity(record){return canonicalSource(record.source)+'|'+canonicalUrl(record.url,record.source)}function historyValue(record){return Array.isArray(record.price_history_validated)?record.price_history_validated:(Array.isArray(record.price_history)?record.price_history:[])}function points(value){let map=new Map();for(let point of value||[]){let date='',price=NaN;if(Array.isArray(point)){date=String(point[0]||'').slice(0,10);price=Number(point[1])}else if(point&&typeof point==='object'){date=String(point.date||'').slice(0,10);price=Number(point.price_yen??(Number(point.price_man)*10000))}if(date&&Number.isFinite(price)&&price>0)map.set(date,price)}return[...map.entries()].sort((a,b)=>a[0].localeCompare(b[0]))}let byId=new Map(),byIdentity=new Map();for(let record of currentRaw){let id=String(record.listing_id||record.id||''),history=points(historyValue(record));if(id){let previous=byId.get(id);if(!previous||history.length>points(historyValue(previous)).length)byId.set(id,record)}let key=identity(record),previous=byIdentity.get(key);if(key!=='|'&&(!previous||history.length>points(historyValue(previous)).length))byIdentity.set(key,record)}raw=raw.map(record=>{let match=byId.get(String(record.listing_id||record.id||''))||byIdentity.get(identity(record));if(!match)return record;let validated=points(historyValue(match)),fallback=points(historyValue(record)),chosen=validated.length?validated:fallback;return{...record,price_history:chosen,price_history_validated:chosen,price_change_yen_validated:match.price_change_yen_validated??0,price_change_status:match.price_change_status??record.price_change_status,price_history_anomaly_count:match.price_history_anomaly_count??0,first_seen:record.first_seen??match.first_seen,last_seen:match.last_seen??record.last_seen}});items=raw.map(normalize).filter(x=>x.id&&x.active!==false&&!String(x.url||'').includes('/inquire/')&&String(x.title||'')!=='資料請求'&&!isNonFreehold(x));populateSources();$('updated').textContent='最終更新: '+dateOnly(current.ingest_snapshot?.observed_at||data.generated_at||data.latest_run?.completed_at);$('metricChanged').textContent=items.filter(x=>x.priceChangeStatus==='confirmed'&&Number(x.priceChangeValidated)!==0).length.toLocaleString('ja-JP');render();if(items[0]&&!isMobile())show(items[0].id)}catch(e){console.error(e);$('status').classList.add('error');$('status').textContent='データの読み込みに失敗しました。'}})();'''

source = source[:start] + loader + source[end:]
PATH.write_text(source, encoding="utf-8")
print(f"patched validated v1 history loader in {PATH}")
