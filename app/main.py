from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from typing import Optional
from app import cache
from app.models import AnnouncementsResponse, Announcement, SyncPayload
from app.scraper import download_attachment as scraper_download
from fastapi.responses import HTMLResponse
import asyncio
import httpx
import re
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    """Check if the API is running and when it last scraped data."""
    return {
        "status": "online",
        "cached_items": len(cache.state["announcements"]),
        "last_updated": cache.state["last_updated"],
        "last_attempt": cache.state["last_attempt"],
        "last_error": cache.state["last_error"],
        "has_token": cache.state["x_token"] is not None,
        "token_preview": cache.state["x_token"][:15] if cache.state["x_token"] else "No token found!"
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
            "has_token": cache.state["x_token"] is not None,
            "token_preview": cache.state["x_token"][:15] if cache.state["x_token"] else "No token found!"
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
    limit: int | None = Query(None, description="Max number of announcements to return"),
    new_only: bool = Query(False, description="Only return announcements marked as 'New'"),
    scheme: str | None = Query(None, description="Filter by scheme year")
):
    """Get all announcements, optionally filtered by limit or new status."""
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

    # Fallback to current time if cache hasn't finished its first run yet
    updated_time = cache.state["last_updated"] or datetime.now(timezone.utc)

    return AnnouncementsResponse(
        success=True,
        count=len(results),
        last_updated=updated_time,
        data=results
    )

