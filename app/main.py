from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from app import cache
from app.models import AnnouncementsResponse, Announcement
from app.scraper import download_attachment as scraper_download
from fastapi.responses import HTMLResponse
import asyncio
import httpx
import re



# This lifespan function runs when the server starts and stops
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting background scraper...")
    cache.start_scheduler()
    yield
    print("Shutting down...")

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
        "has_token": cache.state["x_token"] is not None,
        "token_preview": cache.state["x_token"][:15] if cache.state["x_token"] else "No token found!"
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
    if not cache.state["x_token"]:
        raise HTTPException(
            status_code=503, 
            detail="API is warming up and hasn't generated an access token yet. Try again in a minute."
        )
    
    # 1. Search the cache for the real file name
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
    
    try:
        # Fetch the PDF bytes asynchronously
        pdf_bytes = await scraper_download(encrypt_id, cache.state["x_token"])
        
        # 2. Return the bytes with the dynamically found real_file_name
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