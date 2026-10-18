from camoufox.sync_api import Camoufox
from datetime import datetime, date, timezone
from app.models import Attachment, Announcement
from bs4 import BeautifulSoup
from app.utils import extract_schemes
import httpx  
import re
import base64
import json

KTU_URL = "https://ktu.edu.in/Menu/announcements"

def parse_date(date_str: str) -> date:
    """Convert date string like '2026-05-18 00:00:00' to a date object."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return datetime.today().date()

def scrape_announcements() -> tuple[list[Announcement], str | None]:
    """Fetch announcements by intercepting the API call using Camoufox anti-detect browser."""
    announcements = []
    scraped_at = datetime.now(timezone.utc)
    x_token = None

    print(f"[{datetime.now(timezone.utc)}] Launching Camoufox browser (headless='virtual')...", flush=True)
    with Camoufox(
        headless="virtual",
        disable_coop=True,
        humanize=True,
        i_know_what_im_doing=True
    ) as browser:
        print(f"[{datetime.now(timezone.utc)}] Camoufox launched. Creating browser page...", flush=True)
        page = browser.new_page()

        print(f"[{datetime.now(timezone.utc)}] Navigating to KTU announcements and waiting for Turnstile + API response...", flush=True)
        
        # Listen for the specific API response we want
        with page.expect_response(
            lambda response: "/anon/announcemnts" in response.url,
            timeout=75000
        ) as response_info:
            page.goto(KTU_URL, timeout=60000, wait_until="domcontentloaded")
            print(f"[{datetime.now(timezone.utc)}] Navigation initiated. Waiting for network response...", flush=True)
        
        # Extract the JSON payload directly from the intercepted network traffic!
        api_response = response_info.value
        print(f"[{datetime.now(timezone.utc)}] Intercepted API response: HTTP {api_response.status}", flush=True)
        if api_response.status != 200:
            raise RuntimeError(f"KTU API returned unexpected status {api_response.status}")

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
    