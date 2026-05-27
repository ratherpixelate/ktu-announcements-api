from playwright.sync_api import sync_playwright
from datetime import datetime, date, timezone
from app.models import Attachment, Announcement
from bs4 import BeautifulSoup
from app.utils import extract_schemes
import httpx  
import re
import base64

KTU_URL = "https://ktu.edu.in/Menu/announcements"

def parse_date(date_str: str) -> date:
    """Convert date string like '2026-05-18 00:00:00' to a date object."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return datetime.today().date()

def scrape_announcements() -> list[Announcement]:
    """Fetch announcements by intercepting the API call in a real browser."""
    announcements = []
    scraped_at = datetime.now(timezone.utc)

    with sync_playwright() as p:
        # Launch an invisible Chromium browser
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = browser.new_page()

        print("Opening KTU website and waiting for API response...")
        
        # Listen for the specific API response we want
        with page.expect_response(lambda response: "/anon/announcemnts" in response.url) as response_info:
            page.goto(KTU_URL, timeout=60000, wait_until="domcontentloaded")
        
        # Extract the JSON payload directly from the intercepted network traffic!
        api_response = response_info.value
        data = api_response.json()

        x_token = api_response.request.headers.get("x-token")
        print(f"\n=== DEBUG SCRAPER ===")
        print(f"Extracted x-token type: {type(x_token)}")
        print(f"Extracted x-token value: {repr(x_token)[:50]}...\n")

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
                
                #Smart Parser Logic
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

        browser.close()

    return announcements,x_token

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
        # We don't need stream() anymore since it's just a text string response
        resp = await client.post(url, headers=headers, json=payload, timeout=60.0)
        
        if resp.status_code != 200:
            raise Exception(f"KTU API returned {resp.status_code}: {resp.text}")
        
        # 1. Get the raw text response and strip any accidental JSON quotes
        base64_string = resp.text.strip('"')
        
        # 2. Decode the Base64 string back into raw binary PDF bytes
        try:
            pdf_bytes = base64.b64decode(base64_string)
        except Exception as e:
            raise Exception(f"Failed to decode KTU's Base64 response: {str(e)}")
            
        # 3. Final safety check (this will pass now!)
        if not pdf_bytes.startswith(b"%PDF"):
            raise Exception("Decoded bytes do not form a valid PDF.")

        return pdf_bytes
    