#!/usr/bin/env python3
"""Prevent auth state callbacks from rendering an empty listing set.

Authentication and listing fetches run in parallel. A fast Supabase auth event
could call `render()` while `items` was still empty, replacing the loading state
with a misleading 0-record dashboard. Track data readiness explicitly and
only render listings after the first data snapshot has been assigned.

This patch is intentionally idempotent even when another dashboard patch
rewrites the auth helper block after AUTH_DATA_SYNC_VERSION was first added.
"""
from pathlib import Path

PATH = Path(__file__).resolve().parent / "dashboard" / "index.html"
s = PATH.read_text(encoding="utf-8")
original = s

old_state = "AUTH_FAVORITES_VERSION=2;let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),legacyFavoriteIds=new Set(),favoritesOnly=false,supabaseClient=null,currentUser=null,authInitialized=false,authBusy=true,googleProviderEnabled=false,lastAppliedUserId=null,authSequence=0;"
new_state = "AUTH_FAVORITES_VERSION=2,AUTH_DATA_SYNC_VERSION=1;let items=[],visibleLimit=PAGE_SIZE,selectedId=null,marketGeometry=[],favoriteIds=new Set(),legacyFavoriteIds=new Set(),favoritesOnly=false,supabaseClient=null,currentUser=null,authInitialized=false,authBusy=true,googleProviderEnabled=false,lastAppliedUserId=null,authSequence=0,dataInitialized=false;"

if "AUTH_DATA_SYNC_VERSION=1" not in s:
    if old_state not in s:
        raise SystemExit("Could not locate auth/favorites dashboard state")
    s = s.replace(old_state, new_state, 1)

# Another auth patch may rewrite applySession after the sync marker already
# exists. Always re-assert the data-readiness render guard.
old_apply = "if(options.render!==false&&authInitialized)render()"
new_apply = "if(options.render!==false&&authInitialized&&dataInitialized)render()"
if old_apply in s:
    s = s.replace(old_apply, new_apply, 1)
elif new_apply not in s:
    raise SystemExit("Could not locate auth session render guard")

# Likewise, make sure the first successfully loaded listing snapshot marks data
# ready before auth is allowed to trigger a render.
old_loader = ");items=raw.map(normalize).filter(x=>x.id&&x.active!==false&&!String(x.url||'').includes('/inquire/')&&String(x.title||'')!=='資料請求'&&!isNonFreehold(x));await authPromise;populateSources();"
new_loader = ");items=raw.map(normalize).filter(x=>x.id&&x.active!==false&&!String(x.url||'').includes('/inquire/')&&String(x.title||'')!=='資料請求'&&!isNonFreehold(x));dataInitialized=true;await authPromise;populateSources();"
if old_loader in s:
    s = s.replace(old_loader, new_loader, 1)
elif new_loader not in s:
    raise SystemExit("Could not locate resilient dashboard item assignment")

if s != original:
    PATH.write_text(s, encoding="utf-8")
    print(f"patched auth/data readiness race in {PATH}")
else:
    print("auth/data readiness race already patched")
