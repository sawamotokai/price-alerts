#!/usr/bin/env python3
"""Idempotently add graph price-range controls and click-to-open details."""
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
s = PATH.read_text(encoding="utf-8")
original = s


def replace_once(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        raise RuntimeError(f"patch marker not found: {label}")
    s = s.replace(old, new, 1)


if "marketMinPrice" not in s:
    css_marker = ".market-controls{display:flex;gap:8px;flex-wrap:wrap}"
    css_new = css_marker + (
        ".market-price-range{display:flex;align-items:center;gap:6px;flex-wrap:wrap}"
        ".market-price-range label{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);white-space:nowrap}"
        ".market-price-input{width:118px}"
        ".market-price-reset{border:1px solid #cbd5e1;border-radius:9px;background:#fff;color:#334155;padding:9px 10px;font-size:12px;font-weight:750;cursor:pointer}"
        ".market-price-reset:hover{background:#f8fafc}"
    )
    replace_once(css_marker, css_new, "market controls css")

    mobile_marker = ".market-controls .control{flex:1 1 100%}"
    mobile_new = mobile_marker + (
        ".market-price-range{width:100%}.market-price-range label{flex:1 1 125px}"
        ".market-price-input{width:100%;min-width:0}.market-price-reset{flex:0 0 auto}"
    )
    replace_once(mobile_marker, mobile_new, "mobile market controls css")

    old_controls = (
        '<div class="market-controls"><select id="marketScale" class="control" aria-label="価格軸">'
        '<option value="linear">価格軸：線形</option><option value="log">価格軸：対数</option></select></div>'
    )
    new_controls = (
        '<div class="market-controls"><select id="marketScale" class="control" aria-label="価格軸">'
        '<option value="linear">価格軸：線形</option><option value="log">価格軸：対数</option></select>'
        '<div class="market-price-range" aria-label="現在価格の表示範囲">'
        '<label>下限<input id="marketMinPrice" class="control market-price-input" type="number" min="0" step="100" inputmode="numeric" placeholder="万円"></label>'
        '<span class="muted">〜</span>'
        '<label>上限<input id="marketMaxPrice" class="control market-price-input" type="number" min="0" step="100" inputmode="numeric" placeholder="万円"></label>'
        '<button id="marketPriceReset" class="market-price-reset" type="button">範囲解除</button>'
        '</div></div>'
    )
    replace_once(old_controls, new_controls, "market controls html")

    s = s.replace(
        '<span>線に触れると物件名・日付・価格を表示</span>',
        '<span>点をクリック／タップすると、その物件の詳細を直接開きます</span>',
        1,
    )

if "function marketPriceRange()" not in s:
    helper = (
        "function marketPriceRange(){let minRaw=$('marketMinPrice').value.trim(),maxRaw=$('marketMaxPrice').value.trim(),"
        "min=minRaw===''?null:Number(minRaw),max=maxRaw===''?null:Number(maxRaw);"
        "if(Number.isFinite(min)&&Number.isFinite(max)&&min>max){let t=min;min=max;max=t}"
        "return{min:Number.isFinite(min)?min:null,max:Number.isFinite(max)?max:null}}\n"
        "function marketRangeIncludes(x,range){let history=marketHistory(x),current=x.priceYen!=null?Number(x.priceYen)/10000:(history.length?history.at(-1).price:null);"
        "if(!Number.isFinite(current))return false;return(range.min==null||current>=range.min)&&(range.max==null||current<=range.max)}\n"
    )
    replace_once("function drawMarketChart(scope){", helper + "function drawMarketChart(scope){", "market helpers")
    replace_once(
        "B=34,series=scope.map(x=>({x,pts:marketHistory(x)}))",
        "B=34,range=marketPriceRange(),series=scope.filter(x=>marketRangeIncludes(x,range)).map(x=>({x,pts:marketHistory(x)}))",
        "market series range filter",
    )
    replace_once(
        "$('marketCount').textContent=`${series.length.toLocaleString('ja-JP')}物件を描画`;",
        "let rangeText=range.min!=null||range.max!=null?`（現在価格 ${range.min==null?'下限なし':Math.round(range.min).toLocaleString('ja-JP')+'万'}〜${range.max==null?'上限なし':Math.round(range.max).toLocaleString('ja-JP')+'万'}）`:'';$('marketCount').textContent=`${series.length.toLocaleString('ja-JP')}物件を描画${rangeText}`;",
        "market count range label",
    )

if "function nearestMarketPoint(" not in s:
    click_helpers = (
        "function nearestMarketPoint(e,maxDistance=32){let canvas=$('marketCanvas'),r=canvas.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top,best=null,bestD=Infinity;"
        "for(let series of marketGeometry)for(let point of series.geom){let d=(point.px-px)**2+(point.py-py)**2;if(d<bestD){bestD=d;best={series,point}}}"
        "return best&&bestD<=maxDistance*maxDistance?best:null}\n"
        "function openMarketPoint(e){let hit=nearestMarketPoint(e);if(!hit)return;$('marketTooltip').style.display='none';show(hit.series.item.id);"
        "if(!isMobile())requestAnimationFrame(()=>$('detail').scrollIntoView({behavior:'smooth',block:'start'}))}\n"
        "$('marketCanvas').addEventListener('click',openMarketPoint);"
        "$('marketCanvas').addEventListener('pointermove',e=>{$('marketCanvas').style.cursor=nearestMarketPoint(e,18)?'pointer':'crosshair'});\n"
    )
    replace_once("(async()=>{try{", click_helpers + "(async()=>{try{", "market point click handler")

if "marketPriceReset').onclick" not in s:
    old_listener = "$('marketScale').onchange=()=>drawMarketChart(filtered());"
    new_listener = (
        old_listener
        + "let marketRangeTimer;['marketMinPrice','marketMaxPrice'].forEach(id=>$(id).addEventListener('input',()=>{clearTimeout(marketRangeTimer);marketRangeTimer=setTimeout(()=>drawMarketChart(filtered()),120)}));"
        + "$('marketPriceReset').onclick=()=>{$('marketMinPrice').value='';$('marketMaxPrice').value='';drawMarketChart(filtered())};"
    )
    replace_once(old_listener, new_listener, "market range listeners")

if s != original:
    PATH.write_text(s, encoding="utf-8")
    print(f"patched {PATH}")
else:
    print("market range/click patch already applied")
