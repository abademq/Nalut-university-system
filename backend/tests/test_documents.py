"""Official documents: issued with a frozen snapshot, checked by their QR, revocable."""
from app.models import IssuedDocument

STUDENT = "s.ali@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"
PRES = "president@nalut.edu.ly"
TEACHER = "t.ahmed@nalut.edu.ly"


def _sid(db):
    from app.models import User

    return db.query(User).filter_by(email=STUDENT).one().id


def test_issue_print_and_verify_a_transcript(client, as_, db):
    sid = _sid(db)
    assert client.post("/api/documents", headers=as_(TEACHER), json={"student_id": sid, "kind": "transcript"}).status_code == 403
    r = client.post("/api/documents", headers=as_(DEAN), json={"student_id": sid, "kind": "transcript",
                                                                "addressee": "إلى السفارة"})
    assert r.status_code == 200, r.text
    d = r.json()
    page = client.get(f"/api/documents/{d['id']}/html", headers=as_(STUDENT))
    assert page.status_code == 200 and "كشف درجات" in page.text and f"/verify/{d['code']}" in page.text
    assert "unsafe-inline" in page.headers["content-security-policy"] and "script-src" not in page.headers["content-security-policy"]
    link = client.post(f"/api/documents/{d['id']}/link", headers=as_(DEAN)).json()["url"]
    assert client.get(link).status_code == 200  # opens in a new tab without the token
    assert client.get(link[:-3] + "xxx").status_code == 410
    v = client.get(f"/api/verify/{d['code']}").json()  # public, no account
    assert v["valid"] and v["kind"] == "كشف درجات" and v["addressee"] == "إلى السفارة"
    assert "وثيقة صحيحة" in client.get(f"/verify/{d['code']}").text
    assert client.get("/api/verify/not-a-real-code").status_code == 404
    # grades changing later do not change the paper: the snapshot is what was issued
    doc = db.get(IssuedDocument, d["id"])
    assert doc.snapshot["name"] and len(doc.content_hash) == 64
    r = client.post(f"/api/documents/{d['id']}/revoke", headers=as_(DEAN), json={"reason": "صدرت بخطأ"})
    assert r.status_code == 200
    v = client.get(f"/api/verify/{d['code']}").json()
    assert not v["valid"] and v["revoked"]
    assert [x["id"] for x in client.get("/api/documents", headers=as_(STUDENT)).json()] == [d["id"]]


def test_student_self_issue_only_when_allowed(client, as_):
    h = as_(STUDENT)
    assert client.post("/api/documents", headers=h, json={"kind": "enrollment"}).status_code == 403
    p = as_(PRES)
    cur = client.get("/api/settings", headers=p).json()["effective"]["documents"]
    client.put("/api/settings", headers=p, json={"settings": {"documents": {**cur, "student_self_enrollment": True}}})
    d = client.post("/api/documents", headers=h, json={"kind": "enrollment"}).json()
    assert d["self_issued"] and d["kind_label"] == "إفادة قيد"
    assert client.post("/api/documents", headers=h, json={"kind": "transcript"}).status_code == 403
    assert "بطلب الطالب" in client.get(f"/api/documents/{d['id']}/html", headers=h).text
