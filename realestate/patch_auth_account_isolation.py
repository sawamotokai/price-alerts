#!/usr/bin/env python3
"""Upgrade dashboard auth to robust session handling and account-isolated favorites.

The auth helper block is inserted immediately before the base `normalize`
function.  Only that helper block may be replaced.  Using the favorites wrapper
as the end marker also swallowed the dashboard's base render/chart functions,
leaving the page stuck at "データ読込中…" with `render is not defined`.
"""
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
source = PATH.read_text(encoding="utf-8")
original = source

OLD_STATE = (
    "const PAGE_SIZE=50,GUEST_FAVORITES_KEY='realestate_guest_favorites_v1';"
    "let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),"
    "favoritesOnly=false,supabaseClient=null,currentUser=null,authInitialized=false,googleProviderEnabled=false;"
)
NEW_STATE = (
    "const PAGE_SIZE=50,GUEST_FAVORITES_KEY='realestate_guest_favorites_v2',"
    "LEGACY_FAVORITES_KEY='realestate_guest_favorites_v1',AUTH_FAVORITES_VERSION=2;"
    "let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),"
    "legacyFavoriteIds=new Set(),favoritesOnly=false,supabaseClient=null,currentUser=null,"
    "authInitialized=false,authBusy=true,googleProviderEnabled=false,lastAppliedUserId=null,authSequence=0;"
)

if OLD_STATE in source:
    source = source.replace(OLD_STATE, NEW_STATE, 1)
elif "AUTH_FAVORITES_VERSION=2" not in source:
    raise SystemExit("Could not locate the existing favorites state")

