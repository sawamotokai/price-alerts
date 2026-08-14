#!/usr/bin/env python3
"""Expose OAuth callback failures and label guest favorites as device-local.

Supabase can redirect back to the app with OAuth error query parameters. The
previous dashboard immediately removed those parameters and then rendered the
normal unauthenticated message, which made a failed Google login look like a
successful login that simply had stale favorites. This patch captures the
callback error before cleaning the URL and keeps the browser-only state
explicit until a real Supabase user session exists.
"""
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
source = PATH.read_text(encoding="utf-8")
original = source

if "AUTH_FAILURE_REPORTING_VERSION=1" not in source:
    state_candidates = [
        "AUTH_FAVORITES_VERSION=2,AUTH_DATA_SYNC_VERSION=1;let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),legacyFavoriteIds=new Set(),favoritesOnly=false,supabaseClient=null,currentUser=null,authInitialized=false,authBusy=true,googleProviderEnabled=false,lastAppliedUserId=null,authSequence=0,dataInitialized=false;",
        "AUTH_FAVORITES_VERSION=2;let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),legacyFavoriteIds=new Set(),favoritesOnly=false,supabaseClient=null,currentUser=null,authInitialized=false,authBusy=true,googleProviderEnabled=false,lastAppliedUserId=null,authSequence=0;",
    ]
    replacement = None
    for candidate in state_candidates:
        if candidate in source:
            replacement = candidate.replace(
                "AUTH_FAVORITES_VERSION=2",
                "AUTH_FAVORITES_VERSION=2,AUTH_FAILURE_REPORTING_VERSION=1",
                1,
            ).replace(
                "authSequence=0,dataInitialized=false;",
                "authSequence=0,dataInitialized=false,oauthCallbackError='';",
                1,
            ).replace(
                "authSequence=0;",
                "authSequence=0,oauthCallbackError='';",
                1,
            )
            source = source.replace(candidate, replacement, 1)
            break
    if replacement is None:
        raise SystemExit("Could not locate dashboard auth state")

    marker = "function setAuthMessage(message){let el=$('authMessage');if(el)el.textContent=message}"
    helpers = r'''
function readOAuthCallbackError(){try{let url=new URL(location.href),code=url.searchParams.get('error_code')||url.searchParams.get('error')||'',description=url.searchParams.get('error_description')||'',raw=String(description||code).trim();if(!raw)return'';if(/invalid_client|client secret|unable to exchange external code/i.test(raw))return'Googleログイン失敗: Google OAuthのClient Secretが無効か、Client IDと一致していません。';return`Googleログイン失敗: ${raw}`}catch(_){return''}}
function guestFavoritesMessage(){return`現在は未ログインです。お気に入り ${favoriteIds.size}件はこのブラウザだけに保存されています。`}
'''.strip()
    if marker not in source:
        raise SystemExit("Could not locate auth message helper")
    source = source.replace(marker, marker + "\n" + helpers, 1)

    current_user_marker = "if(currentUser){let meta=currentUser.user_metadata||{}"
    if current_user_marker not in source:
        raise SystemExit("Could not locate authenticated UI branch")
    source = source.replace(
        current_user_marker,
        "if(currentUser){oauthCallbackError='';let meta=currentUser.user_metadata||{}",
        1,
    )

    unauth_marker = "setAuthMessage(authBusy?'ログイン状態を確認中…':"
    if unauth_marker not in source:
        raise SystemExit("Could not locate unauthenticated auth message")
    source = source.replace(
        unauth_marker,
        "setAuthMessage(authBusy?'ログイン状態を確認中…':oauthCallbackError?`${oauthCallbackError} ${guestFavoritesMessage()}`:",
        1,
    )

    sign_in_marker = "async function signInWithGoogle(){if(!supabaseClient||!googleProviderEnabled){setAuthMessage('SupabaseのAuthentication > ProvidersでGoogleを有効にしてください。');return}authBusy=true;"
    if sign_in_marker not in source:
        raise SystemExit("Could not locate Google sign-in function")
    source = source.replace(
        sign_in_marker,
        "async function signInWithGoogle(){if(!supabaseClient||!googleProviderEnabled){setAuthMessage('SupabaseのAuthentication > ProvidersでGoogleを有効にしてください。');return}oauthCallbackError='';authBusy=true;",
        1,
    )

    init_marker = "async function initAuth(){legacyFavoriteIds=loadLegacyFavorites();"
    if init_marker not in source:
        raise SystemExit("Could not locate auth initialization")
    source = source.replace(
        init_marker,
        "async function initAuth(){oauthCallbackError=readOAuthCallbackError();legacyFavoriteIds=loadLegacyFavorites();",
        1,
    )

if source != original:
    PATH.write_text(source, encoding="utf-8")
    print(f"patched OAuth failure reporting in {PATH}")
else:
    print("OAuth failure reporting already applied")
