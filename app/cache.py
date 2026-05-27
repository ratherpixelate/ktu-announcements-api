from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
from app.scraper import scrape_announcements
from app.models import Announcement

# This is our in-memory database
state = {
    "announcements": [],
    "last_updated": None,
    "x_token": None
}

def update_cache():
    """Run the scraper and update the in-memory cache."""
    print(f"[{datetime.now(timezone.utc)}] Updating announcements cache via Playwright...")
    
    try:
        results, token = scrape_announcements()
        
        # We no longer need the 'global' keyword because we are modifying a dict
        if results:
            state["announcements"] = results
            state["last_updated"] = datetime.now(timezone.utc)
            print(f"[{datetime.now(timezone.utc)}] Cache updated successfully with {len(results)} announcements.")
            
        if token:
            state["x_token"] = token
            print(f"[{datetime.now(timezone.utc)}] x-token refreshed successfully.")
            
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Error updating cache: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_cache)
    scheduler.add_job(update_cache, 'interval', minutes=30)
    scheduler.start()