from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
from app.scraper import scrape_announcements
from app.models import Announcement

import concurrent.futures

# This is our in-memory database
state = {
    "announcements": [],
    "last_updated": None,
    "x_token": None,
    "last_error": None,
    "last_attempt": None,
}

def update_cache():
    """Run the scraper and update the in-memory cache."""
    print(f"[{datetime.now(timezone.utc)}] Updating announcements cache via Camoufox...", flush=True)
    state["last_attempt"] = datetime.now(timezone.utc)
    
    try:
        # Protect against hung scraping threads by enforcing a 120s hard watchdog timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(scrape_announcements)
            results, token = future.result(timeout=120)
        
        # We no longer need the 'global' keyword because we are modifying a dict
        if results:
            state["announcements"] = results
            state["last_updated"] = datetime.now(timezone.utc)
            print(f"[{datetime.now(timezone.utc)}] Cache updated successfully with {len(results)} announcements.", flush=True)
            
        if token:
            state["x_token"] = token
            print(f"[{datetime.now(timezone.utc)}] x-token refreshed successfully.", flush=True)
        state["last_error"] = None
            
    except concurrent.futures.TimeoutError:
        error_msg = "Scraper execution timed out after 120 seconds."
        state["last_error"] = error_msg
        print(f"[{datetime.now(timezone.utc)}] {error_msg}", flush=True)
    except Exception as e:
        import traceback
        state["last_error"] = str(e)  
        print(f"[{datetime.now(timezone.utc)}] Error updating cache: {e}", flush=True)
        traceback.print_exc()

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_cache)
    scheduler.add_job(update_cache, 'interval', minutes=30)
    scheduler.start()