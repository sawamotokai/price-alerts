#!/usr/bin/env python3
"""Make dashboard data loading fast, non-blocking, and failure-visible.

The dashboard previously waited forever on two browser-side raw GitHub requests.
This patch races multiple CDN/origin mirrors with timeouts, lets auth initialize
in parallel, and treats the durable-history file as optional so the listing UI
can still render if that secondary request is unavailable.
"""
from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
s = PATH.read_text(encoding="utf-8")
original = s

RAW_BASE = "https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data"
CDN_BASE = "https://cdn.jsdelivr.net/gh/sawamotokai/price-alerts@master/realestate/data"

if "DATA_LOADING_VERSION=2" not in s:
    old_constants = (
        f"const DATA_URL='{RAW_BASE}/dashboard.json';"
        f"const CURRENT_URL='{RAW_BASE}/current.json';"
    )
    new_constants = (
        "const DATA_LOADING_VERSION=2;"
        f"const DATA_URLS=['{CDN_BASE}/dashboard.json','{RAW_BASE}/dashboard.json'];"
        f"const CURRENT_URLS=['{CDN_BASE}/current.json','{RAW_BASE}/current.json'];"
    )
    if old_constants not in s:
        raise SystemExit("Could not locate dashboard data URL constants")
    s = s.replace(old_constants, new_constants, 1)

    helpers = r'''
function dataUrlWithVersion(url){let separator=url.includes('?')?'&':'?';return url+separator+'v='+Math.floor(Date.now()/300000)}
async function fetchJsonCandidate(url,timeoutMs=12000){let controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);try{let response=await fetch(dataUrlWithVersion(url),{cache:'no-store',signal:controller.signal,headers:{accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status} ${url}`);return await response.json()}finally{clearTimeout(timer)}}
async function fetchJsonFromMirrors(urls,label,required=true){try{return await Promise.any(urls.map(url=>fetchJsonCandidate(url)))}catch(error){let reasons=error&&Array.isArray(error.errors)?error.errors.map(value=>value?.name==='AbortError'?'timeout':String(value?.message||value)).join(' / '):String(error?.message||error);if(required)throw new Error(`${label}を取得できませんでした: ${reasons}`);console.warn(`${label}は取得できなかったため省略します`,reasons);return{}}}
'''.strip() + "\n"
    # Point-click patch versions used different default radii (32/38). Insert
    # before the function name rather than matching a particular signature.
    helper_marker = "function nearestMarketPoint("
    helper_index = s.find(helper_marker)
    if helper_index < 0:
        raise SystemExit("Could not locate market point helper marker")
    s = s[:helper_index] + helpers + s[helper_index:]

    old_loader_prefix = (
        "(async()=>{try{let [r,currentResponse]=await Promise.all([fetch(DATA_URL,{cache:'no-store'}),"
        "fetch(CURRENT_URL,{cache:'no-store'})]);if(!r.ok)throw new Error('HTTP '+r.status);"
        "let data=await r.json(),current=currentResponse.ok?await currentResponse.json():{},raw="
    )
    new_loader_prefix = (
        "(async()=>{let authPromise=null;try{authPromise=initAuth();"
        "$('status').classList.remove('error');$('status').textContent='物件データを読み込んでいます…';"
        "let [data,current]=await Promise.all([fetchJsonFromMirrors(DATA_URLS,'物件データ',true),"
        "fetchJsonFromMirrors(CURRENT_URLS,'価格履歴',false)]),raw="
    )
    if old_loader_prefix not in s:
        raise SystemExit("Could not locate blocking dashboard loader")
    s = s.replace(old_loader_prefix, new_loader_prefix, 1)

    old_auth_wait = "await initAuth();populateSources();"
    new_auth_wait = "await authPromise;populateSources();"
    if old_auth_wait not in s:
        raise SystemExit("Could not locate auth wait in dashboard loader")
    s = s.replace(old_auth_wait, new_auth_wait, 1)

    old_catch = (
        "}catch(e){console.error(e);$('status').classList.add('error');"
        "$('status').textContent='データの読み込みに失敗しました。'}})();"
    )
    new_catch = (
        "}catch(e){console.error(e);try{if(authPromise)await authPromise}catch(authError){console.error(authError)}"
        "$('status').classList.add('error');$('status').textContent='データの読み込みに失敗しました: '+String(e?.message||e)}})();"
    )
    if old_catch not in s:
        raise SystemExit("Could not locate dashboard loader error handler")
    s = s.replace(old_catch, new_catch, 1)

if s != original:
    PATH.write_text(s, encoding="utf-8")
    print(f"patched resilient data loading in {PATH}")
else:
    print("resilient data loading already applied")
