import os
import sys
from pathlib import Path

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import httpx
from datetime import datetime, timezone
from app.scraper import scrape_announcements

def main():
    print(f"[{datetime.now(timezone.utc)}] Starting scheduled scrape...", flush=True)
    try:
        announcements, x_token = scrape_announcements()
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Scrape failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc)}] Successfully scraped {len(announcements)} announcements. Token present: {x_token is not None}", flush=True)

    render_api_url = os.environ.get("RENDER_API_URL")
    sync_secret = os.environ.get("SYNC_SECRET")

    if not render_api_url:
        print("RENDER_API_URL environment variable is not set. Skipping sync.", flush=True)
        return

    sync_endpoint = f"{render_api_url.rstrip('/')}/api/sync"
    print(f"[{datetime.now(timezone.utc)}] Syncing data to {sync_endpoint}...", flush=True)

    payload = {
        "announcements": [json.loads(a.model_dump_json()) for a in announcements],
        "x_token": x_token
    }

    headers = {
        "Content-Type": "application/json",
        "X-Sync-Secret": sync_secret or ""
    }

    try:
        response = httpx.post(sync_endpoint, json=payload, headers=headers, timeout=30.0)
        if response.status_code == 200:
            print(f"[{datetime.now(timezone.utc)}] Successfully synced with Render: {response.json()}", flush=True)
        else:
            print(f"[{datetime.now(timezone.utc)}] Sync failed with HTTP {response.status_code}: {response.text}", file=sys.stderr, flush=True)
            sys.exit(1)
    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] Network error syncing with Render: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
