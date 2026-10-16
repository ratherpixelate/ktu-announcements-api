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

def test_health_check():
    cache.state["announcements"] = []
    cache.state["last_updated"] = datetime.now(timezone.utc)
    cache.state["x_token"] = "sample_test_token_12345"
    cache.state["last_error"] = None

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["has_token"] is True
    assert data["token_preview"] == "sample_test_tok"

def test_get_announcements_empty():
    cache.state["announcements"] = []
    response = client.get("/announcements")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 0
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
