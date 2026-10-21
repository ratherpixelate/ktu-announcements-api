from fastapi.testclient import TestClient
from datetime import datetime, timezone, date
from app.main import app
from app import cache
from app.models import Announcement, Attachment

client = TestClient(app)

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "KTU Announcements API" in response.text
    assert "Camoufox" in response.text

def test_favicon_endpoint():
    response = client.get("/favicon.ico")
    assert response.status_code == 204

def test_health_check():
    cache.state["announcements"] = []
    cache.state["last_updated"] = datetime.now(timezone.utc)
    cache.state["x_token"] = "sample_test_token_12345"
    cache.state["last_error"] = None

    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=60"
    data = response.json()
    assert data["status"] == "online"
    assert data["has_token"] is True
    assert "token_preview" not in data

def test_get_announcements_empty():
    cache.state["announcements"] = []
    cache.state["last_updated"] = None
    response = client.get("/announcements")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=300"
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 0
    assert data["last_updated"] is None
    assert data["data"] == []

def test_get_announcements_with_data_and_filters():
    ann1 = Announcement(
        id="101",
        title="Exam schedule",
        description_text="Details for 2019 scheme",
        date=date(2026, 5, 10),
        is_new=True,
        attachments=[],
        schemes=["2019"],
        scraped_at=datetime.now(timezone.utc)
    )
    ann2 = Announcement(
        id="102",
        title="General circular",
        description_text="General information",
        date=date(2026, 5, 11),
        is_new=False,
        attachments=[],
        schemes=["General"],
        scraped_at=datetime.now(timezone.utc)
    )
    cache.state["announcements"] = [ann1, ann2]

    # Test limit filter
    res = client.get("/announcements?limit=1")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1

    # Test new_only filter
    res = client.get("/announcements?new_only=true")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1
    assert res.json()["data"][0]["id"] == "101"

    # Test scheme filter (includes General)
    res = client.get("/announcements?scheme=2019")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 2

    # Test scheme filter with unmatched scheme (only General matches)
    res_none = client.get("/announcements?scheme=9999")
    assert res_none.status_code == 200
    assert len(res_none.json()["data"]) == 1
    assert res_none.json()["data"][0]["id"] == "102"

def test_get_single_announcement():
    ann = Announcement(
        id="999",
        title="Specific Notice",
        date=date(2026, 5, 10),
        is_new=False,
        attachments=[],
        schemes=["General"],
        scraped_at=datetime.now(timezone.utc)
    )
    cache.state["announcements"] = [ann]

    res = client.get("/announcements/999")
    assert res.status_code == 200
    assert res.json()["id"] == "999"

    res_404 = client.get("/announcements/000")
    assert res_404.status_code == 404

def test_sync_endpoint_unauthorized():
    res = client.post("/api/sync", json={"announcements": []}, headers={"X-Sync-Secret": "wrong"})
    assert res.status_code == 403

def test_sync_endpoint_success(monkeypatch):
    monkeypatch.setenv("SYNC_SECRET", "super_secret_123")
    payload = {
        "announcements": [
            {
                "id": "777",
                "title": "Synced Notice",
                "date": "2026-05-12",
                "is_new": True,
                "attachments": [],
                "schemes": ["2019"],
                "scraped_at": "2026-05-12T10:00:00Z"
            }
        ],
        "x_token": "token_abc"
    }
    res = client.post("/api/sync", json=payload, headers={"X-Sync-Secret": "super_secret_123"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["synced_items"] == 1
    assert cache.state["x_token"] == "token_abc"
    assert len(cache.state["announcements"]) == 1
    assert cache.state["announcements"][0].id == "777"

def test_sync_and_download_cached_attachment(monkeypatch):
    import base64
    monkeypatch.setenv("SYNC_SECRET", "super_secret_123")
    sample_pdf = b"%PDF-1.4 sample pdf content for testing"
    payload = {
        "announcements": [
            {
                "id": "888",
                "title": "Notice With Attachment",
                "date": "2026-05-15",
                "is_new": True,
                "attachments": [
                    {
                        "name": "Exam Schedule",
                        "encrypt_id": "test_enc_123"
                    }
                ],
                "schemes": [],
                "scraped_at": "2026-05-15T10:00:00Z"
            }
        ],
        "x_token": "token_xyz",
        "cached_attachments": [
            {
                "encrypt_id": "test_enc_123",
                "filename": "Exam Schedule.pdf",
                "content_b64": base64.b64encode(sample_pdf).decode("ascii")
            }
        ]
    }
    res = client.post("/api/sync", json=payload, headers={"X-Sync-Secret": "super_secret_123"})
    assert res.status_code == 200
    assert res.json()["cached_attachments"] == 1

    # Verify download serves directly from cache without 502 or external calls
    dl_res = client.get("/download/test_enc_123")
    assert dl_res.status_code == 200
    assert dl_res.content == sample_pdf
    assert dl_res.headers["content-type"] == "application/pdf"
    assert dl_res.headers.get("cache-control") == "public, max-age=86400"
    assert 'filename="Exam Schedule.pdf"' in dl_res.headers["content-disposition"]

def test_refresh_endpoint_unauthorized(monkeypatch):
    monkeypatch.setenv("SYNC_SECRET", "super_secret_123")
    res = client.get("/refresh")
    assert res.status_code == 200
    assert res.json()["mode"] == "decoupled"
    assert res.json()["auth_required"] is True

def test_refresh_endpoint_cooldown(monkeypatch):
    monkeypatch.setenv("SYNC_SECRET", "super_secret_123")
    # Simulate a dispatch that happened 1 minute ago (within 10-minute cooldown)
    cache.state["last_dispatch"] = datetime.now(timezone.utc)
    res = client.get("/refresh?secret=super_secret_123")
    assert res.status_code == 200
    assert res.json()["status"] == "cooldown"
    assert "cooldown_remaining_seconds" in res.json()
    cache.state["last_dispatch"] = None

def test_attachment_internal_fields_excluded():
    ann = Announcement(
        id="555",
        title="Notice with attachment",
        date=date(2026, 5, 20),
        is_new=False,
        attachments=[
            Attachment(name="Circular", encrypt_id="enc_abc")
        ],
        schemes=[],
        scraped_at=datetime.now(timezone.utc)
    )
    cache.state["announcements"] = [ann]

    res = client.get("/announcements/555")
    assert res.status_code == 200
    att = res.json()["attachments"][0]
    assert att["name"] == "Circular"
    assert att["encrypt_id"] == "enc_abc"
    assert "fetch_url" not in att
    assert "method" not in att