HELPERS = r'''function readFavoriteSet(key){try{let value=JSON.parse(localStorage.getItem(key)||'[]');return new Set(Array.isArray(value)?value.map(String):[])}catch(_){return new Set()}}
function writeFavoriteSet(key,value){localStorage.setItem(key,JSON.stringify([...value]))}
function loadGuestFavorites(){return readFavoriteSet(GUEST_FAVORITES_KEY)}
function saveGuestFavorites(){if(!currentUser)writeFavoriteSet(GUEST_FAVORITES_KEY,favoriteIds)}
function loadLegacyFavorites(){return readFavoriteSet(LEGACY_FAVORITES_KEY)}
function clearLegacyFavorites(){localStorage.removeItem(LEGACY_FAVORITES_KEY);legacyFavoriteIds=new Set()}
function isFavorite(id){return favoriteIds.has(String(id))}
function buildFavoriteButton(id,size=''){let button=document.createElement('button'),on=isFavorite(id);button.type='button';button.className=`favorite-btn ${size} ${on?'active':''}`.trim();button.dataset.favoriteId=String(id);button.textContent=on?'★':'☆';button.setAttribute('aria-label',on?'お気に入りから削除':'お気に入りに追加');button.title=on?'お気に入りから削除':'お気に入りに追加';return button}
function bindFavoriteButtons(root=document){root.querySelectorAll('[data-favorite-id]').forEach(button=>{button.onclick=async event=>{event.preventDefault();event.stopPropagation();await toggleFavorite(button.dataset.favoriteId)}})}
function setAuthMessage(message){let el=$('authMessage');if(el)el.textContent=message}
function ensureLegacyImportButton(){let panel=$('authPanel'),button=$('legacyFavoritesImport');if(!panel)return null;if(!button){button=document.createElement('button');button.id='legacyFavoritesImport';button.type='button';button.className='auth-button';button.onclick=importLegacyFavorites;panel.insertBefore(button,$('signOut'))}button.hidden=!(currentUser&&legacyFavoriteIds.size);button.style.display=button.hidden?'none':'';button.textContent=`旧端末のお気に入り ${legacyFavoriteIds.size}件を移行`;return button}
function renderAuthState(){let login=$('googleSignIn'),user=$('authUser'),logout=$('signOut'),toggle=$('marketFavoritesOnly');ensureLegacyImportButton();if(currentUser){let meta=currentUser.user_metadata||{},avatar=meta.avatar_url||meta.picture||'',email=currentUser.email||'Googleユーザー';user.hidden=false;user.style.display='';logout.hidden=false;logout.style.display='';login.hidden=true;login.style.display='none';login.disabled=false;user.innerHTML=`${avatar?`<img class="auth-avatar" src="${esc(avatar)}" alt="">`:''}<span>${esc(email)}</span>`;setAuthMessage(authBusy?`${email} のお気に入りを読み込み中…`:legacyFavoriteIds.size?`${email} · お気に入り ${favoriteIds.size}件。旧端末データは未移行です。`:`${email} · お気に入り ${favoriteIds.size}件を同期済みです。`)}else{user.hidden=true;user.style.display='none';logout.hidden=true;logout.style.display='none';login.hidden=false;login.style.display='';let cfg=window.REALESTATE_SUPABASE_CONFIG||{},ready=Boolean(cfg.url&&cfg.publishableKey&&window.supabase&&googleProviderEnabled);login.disabled=authBusy||!ready;setAuthMessage(authBusy?'ログイン状態を確認中…':!cfg.url||!cfg.publishableKey?'Supabase設定が必要です。お気に入りはこの端末に保存されます。':!googleProviderEnabled?'GoogleログインのProvider設定待ちです。お気に入りはこの端末に保存されます。':'Googleでログインするとお気に入りをアカウント別に同期できます。')}if(toggle){toggle.textContent=`${favoritesOnly?'★':'☆'} お気に入りのみ (${favoriteIds.size})`;toggle.classList.toggle('active',favoritesOnly)}}
async function detectGoogleProvider(){let cfg=window.REALESTATE_SUPABASE_CONFIG||{};try{let response=await fetch(cfg.url+'/auth/v1/settings',{headers:{apikey:cfg.publishableKey}}),settings=await response.json();googleProviderEnabled=Boolean(settings?.external?.google)}catch(_){googleProviderEnabled=false}renderAuthState()}
function cleanAuthUrl(){try{let url=new URL(location.href),changed=false;for(let key of ['code','error','error_code','error_description'])if(url.searchParams.has(key)){url.searchParams.delete(key);changed=true}if(/(?:access_token|refresh_token|provider_token)=/.test(url.hash)){url.hash='';changed=true}if(changed)history.replaceState(null,'',url.pathname+(url.searchParams.toString()?'?'+url.searchParams.toString():'')+url.hash)}catch(_){}}
async function signInWithGoogle(){if(!supabaseClient||!googleProviderEnabled){setAuthMessage('SupabaseのAuthentication > ProvidersでGoogleを有効にしてください。');return}authBusy=true;renderAuthState();let redirectTo=location.origin+location.pathname,{error}=await supabaseClient.auth.signInWithOAuth({provider:'google',options:{redirectTo,queryParams:{prompt:'select_account'}}});if(error){authBusy=false;renderAuthState();setAuthMessage('ログイン開始に失敗しました: '+error.message)}}
async function signOutUser(){if(!supabaseClient)return;authBusy=true;renderAuthState();let {error}=await supabaseClient.auth.signOut({scope:'local'});if(error){authBusy=false;renderAuthState();setAuthMessage('ログアウトに失敗しました: '+error.message)}}
function favoriteRows(ids,userId){return[...ids].map(id=>{let x=items.find(v=>String(v.id)===String(id));return{user_id:userId,listing_id:String(id),source:x?.source||null,listing_url:x?.url||null,listing_title:x?.title||x?.address||null}})}
async function loadCloudFavorites(options={}){if(!supabaseClient||!currentUser)return;let userId=currentUser.id,migrateGuest=Boolean(options.migrateGuest),{data,error}=await supabaseClient.from('listing_favorites').select('listing_id').eq('user_id',userId);if(currentUser?.id!==userId)return;if(error){favoriteIds=new Set();setAuthMessage('お気に入り読込エラー: '+error.message);return}let cloud=new Set((data||[]).map(row=>String(row.listing_id))),guest=migrateGuest?loadGuestFavorites():new Set();favoriteIds=new Set([...cloud,...guest]);if(guest.size){let result=await supabaseClient.from('listing_favorites').upsert(favoriteRows(guest,userId),{onConflict:'user_id,listing_id'});if(currentUser?.id!==userId)return;if(result.error)setAuthMessage('端末のお気に入り同期に失敗しました: '+result.error.message);else localStorage.removeItem(GUEST_FAVORITES_KEY)}}
async function importLegacyFavorites(){if(!supabaseClient||!currentUser||!legacyFavoriteIds.size)return;let userId=currentUser.id,copy=new Set(legacyFavoriteIds);authBusy=true;renderAuthState();let result=await supabaseClient.from('listing_favorites').upsert(favoriteRows(copy,userId),{onConflict:'user_id,listing_id'});if(currentUser?.id!==userId)return;if(result.error){authBusy=false;renderAuthState();setAuthMessage('旧お気に入りの移行に失敗しました: '+result.error.message);return}favoriteIds=new Set([...favoriteIds,...copy]);clearLegacyFavorites();authBusy=false;renderAuthState();render()}
async function applySession(session,options={}){let seq=++authSequence,nextUser=session?.user||null,nextId=nextUser?.id||null,previousId=lastAppliedUserId,force=Boolean(options.force);currentUser=nextUser;if(nextId&&nextId===previousId&&!force){authBusy=false;renderAuthState();return}authBusy=true;favoriteIds=new Set();renderAuthState();if(nextUser){let migrateGuest=previousId==null&&loadGuestFavorites().size>0;await loadCloudFavorites({migrateGuest})}else{favoriteIds=loadGuestFavorites()}if(seq!==authSequence)return;lastAppliedUserId=nextId;authBusy=false;authInitialized=true;renderAuthState();if(options.render!==false&&authInitialized)render()}
async function refreshAuthSession(force=false){if(!supabaseClient)return;let {data,error}=await supabaseClient.auth.getSession();if(error){setAuthMessage('セッション更新エラー: '+error.message);return}await applySession(data?.session||null,{event:'REFRESH',force})}
async function initAuth(){legacyFavoriteIds=loadLegacyFavorites();favoriteIds=loadGuestFavorites();authBusy=true;renderAuthState();let cfg=window.REALESTATE_SUPABASE_CONFIG||{};if(!(cfg.url&&cfg.publishableKey&&window.supabase)){authBusy=false;authInitialized=true;renderAuthState();return}supabaseClient=window.supabase.createClient(cfg.url,cfg.publishableKey,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});supabaseClient.auth.onAuthStateChange((event,session)=>{if(event==='TOKEN_REFRESHED'&&session?.user?.id===lastAppliedUserId){currentUser=session.user;renderAuthState();return}setTimeout(()=>applySession(session,{event,force:event==='SIGNED_IN'||event==='SIGNED_OUT'}),0)});await detectGoogleProvider();let {data,error}=await supabaseClient.auth.getSession(),session=data?.session||null;if(error)setAuthMessage('セッション確認エラー: '+error.message);if(!session){let code=new URL(location.href).searchParams.get('code');if(code){let exchange=await supabaseClient.auth.exchangeCodeForSession(code);if(!exchange.error)session=exchange.data?.session||null;else setAuthMessage('ログイン完了処理に失敗しました: '+exchange.error.message)}}await applySession(session,{event:'BOOTSTRAP',force:true,render:false});cleanAuthUrl();authBusy=false;authInitialized=true;renderAuthState();addEventListener('focus',()=>refreshAuthSession(true));document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refreshAuthSession(true)})}
async function toggleFavorite(id){id=String(id);let x=items.find(v=>String(v.id)===id),was=isFavorite(id),userId=currentUser?.id||null;if(was)favoriteIds.delete(id);else favoriteIds.add(id);if(!userId)saveGuestFavorites();render();if(!userId||!supabaseClient)return;let result=was?await supabaseClient.from('listing_favorites').delete().eq('user_id',userId).eq('listing_id',id):await supabaseClient.from('listing_favorites').upsert({user_id:userId,listing_id:id,source:x?.source||null,listing_url:x?.url||null,listing_title:x?.title||x?.address||null},{onConflict:'user_id,listing_id'});if(result.error&&currentUser?.id===userId){if(was)favoriteIds.add(id);else favoriteIds.delete(id);render();setAuthMessage('お気に入り保存エラー: '+result.error.message)}}
function toggleFavoritesOnly(){favoritesOnly=!favoritesOnly;renderAuthState();drawMarketChart(filtered())}
function decorateFavoriteControls(){let header=document.querySelector('thead tr');if(header&&!header.querySelector('.favorite-cell')){let th=document.createElement('th');th.className='favorite-cell';th.textContent='★';header.prepend(th)}document.querySelectorAll('#rows tr[data-id]').forEach(row=>{if(row.querySelector('.favorite-cell'))return;let td=document.createElement('td');td.className='favorite-cell';td.append(buildFavoriteButton(row.dataset.id,'small'));row.prepend(td)});document.querySelectorAll('.property-card[data-id]').forEach(card=>{if(card.querySelector('[data-favorite-id]'))return;let head=card.querySelector('.property-card-head');if(head)head.append(buildFavoriteButton(card.dataset.id,'small'))});document.querySelectorAll('[data-drop-id]').forEach(card=>{if(card.querySelector('[data-favorite-id]'))return;let meta=card.querySelector('.drop-meta');if(meta)meta.prepend(buildFavoriteButton(card.dataset.dropId,'small'))});bindFavoriteButtons()}
function decorateDetailFavorite(id){let head=$('detail')?.querySelector('.detail-head');if(!head||head.querySelector('[data-favorite-id]'))return;let close=head.querySelector('.detail-close'),actions=head.querySelector('.detail-actions');if(!actions){actions=document.createElement('div');actions.className='detail-actions';if(close)actions.append(close);head.append(actions)}actions.prepend(buildFavoriteButton(id));bindFavoriteButtons(head)}'''

# The auth helper block ends immediately before the dashboard's base normalize
# function.  Never use the favorites wrappers as an end marker: those wrappers
# come after render/show/chart declarations and would delete them all.
start = source.find("function loadGuestFavorites(){")
end = source.find("function normalize(", start)
if start < 0 or end < 0:
    if "AUTH_FAVORITES_VERSION=2" not in source:
        raise SystemExit("Could not locate the existing auth helper block")
    if start >= 0 and end < 0:
        raise SystemExit("Base dashboard normalize/render functions are missing; restore the v1 dashboard before applying auth isolation")
else:
    source = source[:start] + HELPERS + "\n" + source[end:]

if source != original:
    PATH.write_text(source, encoding="utf-8")
    print(f"upgraded account-isolated auth/favorites in {PATH}")
else:
    print("account-isolated auth/favorites already applied")
