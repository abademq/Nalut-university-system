"""The complaints box: routing to the faculty or the university, anonymity, replies."""
from app.models import AuditLog

STUDENT = "s.ali@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"
PRES = "president@nalut.edu.ly"
TEACHER = "t.ahmed@nalut.edu.ly"


def _send(client, h, **data):
    base = {"category": "services", "subject": "انقطاع الإنترنت", "body": "الإنترنت في المعمل مقطوع منذ أسبوع."}
    return client.post("/api/complaints", headers=h, data={**base, **data})


def test_complaint_reaches_the_faculty_and_the_author_follows_it(client, as_):
    h = as_(STUDENT)
    r = _send(client, h)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["ref"].startswith("C-") and c["status"] == "new" and c["author"]["full_name"]
    inbox = client.get("/api/complaints?box=inbox", headers=as_(DEAN)).json()
    assert any(x["id"] == c["id"] for x in inbox)
    assert client.get("/api/complaints?box=inbox", headers=as_(TEACHER)).status_code == 403
    assert client.get(f"/api/complaints/{c['id']}", headers=as_(TEACHER)).status_code == 404
    d = client.post(f"/api/complaints/{c['id']}/replies", headers=as_(DEAN),
                    json={"body": "تم إبلاغ قسم الشبكات", "status": "resolved"}).json()
    assert d["status"] == "resolved" and d["replies"][0]["author"] == "الإدارة"
    assert client.post(f"/api/complaints/{c['id']}/replies", headers=h, json={"body": "شكراً"}).status_code == 400
    assert client.post(f"/api/complaints/{c['id']}/replies", headers=h,
                       json={"body": "x x", "status": "resolved"}).status_code == 403
    assert client.get("/api/complaints", headers=h).json()[0]["status"] == "resolved"


def test_anonymous_complaint_hides_the_name_everywhere(client, as_, db):
    h = as_(STUDENT)
    c = _send(client, h, anonymous="true", category="conduct", subject="سوء معاملة").json()
    seen = client.get(f"/api/complaints/{c['id']}", headers=as_(DEAN)).json()
    assert seen["author"] is None and seen["anonymous"]
    assert client.get(f"/api/complaints/{c['id']}", headers=h).json()["author"]  # the author still sees it as theirs
    log = db.query(AuditLog).filter_by(action="complaint.submitted", target_id=str(c["id"])).one()
    assert log.actor_id is None and log.ip is None


def test_sensitive_or_chosen_complaints_go_to_the_university(client, as_):
    h = as_(STUDENT)
    c = _send(client, h, category="harassment", subject="إساءة").json()
    assert c["to"] == "إدارة الجامعة"
    assert not any(x["id"] == c["id"] for x in client.get("/api/complaints?box=inbox", headers=as_(DEAN)).json())
    assert any(x["id"] == c["id"] for x in client.get("/api/complaints?box=inbox", headers=as_(PRES)).json())
    c2 = _send(client, h, to_university="true", subject="عن إدارة الكلية").json()
    assert c2["to"] == "إدارة الجامعة"
