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
    date: date
    is_new: bool
    attachments: list[Attachment]
    scraped_at: datetime


class AnnouncementsResponse(BaseModel):
    success: bool
    count: int
    last_updated: datetime
    data: list[Announcement]