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
import time
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

def scrape_announcements(fetch_attachments: bool = True) -> tuple[list[Announcement], str | None, list[dict]]:
    """Fetch announcements and pre-cache attachments using Camoufox anti-detect browser."""
    announcements = []
    cached_attachments = []
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
        print(f"[{datetime.now(timezone.utc)}] Camoufox launched successfully.", flush=True)

        api_response = None
        max_attempts = 3
        last_error_details = None
        last_page = None

        for attempt in range(1, max_attempts + 1):
            page = browser.new_page(ignore_https_errors=True)
            last_page = page
            captured_responses = []
            backend_errors = []

            def on_response(response):
                if "/anon/announcemnts" in response.url:
                    if response.status == 200:
                        captured_responses.append(response)
                    elif response.status >= 500:
                        backend_errors.append(f"HTTP {response.status} on {response.url}")

            def on_request_failed(request):
                if "/anon/announcemnts" in request.url:
                    backend_errors.append(f"Request failed: {request.url} ({request.failure})")

            def on_console(msg):
                if any(code in msg.text for code in ["500", "502", "503", "504"]) and "announc" in msg.text.lower():
                    backend_errors.append(f"Console: {msg.text}")

            page.on("response", on_response)
            page.on("requestfailed", on_request_failed)
            page.on("console", on_console)

            print(f"[{datetime.now(timezone.utc)}] [Attempt {attempt}/{max_attempts}] Navigating to KTU announcements...", flush=True)
            try:
                page.goto(KTU_URL, timeout=45000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"[{datetime.now(timezone.utc)}] Navigation error on attempt {attempt}: {e}", flush=True)
                try:
                    page.close()
                except Exception:
                    pass
                pause = 5 if "UNKNOWN_HOST" in str(e) else 2
                time.sleep(pause)
                continue

            print(f"[{datetime.now(timezone.utc)}] Page loaded. Waiting for network response and Turnstile verification (up to 80s)...", flush=True)

            attempt_start = datetime.now(timezone.utc)
            attempt_timeout = 80

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
                print(f"[{datetime.now(timezone.utc)}] Attempt {attempt} got {last_error_details}. Cleaning session and retrying...", flush=True)
            elif backend_errors:
                outage_hint = next((err for err in backend_errors if any(code in err for code in ["502", "503", "504", "500"])), backend_errors[0])
                last_error_details = f"KTU official backend outage ({outage_hint})"
                print(f"[{datetime.now(timezone.utc)}] [OUTAGE DETECTED] Attempt {attempt}: KTU official servers (api.ktu.edu.in) appear to be down ({outage_hint}). Cleaning session and retrying...", flush=True)
            else:
                last_error_details = "no API response received within timeout"
                print(f"[{datetime.now(timezone.utc)}] Attempt {attempt} received no API responses. Cleaning session and retrying...", flush=True)

            if attempt < max_attempts:
                try:
                    page.close()
                except Exception:
                    pass
                time.sleep(3)

        if not api_response:
            try:
                if last_page:
                    last_page.screenshot(path="scraper_failure.png", full_page=True)
                    Path("scraper_failure.html").write_text(last_page.content(), encoding="utf-8")
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

        # In-browser attachment pre-fetching while Turnstile session is active
        if fetch_attachments and api_response and page:
            print(f"[{datetime.now(timezone.utc)}] Starting in-browser attachment pre-fetching...", flush=True)
            for ann in announcements:
                for att in ann.attachments:
                    eid = att.encrypt_id
                    if not eid:
                        continue
                    try:
                        # Check if button exists in DOM
                        btn_exists = page.evaluate(f'''() => {{
                            return !!document.querySelector('button[value="{eid}"]');
                        }}''')
                        if not btn_exists:
                            print(f"[{datetime.now(timezone.utc)}] Attachment button not in DOM for {eid}, skipping", flush=True)
                            continue

                        with page.expect_response(
                            lambda r: "getAttachment" in r.url and r.status == 200,
                            timeout=15000
                        ) as res_info:
                            page.evaluate(f'''() => {{
                                const btn = document.querySelector('button[value="{eid}"]');
                                if (btn) btn.click();
                            }}''')

                        res = res_info.value
                        body = res.body()
                        disposition = res.headers.get("content-disposition", "")

                        fname = None
                        if "filename=" in disposition:
                            fname = disposition.split("filename=")[-1].strip('"\' ;')

                        if not fname:
                            clean_name = "".join(c for c in att.name if c.isalnum() or c in " ._-").strip()
                            if not clean_name.lower().endswith(".pdf"):
                                clean_name += ".pdf"
                            fname = clean_name

                        raw_text = body.decode("utf-8", errors="ignore").strip().strip('"')
                        if "&&" in raw_text:
                            raw_text = raw_text[:raw_text.index("&&")]

                        decoded = base64.b64decode(raw_text)
                        if not decoded.startswith(b"%PDF"):
                            print(f"[{datetime.now(timezone.utc)}] Warning: attachment {eid} decoded content does not start with %PDF", flush=True)
                            continue

                        cached_attachments.append({
                            "encrypt_id": eid,
                            "filename": fname,
                            "content_b64": raw_text
                        })
                        print(f"[{datetime.now(timezone.utc)}] Successfully pre-cached: {fname} ({len(decoded)} bytes)", flush=True)
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"[{datetime.now(timezone.utc)}] Warning: failed to pre-cache attachment {eid}: {e}", flush=True)

    return announcements, x_token, cached_attachments

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
    
    async with httpx.AsyncClient(http1=True, http2=False, verify=False) as client:
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
    