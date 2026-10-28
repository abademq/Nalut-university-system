"""Closing the platform from the server (sudo nus-close / nus-open)."""
import time

from app import closed
from app.config import settings


def _set(path, text):
    settings.closed_file = path
    if text is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(text, encoding="utf-8")
    closed._cache = (time.monotonic() - 5, None)  # forget the last check


def test_closed_platform_shows_the_notice_everywhere(client, tmp_path):
    original = settings.closed_file
    flag = tmp_path / "closed"
    try:
        _set(flag, "صيانة حتى الساعة 10 مساءً")
        page = client.get("/")
        assert page.status_code == 503 and "المنصة مغلقة" in page.text and "صيانة حتى الساعة 10" in page.text
        api = client.post("/api/auth/login", json={"identifier": "s.ali@nalut.edu.ly", "password": "x"})
        assert api.status_code == 503 and api.json() == {"detail": "صيانة حتى الساعة 10 مساءً", "closed": True}
        assert client.get("/api/health").json()["closed"] is True  # monitoring still answers
        assert client.get("/static/css/app.css").status_code == 200  # the notice keeps its styles
        _set(flag, "")
        assert closed.DEFAULT_MESSAGE in client.get("/api/me").json()["detail"]
        _set(flag, None)
        assert client.get("/api/health").json()["closed"] is False
        assert client.get("/").status_code == 200
    finally:
        settings.closed_file = original
        closed._cache = (0.0, None)
