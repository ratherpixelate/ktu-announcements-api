import os
import sys
from pathlib import Path

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import httpx
import base64
from datetime import datetime, timezone
from app.scraper import scrape_announcements

def main():
    print(f"[{datetime.now(timezone.utc)}] Starting scheduled scrape...", flush=True)
    try:
        announcements, x_token, cached_attachments = scrape_announcements(fetch_attachments=True)
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Scrape failed: {e}", file=sys.stderr, flush=True)
        if "outage" in str(e).lower() or any(code in str(e) for code in ["502", "503", "504"]):
            print(f"[{datetime.now(timezone.utc)}] NOTE: KTU's official website is currently experiencing an outage. Pre-seeded and cached announcements on Render remain safe and served.", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc)}] Successfully scraped {len(announcements)} announcements and {len(cached_attachments)} attachments. Token present: {x_token is not None}", flush=True)

    render_api_url = os.environ.get("RENDER_API_URL")
    sync_secret = os.environ.get("SYNC_SECRET")

    if not render_api_url:
        print("RENDER_API_URL environment variable is not set. Skipping sync.", flush=True)
        return

    sync_endpoint = f"{render_api_url.rstrip('/')}/api/sync"
    payload = {
        "announcements": [json.loads(a.model_dump_json()) for a in announcements],
        "x_token": x_token,
        "cached_attachments": cached_attachments
    }

    headers = {
        "Content-Type": "application/json",
        "X-Sync-Secret": sync_secret or ""
    }

    max_sync_attempts = 2
    for sync_attempt in range(1, max_sync_attempts + 1):
        print(f"[{datetime.now(timezone.utc)}] [Attempt {sync_attempt}/{max_sync_attempts}] Syncing data to {sync_endpoint}...", flush=True)
        try:
            response = httpx.post(sync_endpoint, json=payload, headers=headers, timeout=90.0)
            if response.status_code == 200:
                print(f"[{datetime.now(timezone.utc)}] Successfully synced with Render: {response.json()}", flush=True)
                break
            else:
                print(f"[{datetime.now(timezone.utc)}] Sync attempt {sync_attempt} failed with HTTP {response.status_code}: {response.text}", file=sys.stderr, flush=True)
                if sync_attempt == max_sync_attempts:
                    sys.exit(1)
        except Exception as e:
            print(f"[{datetime.now(timezone.utc)}] Network error syncing with Render on attempt {sync_attempt}: {e}", file=sys.stderr, flush=True)
            if sync_attempt == max_sync_attempts:
                sys.exit(1)
        
        if sync_attempt < max_sync_attempts:
            import time
            time.sleep(5)

if __name__ == "__main__":
    main()
