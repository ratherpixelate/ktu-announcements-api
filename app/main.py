from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from typing import Optional
from app import cache
from app.models import AnnouncementsResponse, Announcement, SyncPayload
from app.scraper import download_attachment as scraper_download
from fastapi.responses import HTMLResponse
import httpx
import os
import base64



# This lifespan function runs when the server starts and stops
@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("ENABLE_IN_CONTAINER_SCRAPER", "").lower() in ("true", "1"):
        print("Starting in-container background scraper...", flush=True)
        cache.start_scheduler()
    else:
        print("Running in decoupled API mode (scraper managed externally via GitHub Actions)", flush=True)
    yield
    print("Shutting down...", flush=True)

app = FastAPI(
    title="KTU Announcements API",
    description="Unofficial API for APJ Abdul Kalam Technological University (KTU) Announcements",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware allows any website's frontend to call this API without being blocked
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

@app.get("/health")
def health_check(response: Response):
    """Check if the API is running and when it last scraped data."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "status": "online",
        "cached_items": len(cache.state["announcements"]),
        "last_updated": cache.state["last_updated"],
        "last_attempt": cache.state["last_attempt"],
        "last_error": cache.state["last_error"],
        "has_token": cache.state["x_token"] is not None
    }

@app.get("/refresh")
async def refresh_cache(
    secret: Optional[str] = Query(None, description="Secret key to authorize on-demand scraper dispatch"),
    x_refresh_secret: Optional[str] = Header(None, alias="X-Refresh-Secret"),
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """Trigger a cache update or dispatch GitHub Actions scraper if running in decoupled mode with authorization."""
    if os.environ.get("ENABLE_IN_CONTAINER_SCRAPER", "").lower() in ("true", "1"):
        cache.update_cache()
        return {
            "status": "online",
            "mode": "in-container",
            "cached_items": len(cache.state["announcements"]),
            "last_updated": cache.state["last_updated"],
            "has_token": cache.state["x_token"] is not None
        }

    github_repo = os.environ.get("GITHUB_REPO", "ratherpixelate/ktu-announcements-api")
    expected_secret = os.environ.get("REFRESH_SECRET") or os.environ.get("SYNC_SECRET")

    # Extract provided secret from query param, X-Refresh-Secret header, or Bearer auth
    provided_secret = secret or x_refresh_secret
    if not provided_secret and authorization:
        if authorization.lower().startswith("bearer "):
            provided_secret = authorization[7:].strip()
        else:
            provided_secret = authorization.strip()

    # 1. Authorization Gate: require matching secret to dispatch GitHub Actions
    if not expected_secret or provided_secret != expected_secret:
        return {
            "status": "online",
            "mode": "decoupled",
            "message": "Scraping runs automatically every 30m via GitHub Actions.",
            "auth_required": True,
            "tip": "To trigger an immediate scrape, supply your secret via '?secret=...' query parameter or 'X-Refresh-Secret' header.",
            "actions_url": f"https://github.com/{github_repo}/actions",
            "cached_items": len(cache.state["announcements"]),
            "last_updated": cache.state["last_updated"],
            "has_token": cache.state["x_token"] is not None
        }

    # 2. Cooldown Gate: mandatory 10-minute (600s) cooldown between dispatches
    now = datetime.now(timezone.utc)
    last_dispatch = cache.state.get("last_dispatch")
    cooldown_seconds = 600  # 10 minutes

    if last_dispatch:
        elapsed = (now - last_dispatch).total_seconds()
        if elapsed < cooldown_seconds:
            remaining = int(cooldown_seconds - elapsed)
            return {
                "status": "cooldown",
                "mode": "decoupled",
                "message": f"A scrape was recently triggered. Cooldown active: please wait {remaining} seconds before triggering again.",
                "cooldown_remaining_seconds": remaining,
                "actions_url": f"https://github.com/{github_repo}/actions",
                "cached_items": len(cache.state["announcements"]),
                "last_updated": cache.state["last_updated"]
            }

    # 3. GitHub PAT Check
    github_pat = os.environ.get("GITHUB_PAT") or os.environ.get("GH_TOKEN")
    if not github_pat:
        return {
            "status": "error",
            "mode": "decoupled",
            "message": "GITHUB_PAT environment variable is not configured in Render. Cannot dispatch workflow.",
            "actions_url": f"https://github.com/{github_repo}/actions"
        }

    # 4. Dispatch GitHub Actions workflow
    dispatch_url = f"https://api.github.com/repos/{github_repo}/actions/workflows/scraper.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "KTU-Announcements-API"
    }
    payload = {"ref": "main"}
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(dispatch_url, json=payload, headers=headers, timeout=10.0)
            if res.status_code == 204:
                cache.state["last_dispatch"] = now
                return {
                    "status": "dispatched",
                    "mode": "decoupled",
                    "message": "Scraper workflow dispatched on GitHub Actions. Cache will update in ~1-2 minutes.",
                    "cooldown_seconds": cooldown_seconds,
                    "actions_url": f"https://github.com/{github_repo}/actions",
                    "cached_items": len(cache.state["announcements"]),
                    "last_updated": cache.state["last_updated"]
                }
            else:
                return {
                    "status": "error",
                    "mode": "decoupled",
                    "message": f"GitHub dispatch failed with HTTP {res.status_code}: {res.text}",
                    "cached_items": len(cache.state["announcements"]),
                    "last_updated": cache.state["last_updated"]
                }
    except Exception as e:
        return {
            "status": "error",
            "mode": "decoupled",
            "message": f"Failed to contact GitHub API: {str(e)}",
            "cached_items": len(cache.state["announcements"]),
            "last_updated": cache.state["last_updated"]
        }

@app.post("/api/sync")
def sync_data(payload: SyncPayload, x_sync_secret: str = Header(..., alias="X-Sync-Secret")):
    """Receive announcements, x-token, and pre-cached attachments from external scraper."""
    expected_secret = os.environ.get("SYNC_SECRET")
    if not expected_secret or x_sync_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing sync secret")
    
    if payload.announcements:
        cache.state["announcements"] = payload.announcements
        cache.state["last_updated"] = datetime.now(timezone.utc)
    if payload.x_token:
        cache.state["x_token"] = payload.x_token
    if payload.cached_attachments:
        if "attachments" not in cache.state:
            cache.state["attachments"] = {}
        for ca in payload.cached_attachments:
            try:
                pdf_bytes = base64.b64decode(ca.content_b64)
                cache.state["attachments"][ca.encrypt_id] = {
                    "filename": ca.filename,
                    "bytes": pdf_bytes
                }
            except Exception as e:
                print(f"Error decoding cached attachment {ca.encrypt_id}: {e}", flush=True)

    cache.state["last_attempt"] = datetime.now(timezone.utc)
    cache.state["last_error"] = None

    print(f"[{datetime.now(timezone.utc)}] Successfully synced {len(payload.announcements)} announcements and {len(payload.cached_attachments or [])} cached attachments via /api/sync", flush=True)
    return {
        "status": "success",
        "synced_items": len(payload.announcements),
        "cached_attachments": len(payload.cached_attachments or []),
        "has_token": payload.x_token is not None,
        "last_updated": cache.state["last_updated"]
    }

@app.get("/announcements", response_model=AnnouncementsResponse)
def get_announcements(
    response: Response,
    limit: int | None = Query(None, description="Max number of announcements to return"),
    new_only: bool = Query(False, description="Only return announcements marked as 'New'"),
    scheme: str | None = Query(None, description="Filter by scheme year")
):
    """Get all announcements, optionally filtered by limit or new status."""
    response.headers["Cache-Control"] = "public, max-age=300"
    results = cache.state["announcements"]

    if scheme:
        results = [
            a for a in results 
            if scheme in a.schemes or "General" in a.schemes
        ]

    if new_only:
        results = [a for a in results if a.is_new]
        
    if limit is not None:
        results = results[:limit]

    return AnnouncementsResponse(
        success=True,
        count=len(results),
        last_updated=cache.state["last_updated"],
        data=results
    )

@app.get("/announcements/{announcement_id}", response_model=Announcement)
def get_single_announcement(announcement_id: str, response: Response):
    """Fetch a single announcement by its exact ID."""
    response.headers["Cache-Control"] = "public, max-age=300"
    for ann in cache.state["announcements"]:
        if ann.id == announcement_id:
            return ann
            
    raise HTTPException(status_code=404, detail="Announcement not found")

@app.get("/download/{encrypt_id}")
async def download_pdf(encrypt_id: str):
    """Download an attachment by its encryptId with its original filename."""
    # 1. First check if the attachment was pre-cached during the scheduled scrape
    cached = cache.state.get("attachments", {}).get(encrypt_id)
    if cached:
        return Response(
            content=cached["bytes"], 
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{cached["filename"]}"',
                "Cache-Control": "public, max-age=86400"
            }
        )

    # 2. Search the cache for the real file name
    real_file_name = f"KTU_Document_{encrypt_id[:6]}.pdf"  # Fallback name
    
    for ann in cache.state.get("announcements", []):
        for att in ann.attachments:
            if att.encrypt_id == encrypt_id:
                # Clean the string to ensure it's a valid filename (remove weird characters)
                clean_name = "".join(c for c in att.name if c.isalnum() or c in " ._-").strip()
                # Ensure it ends with .pdf
                if not clean_name.lower().endswith(".pdf"):
                    clean_name += ".pdf"
                real_file_name = clean_name
                break

    # 3. Fallback to live download if not pre-cached
    if not cache.state.get("x_token"):
        raise HTTPException(
            status_code=503, 
            detail="API is warming up and hasn't generated an access token yet. Try again in a minute."
        )
    
    try:
        # Fetch the PDF bytes asynchronously
        pdf_bytes = await scraper_download(encrypt_id, cache.state["x_token"])
        
        # Return the bytes with the dynamically found real_file_name
        return Response(
            content=pdf_bytes, 
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{real_file_name}"',
                "Cache-Control": "public, max-age=86400"
            }
        )
        
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from KTU: {str(e)}")

LANDING_PAGE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="google-site-verification" content="C_ItUx9PVzCwP9D2doe3bbM-Yfutkx0L-PeWnPhN4Pg" />
  <meta name="description" content="Unofficial REST API for APJ Abdul Kalam Technological University (KTU) announcements. Built with FastAPI and Camoufox.">
  <title>KTU Announcements API</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎓</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />
  <style>
    :root {
      /* Material Design 3 Light Theme Tokens — Claude Warm Terracotta */
      --md-sys-color-primary: #c05638;
      --md-sys-color-on-primary: #ffffff;
      --md-sys-color-primary-container: #ffdbd1;
      --md-sys-color-on-primary-container: #3c1105;
      --md-sys-color-secondary: #755951;
      --md-sys-color-on-secondary: #ffffff;
      --md-sys-color-secondary-container: #fadbd2;
      --md-sys-color-on-secondary-container: #2b1711;
      --md-sys-color-tertiary: #735c2b;
      --md-sys-color-on-tertiary: #ffffff;
      --md-sys-color-tertiary-container: #ffe1a3;
      --md-sys-color-on-tertiary-container: #271c00;
      --md-sys-color-surface: #faf9f5;
      --md-sys-color-on-surface: #1f1d1b;
      --md-sys-color-on-surface-variant: #514b46;
      --md-sys-color-surface-container-lowest: #ffffff;
      --md-sys-color-surface-container-low: #f5f3ed;
      --md-sys-color-surface-container: #efece3;
      --md-sys-color-surface-container-high: #e9e5db;
      --md-sys-color-surface-container-highest: #e3ded3;
      --md-sys-color-outline: #847c76;
      --md-sys-color-outline-variant: #d5cec7;
      --md-sys-color-inverse-surface: #34302d;
      --md-sys-color-inverse-on-surface: #f8f4ee;
      --md-sys-color-error: #ba1a1a;
      --md-sys-color-error-container: #ffdad6;
      --md-sys-color-on-error-container: #410002;

      /* MD3 Shape Tokens */
      --md-sys-shape-corner-extra-small: 4px;
      --md-sys-shape-corner-small: 8px;
      --md-sys-shape-corner-medium: 12px;
      --md-sys-shape-corner-large: 16px;
      --md-sys-shape-corner-extra-large: 28px;
      --md-sys-shape-corner-full: 9999px;

      /* MD3 Motion & Transition */
      --md-sys-motion-easing-emphasized: cubic-bezier(0.2, 0, 0, 1);
      --md-sys-motion-duration-short: 150ms;
      --md-sys-motion-duration-medium: 250ms;
    }

    [data-theme="dark"] {
      /* Material Design 3 Dark Theme Tokens — Claude Warm Charcoal & Terracotta */
      --md-sys-color-primary: #e28468;
      --md-sys-color-on-primary: #47190a;
      --md-sys-color-primary-container: #5e2614;
      --md-sys-color-on-primary-container: #ffdbd1;
      --md-sys-color-secondary: #dec2b8;
      --md-sys-color-on-secondary: #412b23;
      --md-sys-color-secondary-container: #3a2e2a;
      --md-sys-color-on-secondary-container: #fadbd2;
      --md-sys-color-tertiary: #e5c384;
      --md-sys-color-on-tertiary: #3f300c;
      --md-sys-color-tertiary-container: #44371b;
      --md-sys-color-on-tertiary-container: #ffe1a3;
      --md-sys-color-surface: #181816;
      --md-sys-color-on-surface: #ede8e3;
      --md-sys-color-on-surface-variant: #c4bcb5;
      --md-sys-color-surface-container-lowest: #111110;
      --md-sys-color-surface-container-low: #201f1d;
      --md-sys-color-surface-container: #262522;
      --md-sys-color-surface-container-high: #2e2d29;
      --md-sys-color-surface-container-highest: #373531;
      --md-sys-color-outline: #8c827b;
      --md-sys-color-outline-variant: #433e39;
      --md-sys-color-inverse-surface: #ede8e3;
      --md-sys-color-inverse-on-surface: #1f1d1b;
      --md-sys-color-error: #ffb4ab;
      --md-sys-color-error-container: #93000a;
      --md-sys-color-on-error-container: #ffdad6;
    }

    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--md-sys-color-surface);
      color: var(--md-sys-color-on-surface);
      font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      transition: background-color var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-emphasized),
                  color var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-emphasized);
    }

    /* Top App Bar */
    .top-app-bar {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 64px;
      padding: 0 16px 0 24px;
      background-color: var(--md-sys-color-surface-container);
      border-bottom: 1px solid var(--md-sys-color-outline-variant);
      transition: background-color var(--md-sys-motion-duration-medium) var(--md-sys-motion-easing-emphasized);
    }

    .app-bar-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
      color: var(--md-sys-color-on-surface);
    }

    .brand-icon {
      font-size: 26px;
      color: var(--md-sys-color-primary);
    }

    .brand-title {
      font-size: 19px;
      font-weight: 500;
      letter-spacing: -0.01em;
    }

    .app-bar-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Live Status Badge */
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: var(--md-sys-shape-corner-full);
      font-size: 12px;
      font-weight: 500;
      letter-spacing: 0.02em;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid transparent;
      transition: background-color var(--md-sys-motion-duration-short) ease,
                  border-color var(--md-sys-motion-duration-short) ease,
                  color var(--md-sys-motion-duration-short) ease;
    }

    .status-badge:hover {
      border-color: var(--md-sys-color-outline-variant);
      opacity: 0.92;
    }

    .status-healthy {
      background-color: var(--md-sys-color-secondary-container);
      color: var(--md-sys-color-on-secondary-container);
    }

    .status-healthy .status-dot {
      background-color: #22c55e;
      box-shadow: 0 0 8px rgba(34, 197, 94, 0.7);
    }

    .status-warning {
      background-color: var(--md-sys-color-tertiary-container);
      color: var(--md-sys-color-on-tertiary-container);
    }

    .status-warning .status-dot {
      background-color: #f59e0b;
      box-shadow: 0 0 8px rgba(245, 158, 11, 0.7);
    }

    .status-error {
      background-color: var(--md-sys-color-error-container);
      color: var(--md-sys-color-on-error-container);
    }

    .status-error .status-dot {
      background-color: var(--md-sys-color-error);
      box-shadow: 0 0 8px rgba(239, 68, 68, 0.7);
    }

    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex-shrink: 0;
      transition: background-color var(--md-sys-motion-duration-short) ease,
                  box-shadow var(--md-sys-motion-duration-short) ease;
    }

    /* MD3 Icon Button */
    .icon-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border: none;
      border-radius: var(--md-sys-shape-corner-full);
      background: transparent;
      color: var(--md-sys-color-on-surface-variant);
      cursor: pointer;
      transition: background-color var(--md-sys-motion-duration-short) ease,
                  color var(--md-sys-motion-duration-short) ease;
    }

    .icon-button:hover {
      background-color: var(--md-sys-color-surface-container-highest);
      color: var(--md-sys-color-on-surface);
    }

    /* Main Container */
    main {
      flex: 1;
      width: 100%;
      max-width: 860px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }

    /* Hero Section */
    .hero-card {
      background-color: var(--md-sys-color-surface-container-low);
      border-radius: var(--md-sys-shape-corner-extra-large);
      padding: 32px 28px;
      margin-bottom: 32px;
      border: 1px solid var(--md-sys-color-outline-variant);
    }

    .hero-title {
      font-size: 28px;
      font-weight: 700;
      line-height: 1.25;
      color: var(--md-sys-color-on-surface);
      margin-bottom: 12px;
    }

    .hero-subtitle {
      font-size: 15px;
      line-height: 1.6;
      color: var(--md-sys-color-on-surface-variant);
      margin-bottom: 24px;
      max-width: 680px;
    }

    /* Base URL Display */
    .base-url-box {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 16px;
      background-color: var(--md-sys-color-surface-container-highest);
      border-radius: var(--md-sys-shape-corner-large);
      border: 1px solid var(--md-sys-color-outline-variant);
    }

    .base-url-meta {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }

    .base-url-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--md-sys-color-primary);
    }

    .base-url-text {
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      color: var(--md-sys-color-on-surface);
      word-break: break-all;
    }

    .copy-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border: none;
      border-radius: var(--md-sys-shape-corner-full);
      background-color: var(--md-sys-color-primary-container);
      color: var(--md-sys-color-on-primary-container);
      font-family: inherit;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
      transition: opacity var(--md-sys-motion-duration-short) ease;
    }

    .copy-btn:hover {
      opacity: 0.9;
    }

    .copy-btn .material-symbols-outlined {
      font-size: 16px;
    }

    /* Section Headers */
    .section-title {
      font-size: 18px;
      font-weight: 500;
      color: var(--md-sys-color-on-surface);
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .section-title .material-symbols-outlined {
      color: var(--md-sys-color-primary);
      font-size: 22px;
    }

    /* Endpoints Grid */
    .endpoints-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-bottom: 36px;
    }

    /* MD3 Outlined Card */
    .endpoint-card {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 14px 18px;
      background-color: var(--md-sys-color-surface);
      border: 1px solid var(--md-sys-color-outline-variant);
      border-radius: var(--md-sys-shape-corner-medium);
      text-decoration: none;
      color: inherit;
      transition: background-color var(--md-sys-motion-duration-short) ease,
                  border-color var(--md-sys-motion-duration-short) ease,
                  transform var(--md-sys-motion-duration-short) ease;
    }

    .endpoint-card:hover {
      background-color: var(--md-sys-color-surface-container-low);
      border-color: var(--md-sys-color-primary);
      transform: translateY(-1px);
    }

    /* Method Badges */
    .method-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 8px;
      border-radius: var(--md-sys-shape-corner-small);
      letter-spacing: 0.05em;
      min-width: 44px;
      text-align: center;
    }

    .method-get {
      background-color: var(--md-sys-color-secondary-container);
      color: var(--md-sys-color-on-secondary-container);
    }

    .method-post {
      background-color: var(--md-sys-color-tertiary-container);
      color: var(--md-sys-color-on-tertiary-container);
    }

    .endpoint-details {
      flex: 1;
      min-width: 0;
    }

    .endpoint-path {
      font-family: 'JetBrains Mono', monospace;
      font-size: 13.5px;
      font-weight: 500;
      color: var(--md-sys-color-on-surface);
      margin-bottom: 2px;
    }

    .endpoint-path .param {
      color: var(--md-sys-color-primary);
      font-weight: 600;
    }

    .endpoint-desc {
      font-size: 12.5px;
      color: var(--md-sys-color-on-surface-variant);
    }

    .endpoint-card .card-arrow {
      color: var(--md-sys-color-outline);
      font-size: 20px;
      transition: transform var(--md-sys-motion-duration-short) ease,
                  color var(--md-sys-motion-duration-short) ease;
    }

    .endpoint-card:hover .card-arrow {
      color: var(--md-sys-color-primary);
      transform: translateX(3px);
    }

    /* Resource Links Row */
    .links-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 40px;
    }

    .btn-filled {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      border-radius: var(--md-sys-shape-corner-full);
      background-color: var(--md-sys-color-primary);
      color: var(--md-sys-color-on-primary);
      text-decoration: none;
      font-size: 13px;
      font-weight: 500;
      transition: opacity var(--md-sys-motion-duration-short) ease;
    }

    .btn-filled:hover {
      opacity: 0.92;
    }

    .btn-outlined {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      border-radius: var(--md-sys-shape-corner-full);
      border: 1px solid var(--md-sys-color-outline);
      background-color: transparent;
      color: var(--md-sys-color-on-surface);
      text-decoration: none;
      font-size: 13px;
      font-weight: 500;
      transition: background-color var(--md-sys-motion-duration-short) ease;
    }

    .btn-outlined:hover {
      background-color: var(--md-sys-color-surface-container-high);
    }

    /* Footer */
    footer {
      border-top: 1px solid var(--md-sys-color-outline-variant);
      padding: 24px 20px;
      background-color: var(--md-sys-color-surface-container-lowest);
      text-align: center;
    }

    .footer-text {
      font-size: 12px;
      line-height: 1.6;
      color: var(--md-sys-color-on-surface-variant);
    }
  </style>
</head>
<body>
  <!-- MD3 Top App Bar -->
  <header class="top-app-bar">
    <a href="/" class="app-bar-brand">
      <span class="material-symbols-outlined brand-icon">school</span>
      <span class="brand-title">KTU Announcements API</span>
    </a>
    <div class="app-bar-actions">
      <a href="/health" class="status-badge __STATUS_CLASS__" id="statusBadge" title="__STATUS_TITLE__">
        <span class="status-dot"></span>
        <span id="statusText">__STATUS_TEXT__</span>
      </a>
      <button class="icon-button" id="themeToggle" aria-label="Toggle light or dark theme" title="Toggle theme">
        <span class="material-symbols-outlined" id="themeIcon">light_mode</span>
      </button>
    </div>
  </header>

  <!-- Main Content -->
  <main>
    <section class="hero-card">
      <h1 class="hero-title">Automated REST Access to KTU Announcements</h1>
      <p class="hero-subtitle">
        Direct, decoupled API service scraping circulars and notifications from APJ Abdul Kalam Technological University via <strong>Camoufox</strong>. Attachments are pre-cached in memory for instant downloads.
      </p>

      <div class="base-url-box">
        <div class="base-url-meta">
          <span class="base-url-label">API Base URL</span>
          <span class="base-url-text" id="baseUrlText">https://ktu-announcements-api-wxk8.onrender.com</span>
        </div>
        <button class="copy-btn" id="copyBtn">
          <span class="material-symbols-outlined" id="copyIcon">content_copy</span>
          <span id="copyLabel">Copy</span>
        </button>
      </div>
    </section>

    <!-- Endpoints Section -->
    <h2 class="section-title">
      <span class="material-symbols-outlined">api</span>
      <span>API Endpoints</span>
    </h2>

    <div class="endpoints-list">
      <a class="endpoint-card" href="/announcements">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/announcements</div>
          <div class="endpoint-desc">List all cached university announcements</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/announcements?limit=5">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/announcements<span class="param">?limit=5</span></div>
          <div class="endpoint-desc">Retrieve only the N most recent records</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/announcements?new_only=true">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/announcements<span class="param">?new_only=true</span></div>
          <div class="endpoint-desc">Filter records flagged as new by KTU</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/announcements?scheme=2019">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/announcements<span class="param">?scheme=2019</span></div>
          <div class="endpoint-desc">Filter by scheme (e.g. 2015, 2019, 2024, or General)</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/docs#/default/get_single_announcement_announcements__announcement_id__get">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/announcements/<span class="param">{id}</span></div>
          <div class="endpoint-desc">Fetch a single announcement by its numeric ID</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/docs#/default/download_pdf_download__encrypt_id__get">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/download/<span class="param">{encrypt_id}</span></div>
          <div class="endpoint-desc">Download an attached document directly as a PDF (pre-cached)</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/health">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/health</div>
          <div class="endpoint-desc">Service status, Turnstile token state, and cache timestamps</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/refresh">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/refresh<span class="param">?secret=...</span></div>
          <div class="endpoint-desc">Dispatch on-demand scraper run (requires secret, 10m cooldown)</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/docs#/default/sync_data_api_sync_post">
        <span class="method-badge method-post">POST</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/api/sync</div>
          <div class="endpoint-desc">Scraper data ingestion endpoint (requires X-Sync-Secret)</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>

      <a class="endpoint-card" href="/docs">
        <span class="method-badge method-get">GET</span>
        <div class="endpoint-details">
          <div class="endpoint-path">/docs</div>
          <div class="endpoint-desc">Interactive Swagger UI / OpenAPI documentation</div>
        </div>
        <span class="material-symbols-outlined card-arrow">arrow_forward</span>
      </a>
    </div>

    <!-- Quick Links -->
    <h2 class="section-title">
      <span class="material-symbols-outlined">link</span>
      <span>Resources & Documentation</span>
    </h2>

    <div class="links-grid">
      <a class="btn-filled" href="/docs">
        <span class="material-symbols-outlined">menu_book</span>
        <span>Interactive API Docs</span>
      </a>
      <a class="btn-outlined" href="https://github.com/ratherpixelate/ktu-announcements-api" target="_blank" rel="noopener">
        <span class="material-symbols-outlined">code</span>
        <span>GitHub Repository</span>
      </a>
      <a class="btn-outlined" href="https://ktu.edu.in" target="_blank" rel="noopener">
        <span class="material-symbols-outlined">open_in_new</span>
        <span>Official KTU Portal</span>
      </a>
    </div>
  </main>

  <!-- Footer -->
  <footer>
    <p class="footer-text">
      Independent community-maintained project. Not affiliated with APJ Abdul Kalam Technological University.<br>
      Data sourced from ktu.edu.in for educational and developer usage.
    </p>
  </footer>

  <script>
    // Dynamic Base URL detection
    if (window.location && window.location.origin) {
      const el = document.getElementById('baseUrlText');
      if (el) el.textContent = window.location.origin;
    }

    // Copy Base URL functionality
    const copyBtn = document.getElementById('copyBtn');
    if (copyBtn) {
      copyBtn.addEventListener('click', async () => {
        const text = document.getElementById('baseUrlText').textContent;
        try {
          await navigator.clipboard.writeText(text);
          const icon = document.getElementById('copyIcon');
          const label = document.getElementById('copyLabel');
          icon.textContent = 'check';
          label.textContent = 'Copied!';
          setTimeout(() => {
            icon.textContent = 'content_copy';
            label.textContent = 'Copy';
          }, 2000);
        } catch (e) {
          console.error(e);
        }
      });
    }

    // Material 3 Theme Switcher (Dark / Light)
    const themeToggle = document.getElementById('themeToggle');
    const themeIcon = document.getElementById('themeIcon');
    const rootEl = document.documentElement;

    function applyTheme(theme) {
      rootEl.setAttribute('data-theme', theme);
      if (themeIcon) {
        themeIcon.textContent = theme === 'dark' ? 'light_mode' : 'dark_mode';
      }
      localStorage.setItem('m3-theme', theme);
    }

    // Initialize theme: saved preference -> system preference -> default dark
    const savedTheme = localStorage.getItem('m3-theme');
    if (savedTheme) {
      applyTheme(savedTheme);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      applyTheme('light');
    } else {
      applyTheme('dark');
    }

    if (themeToggle) {
      themeToggle.addEventListener('click', () => {
        const currentTheme = rootEl.getAttribute('data-theme') || 'dark';
        const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
        applyTheme(nextTheme);
      });
    }

    // Real-Time Health & Cache Status Updater
    const statusBadge = document.getElementById('statusBadge');
    const statusText = document.getElementById('statusText');

    function formatRelativeTime(dateString) {
      if (!dateString) return null;
      const date = new Date(dateString);
      const now = new Date();
      const diffSec = Math.floor((now - date) / 1000);
      if (diffSec < 60) return 'just now';
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `${diffHr}h ago`;
      return `${Math.floor(diffHr / 24)}d ago`;
    }

    async function updateHealthStatus() {
      if (!statusBadge || !statusText) return;
      try {
        const res = await fetch('/health');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        statusBadge.classList.remove('status-healthy', 'status-warning', 'status-error');

        if (data.last_error) {
          statusBadge.classList.add('status-warning');
          statusText.textContent = 'Sync Issue';
          statusBadge.title = `Sync warning: ${data.last_error}. Click for diagnostics.`;
        } else if (data.cached_items > 0) {
          statusBadge.classList.add('status-healthy');
          const relTime = formatRelativeTime(data.last_updated);
          if (relTime) {
            statusText.textContent = `Synced ${relTime} • ${data.cached_items} items`;
          } else {
            statusText.textContent = `Live • ${data.cached_items} items`;
          }
          statusBadge.title = `Cache healthy (${data.cached_items} announcements). Click for diagnostics.`;
        } else {
          statusBadge.classList.add('status-warning');
          statusText.textContent = 'Warming up';
          statusBadge.title = 'Cache is initializing. Click for diagnostics.';
        }
      } catch (err) {
        statusBadge.classList.remove('status-healthy', 'status-warning');
        statusBadge.classList.add('status-error');
        statusText.textContent = 'Disconnected';
        statusBadge.title = 'Cannot connect to API server. Click to view status.';
      }
    }

    window.addEventListener('focus', updateHealthStatus);
    setInterval(updateHealthStatus, 45000);
    setTimeout(updateHealthStatus, 1200);
  </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def root():
    cached_count = len(cache.state.get("announcements", []))
    last_error = cache.state.get("last_error")

    if last_error:
        initial_class = "status-warning"
        initial_text = "Sync Issue"
        initial_title = f"Sync warning: {last_error}. Click for diagnostics."
    elif cached_count > 0:
        initial_class = "status-healthy"
        initial_text = f"Live • {cached_count} items"
        initial_title = f"API and cache healthy ({cached_count} announcements). Click for diagnostics."
    else:
        initial_class = "status-warning"
        initial_text = "Warming up"
        initial_title = "Cache is initializing. Click for diagnostics."

    return (
        LANDING_PAGE_HTML
        .replace("__STATUS_CLASS__", initial_class)
        .replace("__STATUS_TEXT__", initial_text)
        .replace("__STATUS_TITLE__", initial_title)
    )