from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class Attachment(BaseModel):
    name: str
    encrypt_id: str
    fetch_url: str = "https://api.ktu.edu.in/ktu-web-portal-api/anon/getAttachment"
    method: str = "POST"


class Announcement(BaseModel):
    id: str
    title: str
    description_html: str | None = None
    description_text: str | None = None
    date: date
    is_new: bool
    attachments: list[Attachment]
    schemes: list[str] = []
    scraped_at: datetime


class AnnouncementsResponse(BaseModel):
    success: bool
    count: int
    last_updated: datetime
    data: list[Announcement]


class CachedAttachment(BaseModel):
    encrypt_id: str
    filename: str
    content_b64: str


class SyncPayload(BaseModel):
    announcements: list[Announcement]
    x_token: Optional[str] = None
    cached_attachments: Optional[list[CachedAttachment]] = None
