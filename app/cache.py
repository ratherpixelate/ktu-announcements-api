from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
from app.scraper import scrape_announcements
from app.models import Announcement

# This is our in-memory database
cached_announcements: list[Announcement] = []
last_updated: datetime | None = None

def update_cache():
    """Run the scraper and update the in-memory cache."""
    global cached_announcements, last_updated
    print(f"[{datetime.now(timezone.utc)}] Updating announcements cache via Playwright...")
    
    try:
        results = scrape_announcements()
        if results:
            cached_announcements = results
            last_updated = datetime.now(timezone.utc)
            print(f"[{datetime.now(timezone.utc)}] Cache updated successfully with {len(results)} announcements.")
        else:
            print(f"[{datetime.now(timezone.utc)}] Scraper returned empty, keeping existing cache.")
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Error updating cache: {e}")

def start_scheduler():
    """Start the background job to scrape periodically."""
    scheduler = BackgroundScheduler()
    
    # Run the scraper once immediately when the app starts
    scheduler.add_job(update_cache)
    
    # Then run it every 30 minutes
    scheduler.add_job(update_cache, 'interval', minutes=30)
    
    scheduler.start()