"""The public Android download page."""
import json


def test_download_page_without_and_with_an_apk(client, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "app_download_dir", tmp_path)
    r = client.get("/download")
    assert r.status_code == 200 and "غير متوفر بعد" in r.text
    assert client.get("/download/nalut-university.apk").status_code == 404
    (tmp_path / "nalut-university.apk").write_bytes(b"PK\x03\x04" + b"\x00" * 2048)
    (tmp_path / "app.json").write_text(json.dumps({"commit": "abcdef1234567", "sha256": "f" * 64,
                                                   "updated": "2026-10-28T10:00"}))
    r = client.get("/download")
    assert "تحميل التطبيق" in r.text and "abcdef1" in r.text and "style=" not in r.text
    r = client.get("/download/nalut-university.apk")
    assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.android.package-archive"
    assert r.content.startswith(b"PK")
