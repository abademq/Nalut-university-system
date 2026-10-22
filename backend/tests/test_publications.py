"""Lecture timetables and image announcements."""
from datetime import datetime, timedelta, timezone

from conftest import PDF

from app.models import User

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
PRES = "president@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"


def post(client, h, **fields):
    upload = fields.pop("upload", ("poster.png", PNG, "image/png"))
    return client.post("/api/publications", headers=h, data={k: str(v) for k, v in fields.items()},
                       files={"upload": upload})


def test_publish_target_and_view(client, as_, db):
    p = as_(PRES)
    s = as_("s.ali@nalut.edu.ly")
    ali = db.query(User).filter_by(email="s.ali@nalut.edu.ly").one()
    r = post(client, p, kind="poster", title="معرض التخرج", audience="all", notify="true")
    assert r.status_code == 200, r.text
    poster = r.json()
    assert poster["is_image"] and poster["notified"] is True
    sched = post(client, p, kind="schedule", title="جدول الدفعة", audience="students", cohort=ali.cohort,
                 upload=("table.pdf", PDF, "application/pdf")).json()
    post(client, p, kind="schedule", title="دفعة أخرى", audience="students", cohort="1999")
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    post(client, p, kind="poster", title="لاحقاً", starts_at=later)

    feed = client.get("/api/publications", headers=s).json()
    titles = [x["title"] for x in feed]
    assert "معرض التخرج" in titles and "جدول الدفعة" in titles
    assert "دفعة أخرى" not in titles and "لاحقاً" not in titles
    assert [x["title"] for x in client.get("/api/publications?kind=schedule", headers=s).json()] == ["جدول الدفعة"]
    # the file is served to whoever can see the item, and to no one else
    assert client.get(f"/api/files/{sched['file']['id']}", headers=s).status_code == 200
    teacher = as_("t.ahmed@nalut.edu.ly")
    assert client.get(f"/api/files/{sched['file']['id']}", headers=teacher).status_code in (403, 404)
    # students cannot publish; wrong file types are refused
    assert post(client, s, kind="poster", title="x x").status_code == 403
    assert post(client, p, kind="poster", title="exe", upload=("a.exe", b"MZ....", "application/octet-stream")).status_code == 400


def test_faculty_scope_and_edit(client, as_):
    d = as_(DEAN)
    r = post(client, d, kind="schedule", title="جدول الكلية", faculty_id=999999).json()
    dean_fac = client.get("/api/me", headers=d).json()["faculty"]["id"]
    assert r["faculty_id"] == dean_fac  # forced to the dean's faculty
    eng = as_("dean.eng@nalut.edu.ly")
    assert "جدول الكلية" not in [x["title"] for x in client.get("/api/publications", headers=eng).json()]
    assert client.patch(f"/api/publications/{r['id']}", headers=eng, json={"is_active": False}).status_code == 404
    assert client.patch(f"/api/publications/{r['id']}", headers=d, json={"is_active": False}).json()["is_active"] is False
    assert client.delete(f"/api/publications/{r['id']}", headers=d).status_code == 200
