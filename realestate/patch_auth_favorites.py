#!/usr/bin/env python3
"""Idempotently add Supabase Google auth and per-user favorites to the dashboard."""
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
s = PATH.read_text(encoding="utf-8")
original = s

SUPABASE_URL = "https://nswgzzvgmudtftvjogvt.supabase.co"
SUPABASE_KEY = "sb_publishable_ZcTEUk2Wj6Nq1dlFs5zU3g_FK08RoWc"


def replace_once(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        raise RuntimeError(f"patch marker not found: {label}")
    s = s.replace(old, new, 1)


if "realestate_guest_favorites_v1" not in s:
    auth_css = r'''
.top-side{display:flex;flex-direction:column;align-items:flex-end;gap:7px}.auth-panel{display:flex;align-items:center;gap:8px;min-height:38px}.auth-button{display:inline-flex;align-items:center;gap:7px;border:1px solid #cbd5e1;border-radius:999px;background:#fff;color:#0f172a;padding:8px 12px;font-weight:750;font-size:13px;cursor:pointer}.auth-button:hover{background:#f8fafc}.auth-button:disabled{opacity:.55;cursor:not-allowed}.auth-user{display:flex;align-items:center;gap:8px;font-size:12px;color:#475569}.auth-avatar{width:30px;height:30px;border-radius:999px;object-fit:cover;border:1px solid #e2e8f0}.auth-message{font-size:11px;color:var(--muted);max-width:310px;text-align:right}.favorite-btn{display:inline-grid;place-items:center;width:34px;height:34px;border:1px solid #cbd5e1;border-radius:999px;background:#fff;color:#94a3b8;font-size:19px;line-height:1;cursor:pointer;flex:0 0 auto}.favorite-btn:hover{background:#fffbeb;border-color:#fbbf24;color:#d97706}.favorite-btn.active{background:#fffbeb;border-color:#f59e0b;color:#f59e0b}.favorite-btn.small{width:30px;height:30px;font-size:17px}.favorite-cell{width:42px;padding-right:2px!important}.market-favorites{border:1px solid #cbd5e1;border-radius:9px;background:#fff;color:#334155;padding:9px 10px;font-size:12px;font-weight:750;cursor:pointer;white-space:nowrap}.market-favorites.active{background:#fffbeb;color:#b45309;border-color:#f59e0b}.detail-actions{display:flex;align-items:center;gap:8px}@media(max-width:760px){.top-side{width:100%;align-items:flex-start}.auth-panel{flex-wrap:wrap}.auth-message{text-align:left;max-width:none}}
'''.strip()
    replace_once("</style>", auth_css + "\n</style>", "auth css")

    old_header = '<div class="wrap"><header class="top"><div><h1 class="title">中古戸建 Price Watch</h1><div class="muted">品川区・目黒区 / 所有権の土地・土地建物のみ / 夜間バッチ収集</div></div><div id="updated" class="updated muted"></div></header>'
    new_header = '<div class="wrap"><header class="top"><div><h1 class="title">中古戸建 Price Watch</h1><div class="muted">品川区・目黒区 / 所有権の土地・土地建物のみ / 夜間バッチ収集</div></div><div class="top-side"><div id="authPanel" class="auth-panel"><button id="googleSignIn" class="auth-button" type="button">G&nbsp; Googleでログイン</button><div id="authUser" class="auth-user" hidden></div><button id="signOut" class="auth-button" type="button" hidden>ログアウト</button></div><div id="authMessage" class="auth-message">お気に入りはこの端末に保存されます。Googleログイン後はアカウントへ同期します。</div><div id="updated" class="updated muted"></div></div></header>'
    replace_once(old_header, new_header, "auth header")

    range_button = '<button id="marketPriceReset" class="market-price-reset" type="button">範囲解除</button></div></div></div><div class="market-chart-wrap">'
    range_button_new = '<button id="marketPriceReset" class="market-price-reset" type="button">範囲解除</button></div><button id="marketFavoritesOnly" class="market-favorites" type="button">☆ お気に入りのみ (0)</button></div></div><div class="market-chart-wrap">'
    replace_once(range_button, range_button_new, "favorites graph toggle")

    script_marker = "<script>\n'use strict';"
    script_new = (
        '<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.111.0/dist/umd/supabase.min.js"></script>\n'
        '<script>window.REALESTATE_SUPABASE_CONFIG={'
        f'url:"{SUPABASE_URL}",publishableKey:"{SUPABASE_KEY}"'
        '};</script>\n'
        "<script>\n'use strict';"
    )
    replace_once(script_marker, script_new, "supabase scripts")

    old_state = "const DATA_URL='https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data/dashboard.json';const CURRENT_URL='https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data/current.json';const PAGE_SIZE=50;let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[];"
    new_state = "const DATA_URL='https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data/dashboard.json';const CURRENT_URL='https://raw.githubusercontent.com/sawamotokai/price-alerts/master/realestate/data/current.json';const PAGE_SIZE=50,GUEST_FAVORITES_KEY='realestate_guest_favorites_v1';let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),favoritesOnly=false,supabaseClient=null,currentUser=null,authInitialized=false,googleProviderEnabled=false;"
    replace_once(old_state, new_state, "dashboard state")

    date_marker = "function dateOnly(v){return v?String(v).slice(0,10):'—'}"
    helpers = r'''
function loadGuestFavorites(){try{return new Set(JSON.parse(localStorage.getItem(GUEST_FAVORITES_KEY)||'[]').map(String))}catch(_){return new Set()}}
function saveGuestFavorites(){localStorage.setItem(GUEST_FAVORITES_KEY,JSON.stringify([...favoriteIds]))}
function isFavorite(id){return favoriteIds.has(String(id))}
function buildFavoriteButton(id,size=''){let button=document.createElement('button'),on=isFavorite(id);button.type='button';button.className=`favorite-btn ${size} ${on?'active':''}`.trim();button.dataset.favoriteId=String(id);button.textContent=on?'★':'☆';button.setAttribute('aria-label',on?'お気に入りから削除':'お気に入りに追加');button.title=on?'お気に入りから削除':'お気に入りに追加';return button}
function bindFavoriteButtons(root=document){root.querySelectorAll('[data-favorite-id]').forEach(button=>{button.onclick=async event=>{event.preventDefault();event.stopPropagation();await toggleFavorite(button.dataset.favoriteId)}})}
function setAuthMessage(message){let el=$('authMessage');if(el)el.textContent=message}
function renderAuthState(){let login=$('googleSignIn'),user=$('authUser'),logout=$('signOut'),toggle=$('marketFavoritesOnly');if(currentUser){let meta=currentUser.user_metadata||{},avatar=meta.avatar_url||meta.picture||'',email=currentUser.email||'Googleユーザー';user.hidden=false;logout.hidden=false;login.hidden=true;user.innerHTML=`${avatar?`<img class="auth-avatar" src="${esc(avatar)}" alt="">`:''}<span>${esc(email)}</span>`;setAuthMessage(`お気に入り ${favoriteIds.size}件をGoogleアカウントへ同期しています。`)}else{user.hidden=true;logout.hidden=true;login.hidden=false;let cfg=window.REALESTATE_SUPABASE_CONFIG||{},ready=Boolean(cfg.url&&cfg.publishableKey&&window.supabase&&googleProviderEnabled);login.disabled=!ready;setAuthMessage(!cfg.url||!cfg.publishableKey?'Supabase設定が必要です。お気に入りはこの端末に保存されます。':!googleProviderEnabled?'GoogleログインのProvider設定待ちです。お気に入りはこの端末に保存されます。':'Googleでログインするとお気に入りを端末間で同期できます。')}if(toggle){toggle.textContent=`${favoritesOnly?'★':'☆'} お気に入りのみ (${favoriteIds.size})`;toggle.classList.toggle('active',favoritesOnly)}}
async function detectGoogleProvider(){let cfg=window.REALESTATE_SUPABASE_CONFIG||{};try{let response=await fetch(cfg.url+'/auth/v1/settings',{headers:{apikey:cfg.publishableKey}}),settings=await response.json();googleProviderEnabled=Boolean(settings?.external?.google)}catch(_){googleProviderEnabled=false}renderAuthState()}
async function signInWithGoogle(){if(!supabaseClient||!googleProviderEnabled){setAuthMessage('SupabaseのAuthentication > ProvidersでGoogleを有効にしてください。');return}let redirectTo=location.origin+location.pathname,{error}=await supabaseClient.auth.signInWithOAuth({provider:'google',options:{redirectTo}});if(error)setAuthMessage('ログイン開始に失敗しました: '+error.message)}
async function signOutUser(){if(supabaseClient)await supabaseClient.auth.signOut()}
async function loadCloudFavorites(){if(!supabaseClient||!currentUser)return;let guest=loadGuestFavorites(),{data,error}=await supabaseClient.from('listing_favorites').select('listing_id');if(error){setAuthMessage('お気に入り読込エラー: '+error.message);return}let cloud=new Set((data||[]).map(row=>String(row.listing_id))),merged=new Set([...cloud,...guest]);favoriteIds=merged;if(guest.size){let rows=[...guest].map(id=>{let x=items.find(v=>String(v.id)===id);return{user_id:currentUser.id,listing_id:id,source:x?.source||null,listing_url:x?.url||null,listing_title:x?.title||x?.address||null}}),result=await supabaseClient.from('listing_favorites').upsert(rows,{onConflict:'user_id,listing_id'});if(result.error)setAuthMessage('端末のお気に入り同期に失敗しました: '+result.error.message)}saveGuestFavorites()}
async function applySession(session){currentUser=session?.user||null;if(currentUser)await loadCloudFavorites();else favoriteIds=loadGuestFavorites();renderAuthState();if(authInitialized)render()}
async function initAuth(){favoriteIds=loadGuestFavorites();renderAuthState();let cfg=window.REALESTATE_SUPABASE_CONFIG||{};if(!(cfg.url&&cfg.publishableKey&&window.supabase)){authInitialized=true;return}supabaseClient=window.supabase.createClient(cfg.url,cfg.publishableKey,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});await detectGoogleProvider();let {data,error}=await supabaseClient.auth.getSession();if(error)setAuthMessage('セッション確認エラー: '+error.message);currentUser=data?.session?.user||null;if(currentUser)await loadCloudFavorites();supabaseClient.auth.onAuthStateChange((_event,session)=>setTimeout(()=>applySession(session),0));authInitialized=true;renderAuthState()}
async function toggleFavorite(id){id=String(id);let x=items.find(v=>String(v.id)===id),was=isFavorite(id);if(was)favoriteIds.delete(id);else favoriteIds.add(id);saveGuestFavorites();render();if(!currentUser||!supabaseClient)return;let result=was?await supabaseClient.from('listing_favorites').delete().eq('listing_id',id):await supabaseClient.from('listing_favorites').upsert({user_id:currentUser.id,listing_id:id,source:x?.source||null,listing_url:x?.url||null,listing_title:x?.title||x?.address||null},{onConflict:'user_id,listing_id'});if(result.error){if(was)favoriteIds.add(id);else favoriteIds.delete(id);saveGuestFavorites();render();setAuthMessage('お気に入り保存エラー: '+result.error.message)}}
function toggleFavoritesOnly(){favoritesOnly=!favoritesOnly;renderAuthState();drawMarketChart(filtered())}
function decorateFavoriteControls(){let header=document.querySelector('thead tr');if(header&&!header.querySelector('.favorite-cell')){let th=document.createElement('th');th.className='favorite-cell';th.textContent='★';header.prepend(th)}document.querySelectorAll('#rows tr[data-id]').forEach(row=>{if(row.querySelector('.favorite-cell'))return;let td=document.createElement('td');td.className='favorite-cell';td.append(buildFavoriteButton(row.dataset.id,'small'));row.prepend(td)});document.querySelectorAll('.property-card[data-id]').forEach(card=>{if(card.querySelector('[data-favorite-id]'))return;let head=card.querySelector('.property-card-head');if(head)head.append(buildFavoriteButton(card.dataset.id,'small'))});document.querySelectorAll('[data-drop-id]').forEach(card=>{if(card.querySelector('[data-favorite-id]'))return;let meta=card.querySelector('.drop-meta');if(meta)meta.prepend(buildFavoriteButton(card.dataset.dropId,'small'))});bindFavoriteButtons()}
function decorateDetailFavorite(id){let head=$('detail')?.querySelector('.detail-head');if(!head||head.querySelector('[data-favorite-id]'))return;let close=head.querySelector('.detail-close'),actions=head.querySelector('.detail-actions');if(!actions){actions=document.createElement('div');actions.className='detail-actions';if(close)actions.append(close);head.append(actions)}actions.prepend(buildFavoriteButton(id));bindFavoriteButtons(head)}
'''.strip()
    replace_once(date_marker, date_marker + "\n" + helpers, "auth helpers")

    wrapper_marker = "function populateSources(){"
    wrappers = r'''
const renderWithoutFavorites=render;render=function(){renderWithoutFavorites();decorateFavoriteControls();renderAuthState()};
const showWithoutFavorites=show;show=function(id){showWithoutFavorites(id);decorateDetailFavorite(id)};
const drawMarketChartWithoutFavorites=drawMarketChart;drawMarketChart=function(scope){return drawMarketChartWithoutFavorites(favoritesOnly?scope.filter(x=>isFavorite(x.id)):scope)};
$('googleSignIn').onclick=signInWithGoogle;$('signOut').onclick=signOutUser;$('marketFavoritesOnly').onclick=toggleFavoritesOnly;
'''.strip() + "\n"
    replace_once(wrapper_marker, wrappers + wrapper_marker, "function wrappers")

    init_marker = "items=raw.map(normalize).filter(x=>x.id&&x.active!==false&&!String(x.url||'').includes('/inquire/')&&String(x.title||'')!=='資料請求'&&!isNonFreehold(x));populateSources();"
    init_new = "items=raw.map(normalize).filter(x=>x.id&&x.active!==false&&!String(x.url||'').includes('/inquire/')&&String(x.title||'')!=='資料請求'&&!isNonFreehold(x));await initAuth();populateSources();"
    replace_once(init_marker, init_new, "auth initialization")

# Always keep the public project config current.
s = s.replace(
    "window.REALESTATE_SUPABASE_CONFIG={url:\"" + SUPABASE_URL + "\",publishableKey:\"" + SUPABASE_KEY + "\"};",
    "window.REALESTATE_SUPABASE_CONFIG={url:\"" + SUPABASE_URL + "\",publishableKey:\"" + SUPABASE_KEY + "\"};",
)

if s != original:
    PATH.write_text(s, encoding="utf-8")
    print(f"patched {PATH}")
else:
    print("auth/favorites patch already applied")