@app.get("/announcements/{announcement_id}", response_model=Announcement)
def get_single_announcement(announcement_id: str):
    """Fetch a single announcement by its exact ID."""
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
            headers={"Content-Disposition": f'attachment; filename="{cached["filename"]}"'}
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
            headers={"Content-Disposition": f'attachment; filename="{real_file_name}"'}
        )
        
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from KTU: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="google-site-verification" content="C_ItUx9PVzCwP9D2doe3bbM-Yfutkx0L-PeWnPhN4Pg" />
    <meta name="description" content="Unofficial REST API for APJ Abdul Kalam Technological University (KTU) announcements. Built with FastAPI and Playwright.">
    <title>KTU Announcements API</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Syne:wght@400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
        background: #0d0f0e;
        font-family: 'Syne', sans-serif;
        color: #e8e6e0;
        min-height: 100vh;
        padding: 2.5rem 2rem 3rem;
        }
        .badge {
        display: inline-block;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: #6fcf8a;
        border: 0.5px solid #6fcf8a44;
        border-radius: 4px;
        padding: 3px 10px;
        margin-bottom: 1rem;
        letter-spacing: 0.08em;
        }
        h1 {
        font-size: 26px;
        font-weight: 700;
        color: #f0ede6;
        margin-bottom: 0.3rem;
        letter-spacing: -0.02em;
        }
        .subtitle {
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        color: #6b6b62;
        margin-bottom: 2.5rem;
        }
        .base-url {
        display: flex;
        align-items: center;
        gap: 10px;
        background: #161815;
        border: 0.5px solid #2a2d28;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-bottom: 2rem;
        }
        .base-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: #6b6b62;
        white-space: nowrap;
        letter-spacing: 0.05em;
        }
        .base-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        color: #a8c7b0;
        word-break: break-all;
        }
        .section-label {
        font-size: 11px;
        color: #4a4a43;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-family: 'JetBrains Mono', monospace;
        margin-bottom: 0.75rem;
        }
        .endpoints {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 2rem;
        }
        .endpoint {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        background: #161815;
        border: 0.5px solid #232620;
        border-radius: 8px;
        padding: 0.9rem 1rem;
        text-decoration: none;
        transition: border-color 0.15s, background 0.15s;
        }
        .endpoint:hover {
        border-color: #3a3d38;
        background: #1a1d19;
        }
        .method {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 600;
        color: #6fcf8a;
        background: #6fcf8a14;
        border: 0.5px solid #6fcf8a33;
        border-radius: 4px;
        padding: 2px 7px;
        letter-spacing: 0.05em;
        white-space: nowrap;
        margin-top: 1px;
        }
        .ep-right { flex: 1; min-width: 0; }
        .ep-path {
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        color: #c8c5bc;
        margin-bottom: 3px;
        }
        .ep-path span { color: #7ba88a; }
        .ep-desc {
        font-size: 12px;
        color: #5a5a52;
        font-family: 'JetBrains Mono', monospace;
        }
        .ep-arrow {
        color: #303330;
        font-size: 14px;
        margin-top: 2px;
        transition: color 0.15s, transform 0.15s;
        }
        .endpoint:hover .ep-arrow {
        color: #6fcf8a;
        transform: translateX(2px);
        }
        .links {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        }
        .link-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: #6b6b62;
        border: 0.5px solid #232620;
        border-radius: 6px;
        padding: 6px 12px;
        text-decoration: none;
        background: #161815;
        transition: color 0.15s, border-color 0.15s;
        }
        .link-btn:hover { color: #a8c7b0; border-color: #3a3d38; }
        hr { border: none; border-top: 0.5px solid #1e201d; margin: 2rem 0; }
        .disclaimer {
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: #3a3a34;
        line-height: 1.7;
        }
    </style>
    </head>
    <body>
    <div class="badge">&#9679; LIVE</div>
    <h1>KTU Announcements API</h1>
    <p class="subtitle">// unofficial &middot; community-maintained &middot; open-source</p>

    <div class="base-url">
        <span class="base-label">BASE URL</span>
        <span class="base-value">https://ktu-announcements-api-wxk8.onrender.com</span>
    </div>

    <p class="section-label">Endpoints</p>
    <div class="endpoints">
        <a class="endpoint" href="/announcements">
        <span class="method">GET</span>
        <div class="ep-right">
            <div class="ep-path">/announcements</div>
            <div class="ep-desc">Returns all cached announcements</div>
        </div>
        <span class="ep-arrow"><i class="ti ti-arrow-right"></i></span>
        </a>
        <a class="endpoint" href="/announcements?limit=5">
        <span class="method">GET</span>
        <div class="ep-right">
            <div class="ep-path">/announcements<span>?limit=5</span></div>
            <div class="ep-desc">Returns the N most recent announcements</div>
        </div>
        <span class="ep-arrow"><i class="ti ti-arrow-right"></i></span>
        </a>
        <a class="endpoint" href="/download/example">
        <span class="method">GET</span>
        <div class="ep-right">
            <div class="ep-path">/download/<span>{encrypt_id}</span></div>
            <div class="ep-desc">Downloads an attached document directly as a PDF</div>
        </div>
        <span class="ep-arrow"><i class="ti ti-arrow-right"></i></span>
        </a>
        <a class="endpoint" href="/health">
        <span class="method">GET</span>
        <div class="ep-right">
            <div class="ep-path">/health</div>
            <div class="ep-desc">API status and cache info</div>
        </div>
        <span class="ep-arrow"><i class="ti ti-arrow-right"></i></span>
        </a>
        <a class="endpoint" href="/docs">
        <span class="method">GET</span>
        <div class="ep-right">
            <div class="ep-path">/docs</div>
            <div class="ep-desc">Interactive Swagger UI documentation</div>
        </div>
        <span class="ep-arrow"><i class="ti ti-arrow-right"></i></span>
        </a>
    </div>

    <p class="section-label">Links</p>
    <div class="links">
        <a class="link-btn" href="https://github.com/ratherpixelate/ktu-announcements-api" target="_blank">
        <i class="ti ti-brand-github"></i> GitHub
        </a>
        <a class="link-btn" href="/docs">
        <i class="ti ti-file-description"></i> Swagger Docs
        </a>
        <a class="link-btn" href="https://ktu.edu.in" target="_blank">
        <i class="ti ti-external-link"></i> ktu.edu.in
        </a>
    </div>

    <hr>
    <p class="disclaimer">
        // Not affiliated with APJ Abdul Kalam Technological University.<br>
        // Use responsibly. Data sourced from ktu.edu.in.
    </p>
    </body>
    </html>
    """