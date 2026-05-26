from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from app import cache
from app.models import AnnouncementsResponse, Announcement

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
        "cached_items": len(cache.cached_announcements),
        "last_updated": cache.last_updated
    }

@app.get("/announcements", response_model=AnnouncementsResponse)
def get_announcements(
    limit: int | None = Query(None, description="Max number of announcements to return"),
    new_only: bool = Query(False, description="Only return announcements marked as 'New'"),
    scheme: str | None = Query(None, description="Filter by scheme year")
):
    """Get all announcements, optionally filtered by limit or new status."""
    results = cache.cached_announcements

    if scheme:
        results = [a for a in results if scheme in a.schemes]

    if new_only:
        results = [a for a in results if a.is_new]
        
    if limit is not None:
        results = results[:limit]

    # Fallback to current time if cache hasn't finished its first run yet
    updated_time = cache.last_updated or datetime.now(timezone.utc)

    return AnnouncementsResponse(
        success=True,
        count=len(results),
        last_updated=updated_time,
        data=results
    )

@app.get("/announcements/{announcement_id}", response_model=Announcement)
def get_single_announcement(announcement_id: str):
    """Fetch a single announcement by its exact ID."""
    for ann in cache.cached_announcements:
        if ann.id == announcement_id:
            return ann
            
    raise HTTPException(status_code=404, detail="Announcement not found")