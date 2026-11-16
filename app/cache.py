import base64
import concurrent.futures
import json
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.models import Announcement
from app.scraper import scrape_announcements

# This is our in-memory database
state = {
    "announcements": [],
    "last_updated": None,
    "x_token": None,
    "last_error": None,
    "last_attempt": None,
    "attachments": {},
    "last_dispatch": None,
}

def load_seed_data():
    """Load pre-baked seed announcements if memory cache is empty."""
    if state["announcements"]:
        return

    seed_file = Path(__file__).resolve().parent.parent / "data" / "seed_announcements.json"
    if not seed_file.exists():
        return

    try:
        with open(seed_file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, dict):
            items = raw.get("announcements", [])
            last_updated_str = raw.get("last_updated")
        elif isinstance(raw, list):
            items = raw
            last_updated_str = None
        else:
            return

        parsed = [Announcement.model_validate(item) for item in items]
        if parsed:
            state["announcements"] = parsed
            if last_updated_str:
                try:
                    # Replace 'Z' with '+00:00' for Python < 3.11 compatibility if needed
                    state["last_updated"] = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                except Exception:
                    state["last_updated"] = datetime.now(timezone.utc)
            else:
                state["last_updated"] = datetime.now(timezone.utc)
            print(f"[{datetime.now(timezone.utc)}] Seed data loaded: {len(parsed)} announcements.", flush=True)
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Warning: Failed to load seed data: {e}", flush=True)

    seed_att_file = Path(__file__).resolve().parent.parent / "data" / "seed_attachments.json"
    if seed_att_file.exists() and not state["attachments"]:
        try:
            with open(seed_att_file, "r", encoding="utf-8") as f:
                raw_atts = json.load(f)
            loaded_count = 0
            for item in raw_atts:
                eid = item.get("encrypt_id")
                fname = item.get("filename")
                b64 = item.get("content_b64")
                if eid and b64:
                    state["attachments"][eid] = {
                        "filename": fname or f"KTU_Document_{eid[:6]}.pdf",
                        "bytes": base64.b64decode(b64)
                    }
                    loaded_count += 1
            if loaded_count:
                print(f"[{datetime.now(timezone.utc)}] Seed attachments loaded: {loaded_count} files.", flush=True)
        except Exception as e:
            print(f"[{datetime.now(timezone.utc)}] Warning: Failed to load seed attachments: {e}", flush=True)


def update_cache():
    """Run the scraper and update the in-memory cache."""
    print(f"[{datetime.now(timezone.utc)}] Updating announcements cache via Camoufox...", flush=True)
    state["last_attempt"] = datetime.now(timezone.utc)
    
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        # Protect against hung scraping threads by enforcing a 180s hard watchdog timeout
        cached_ids = set(state.get("attachments", {}).keys())
        future = executor.submit(scrape_announcements, fetch_attachments=True, already_cached_ids=cached_ids)
        results, token, cached_attachments = future.result(timeout=180)
        
        # We no longer need the 'global' keyword because we are modifying a dict
        if results:
            state["announcements"] = results
            state["last_updated"] = datetime.now(timezone.utc)
            print(f"[{datetime.now(timezone.utc)}] Cache updated successfully with {len(results)} announcements.", flush=True)
            
        if token:
            state["x_token"] = token
            print(f"[{datetime.now(timezone.utc)}] x-token refreshed successfully.", flush=True)

        if cached_attachments:
            for ca in cached_attachments:
                try:
                    pdf_bytes = base64.b64decode(ca["content_b64"])
                    state["attachments"][ca["encrypt_id"]] = {
                        "filename": ca["filename"],
                        "bytes": pdf_bytes
                    }
                except Exception as e:
                    print(f"Error caching attachment {ca.get('encrypt_id')}: {e}", flush=True)
            # Retain up to 25 attachments in memory to bound RAM usage
            if len(state["attachments"]) > 25:
                keys_to_remove = list(state["attachments"].keys())[:-25]
                for k in keys_to_remove:
                    state["attachments"].pop(k, None)
            print(f"[{datetime.now(timezone.utc)}] Cached {len(cached_attachments)} new attachments (total in memory: {len(state['attachments'])}).", flush=True)

        state["last_error"] = None
            
    except concurrent.futures.TimeoutError:
        error_msg = "Scraper execution timed out after 180 seconds."
        state["last_error"] = error_msg
        print(f"[{datetime.now(timezone.utc)}] {error_msg}", flush=True)
    except Exception as e:
        import traceback
        state["last_error"] = str(e)  
        print(f"[{datetime.now(timezone.utc)}] Error updating cache: {e}", flush=True)
        traceback.print_exc()
    finally:
        # Crucial: shutdown with wait=False so we don't hang if the worker thread is blocked
        executor.shutdown(wait=False, cancel_futures=True)

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_cache)
    scheduler.add_job(update_cache, 'interval', minutes=30)
    scheduler.start()