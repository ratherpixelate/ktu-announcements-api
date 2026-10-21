from camoufox.sync_api import Camoufox
from datetime import datetime, date, timezone
from app.models import Attachment, Announcement
from bs4 import BeautifulSoup
from app.utils import extract_schemes
import httpx  
import re
import base64
import json
import shutil
import os
from pathlib import Path

KTU_URL = "https://ktu.edu.in/Menu/announcements"

def parse_date(date_str: str) -> date:
    """Convert date string like '2026-05-18 00:00:00' to a date object."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return datetime.today().date()

def handle_turnstile_challenge(page):
    """Attempt to solve or click any interactive Turnstile challenge if displayed."""
    try:
        for frame in page.frames:
            if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                for selector in ['input[type="checkbox"]', '#challenge-stage', '.ctp-checkbox-label', '#cf-stage', '[type="checkbox"]']:
                    loc = frame.locator(selector)
                    if loc.count() > 0:
                        first_loc = loc.first
                        if first_loc.is_visible():
                            print(f"[{datetime.now(timezone.utc)}] Interactive Turnstile challenge detected ({selector}). Clicking...", flush=True)
                            first_loc.click()
                            page.wait_for_timeout(2000)
                            return
    except Exception:
        pass

def scrape_announcements() -> tuple[list[Announcement], str | None]:
    """Fetch announcements by intercepting the API call using Camoufox anti-detect browser."""
    announcements = []
    scraped_at = datetime.now(timezone.utc)
    x_token = None

    # Headless mode: default to native Camoufox anti-detect headless engine (headless=True)
    headless_env = os.environ.get("CAMOUFOX_HEADLESS", "").lower()
    if headless_env in ("virtual",):
        headless_mode = "virtual"
    elif headless_env in ("false", "0"):
        headless_mode = False
    else:
        headless_mode = True

    print(f"[{datetime.now(timezone.utc)}] Launching Camoufox browser (headless={headless_mode!r}, geoip=True)...", flush=True)
    with Camoufox(
        headless=headless_mode,
        geoip=True,
        disable_coop=True,
        humanize=True,
        i_know_what_im_doing=True
    ) as browser:
        print(f"[{datetime.now(timezone.utc)}] Camoufox launched. Creating browser page...", flush=True)
        page = browser.new_page()

        captured_responses = []

        def on_response(response):
            if "/anon/announcemnts" in response.url:
                captured_responses.append(response)

        page.on("response", on_response)

        api_response = None
        max_attempts = 3
        last_error_details = None

        for attempt in range(1, max_attempts + 1):
            captured_responses.clear()
            print(f"[{datetime.now(timezone.utc)}] [Attempt {attempt}/{max_attempts}] Navigating to KTU announcements...", flush=True)
            try:
                page.goto(KTU_URL, timeout=45000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"[{datetime.now(timezone.utc)}] Navigation error on attempt {attempt}: {e}", flush=True)
                page.wait_for_timeout(2000)
                continue

            print(f"[{datetime.now(timezone.utc)}] Page loaded. Waiting for network response and Turnstile verification...", flush=True)

            attempt_start = datetime.now(timezone.utc)
            attempt_timeout = 25

            while (datetime.now(timezone.utc) - attempt_start).total_seconds() < attempt_timeout:
                handle_turnstile_challenge(page)

                for res in captured_responses:
                    if res.status == 200:
                        api_response = res
                        break

                if api_response:
                    break

                page.wait_for_timeout(1000)

            if api_response:
                break

            if captured_responses:
                last_res = captured_responses[-1]
                req_token = last_res.request.headers.get("x-token", "")
                try:
                    res_body = last_res.text()
                except Exception:
                    res_body = "(could not read body)"
                last_error_details = f"HTTP {last_res.status} (x-token: {repr(req_token)[:15]}, body: {res_body[:100]})"
                print(f"[{datetime.now(timezone.utc)}] Attempt {attempt} got {last_error_details}. Retrying with page reload...", flush=True)
            else:
                last_error_details = "no API response received within timeout"
                print(f"[{datetime.now(timezone.utc)}] Attempt {attempt} received no API responses. Retrying...", flush=True)

            page.wait_for_timeout(2000)

        if not api_response:
            try:
                page.screenshot(path="scraper_failure.png", full_page=True)
                Path("scraper_failure.html").write_text(page.content(), encoding="utf-8")
                print(f"[{datetime.now(timezone.utc)}] Saved diagnostic screenshot to scraper_failure.png and HTML to scraper_failure.html", flush=True)
            except Exception as e:
                print(f"[{datetime.now(timezone.utc)}] Failed to save diagnostic artifacts: {e}", flush=True)

            raise RuntimeError(f"KTU API failed after {max_attempts} attempts. Last result: {last_error_details}")

        # Extract the JSON payload directly from the intercepted network traffic!
        print(f"[{datetime.now(timezone.utc)}] Intercepted API response: HTTP {api_response.status}", flush=True)
        data = api_response.json()

        x_token = api_response.request.headers.get("x-token")
        print(f"[{datetime.now(timezone.utc)}] Extracted x-token: {repr(x_token)[:30]}...", flush=True)

        if data and "content" in data:
            for item in data["content"]:
                # Parse attachments
                attachments = []
                for att in item.get("attachmentList", []):
                    encrypt_id = att.get("encryptId", "").strip()
                    if encrypt_id:
                        attachments.append(Attachment(
                            name=att.get("title", "Document"),
                            encrypt_id=encrypt_id
                        ))
                
                raw_html = item.get("message")
                clean_text = None

                if raw_html:
                    clean_text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ").strip() 


                title = item.get("subject", "")
                full_text = f"{title} {clean_text or ''}"
                
                # Smart Parser Logic
                ann_date = parse_date(item.get("announcementDate", ""))
                unique_schemes = extract_schemes(ann_date, full_text)

                announcement = Announcement(
                    id=str(item["id"]),
                    title=title,
                    description_html=raw_html,
                    description_text=clean_text,
                    date=parse_date(item.get("announcementDate", "")),
                    is_new=item.get("status") == 1,
                    attachments=attachments,
                    scraped_at=scraped_at,
                    schemes=unique_schemes
                )
                announcements.append(announcement)

    return announcements, x_token

async def download_attachment(encrypt_id: str, x_token: str) -> bytes:
    if not x_token:
        raise ValueError("Missing x-token for authentication.")

    url = "https://api.ktu.edu.in/ktu-web-portal-api/anon/getAttachment"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "x-token": x_token,
        "Origin": "https://ktu.edu.in",
        "Referer": "https://ktu.edu.in/"
    }
    payload = {"encryptId": encrypt_id}
    
    async with httpx.AsyncClient(http1=True, http2=False) as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=60.0)
        
        if resp.status_code != 200:
            raise Exception(f"KTU API returned {resp.status_code}: {resp.text}")
        
        base64_string = resp.text.strip('"')

        if "&&" in base64_string:
            base64_string = base64_string[:base64_string.index("&&")]

        try:
            pdf_bytes = base64.b64decode(base64_string)
        except Exception as e:
            raise Exception(f"Failed to decode KTU's Base64 response: {str(e)}")
            
        if not pdf_bytes.startswith(b"%PDF"):
            raise Exception("Decoded bytes do not form a valid PDF.")

        return pdf_bytes
    