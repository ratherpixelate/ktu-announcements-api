from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from app import cache
from app.models import AnnouncementsResponse, Announcement
from app.scraper import download_attachment as scraper_download
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