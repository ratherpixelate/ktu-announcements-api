from playwright.sync_api import sync_playwright
from datetime import datetime, date
from app.models import Attachment, Announcement

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
    scraped_at = datetime.utcnow()

    with sync_playwright() as p:
        # Launch an invisible Chromium browser
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Opening KTU website and waiting for API response...")
        
        # Listen for the specific API response we want
        with page.expect_response(lambda response: "/anon/announcemnts" in response.url) as response_info:
            page.goto(KTU_URL)
        
        # Extract the JSON payload directly from the intercepted network traffic!
        api_response = response_info.value
        data = api_response.json()

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

                announcement = Announcement(
                    id=str(item["id"]),
                    title=item.get("subject", ""),
                    date=parse_date(item.get("announcementDate", "")),
                    is_new=item.get("status") == 1,
                    attachments=attachments,
                    scraped_at=scraped_at
                )
                announcements.append(announcement)

        browser.close()

    return announcements