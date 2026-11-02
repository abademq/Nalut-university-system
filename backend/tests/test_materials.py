"""Course materials repository: staff publish, students' files wait for review, faculty reads."""
STUDENT = "s.ali@nalut.edu.ly"
TEACHER = "t.ahmed@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _up(client, h, **data):
    base = {"code": "CS101", "category": "lecture", "title": "المحاضرة الأولى"}
    return client.post("/api/materials", headers=h, data={**base, **data},
                       files={"file": ("lec1.pdf", PDF, "application/pdf")})


def test_teacher_publishes_and_students_read(client, as_):
    r = _up(client, as_(TEACHER))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["status"] == "published" and not m["by_student"]
    h = as_(STUDENT)
    courses = client.get("/api/materials/courses", headers=h).json()
    cs = next(c for c in courses if c["code"] == "CS101")
    assert cs["files"] == 1 and cs["mine"] and cs["pending"] is None
    rows = client.get("/api/materials?code=CS101", headers=h).json()
    assert [x["id"] for x in rows] == [m["id"]]
    d = client.get(f"/api/materials/{m['id']}/download", headers=h)
    assert d.status_code == 200 and d.content == PDF
    assert client.get("/api/materials?code=CS101", headers=as_(TEACHER)).json()[0]["downloads"] == 1


def test_student_summary_waits_for_review_then_is_credited(client, as_):
    h = as_(STUDENT)
    r = _up(client, h, category="summary", title="ملخص الفصل الأول")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["status"] == "pending" and m["by_student"]
    queue = client.get("/api/materials/pending", headers=as_(TEACHER)).json()
    assert [x["id"] for x in queue] == [m["id"]]
    assert client.post(f"/api/materials/{m['id']}/review", headers=as_(TEACHER), json={"approve": False}).status_code == 400
    r = client.post(f"/api/materials/{m['id']}/review", headers=as_(TEACHER), json={"approve": True}).json()
    assert r["status"] == "published" and r["uploader"]
    # the student cannot remove a published summary alone; the teacher can
    assert client.delete(f"/api/materials/{m['id']}", headers=h).status_code == 403
    assert client.delete(f"/api/materials/{m['id']}", headers=as_(TEACHER)).status_code == 200


def test_limits_on_student_uploads(client, as_):
    h = as_(STUDENT)
    assert _up(client, h, code="NOPE").status_code == 404
    p = as_("president@nalut.edu.ly")
    cur = client.get("/api/settings", headers=p).json()["effective"]["materials"]
    client.put("/api/settings", headers=p, json={"settings": {"materials": {**cur, "max_pending_per_student": 1}}})
    assert _up(client, h, category="summary").status_code == 200
    assert _up(client, h, category="summary").status_code == 400
    client.put("/api/settings", headers=p, json={"settings": {"materials": {**cur, "student_uploads": False}}})
    assert _up(client, h, category="summary").status_code == 403
