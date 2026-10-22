"""Pinned announcements, student archive, organisation editing and scoping."""
from datetime import datetime, timedelta, timezone

from conftest import PDF

from app.config import settings
from app.models import AuditLog, StoredFile, StudentRecord

DEAN = "dean.it@nalut.edu.ly"
PRES = "president@nalut.edu.ly"


def iso(delta_minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).isoformat()


def me(client, h):
    return client.get("/api/me", headers=h).json()


# ------------------------------------------------------------------ banners

def test_banner_time_window_and_audience(client, as_):
    p = as_(PRES)
    client.post("/api/banners", headers=p, json={"title": "الآن للجميع", "level": "urgent"})
    client.post("/api/banners", headers=p, json={"title": "لاحقاً", "starts_at": iso(60)})
    client.post("/api/banners", headers=p, json={"title": "منتهي", "starts_at": iso(-120), "ends_at": iso(-60)})
    client.post("/api/banners", headers=p, json={"title": "للموظفين", "audience": "staff"})
    titles = [b["title"] for b in client.get("/api/banners", headers=as_("s.ali@nalut.edu.ly")).json()]
    assert "الآن للجميع" in titles
    assert not {"لاحقاً", "منتهي", "للموظفين"} & set(titles)
    assert "للموظفين" in [b["title"] for b in client.get("/api/banners", headers=as_("t.ahmed@nalut.edu.ly")).json()]
    r = client.post("/api/banners", headers=p, json={"title": "خطأ", "starts_at": iso(10), "ends_at": iso(5)})
    assert r.status_code == 400


def test_faculty_banner_scope_and_permissions(client, as_):
    d = as_(DEAN)
    eng = me(client, as_("dean.eng@nalut.edu.ly"))["faculty"]["id"]
    # a faculty admin cannot target another faculty: the banner is forced to their own
    b = client.post("/api/banners", headers=d, json={"title": "إعلان الكلية", "faculty_id": eng}).json()
    assert b["faculty_id"] == me(client, d)["faculty"]["id"]
    assert "إعلان الكلية" in [x["title"] for x in client.get("/api/banners", headers=as_("s.ali@nalut.edu.ly")).json()]
    assert "إعلان الكلية" not in [x["title"] for x in client.get("/api/banners", headers=as_("eng1@nalut.edu.ly")).json()]
    assert client.patch(f"/api/banners/{b['id']}", headers=as_("dean.eng@nalut.edu.ly"), json={"title": "x y"}).status_code == 403
    assert client.post("/api/banners", headers=as_("t.ahmed@nalut.edu.ly"), json={"title": "أستاذ"}).status_code == 403
    assert client.patch(f"/api/banners/{b['id']}", headers=d, json={"is_active": False}).status_code == 200
    assert "إعلان الكلية" not in [x["title"] for x in client.get("/api/banners", headers=as_("s.ali@nalut.edu.ly")).json()]


# ------------------------------------------------------------------ structure & editing

def test_structure_is_scoped_to_own_faculty(client, as_):
    assert len(client.get("/api/org/structure", headers=as_(DEAN)).json()["faculties"]) == 1
    assert len(client.get("/api/org/structure", headers=as_("s.ali@nalut.edu.ly")).json()["faculties"]) == 1
    assert len(client.get("/api/org/structure", headers=as_(PRES)).json()["faculties"]) == 3


def test_edit_term_faculty_department_course(client, as_):
    p = as_(PRES)
    s = client.get("/api/org/structure", headers=p).json()
    term = s["terms"][0]
    r = client.patch(f"/api/org/terms/{term['id']}", headers=p, json={"name": "خريف 2026 (معدل)", "end_date": "2027-01-31"})
    assert r.status_code == 200
    assert client.patch(f"/api/org/terms/{term['id']}", headers=p, json={"end_date": "2020-01-01"}).status_code == 400
    assert client.patch(f"/api/org/terms/{term['id']}", headers=as_(DEAN), json={"name": "x y"}).status_code == 403
    fac = s["faculties"][2]  # economics has a department but no users/courses
    assert client.patch(f"/api/org/faculties/{fac['id']}", headers=p, json={"name": "كلية الاقتصاد والعلوم السياسية"}).status_code == 200
    assert client.delete(f"/api/org/faculties/{fac['id']}", headers=p).status_code == 400  # has a department
    dep = fac["departments"][0]
    assert client.patch(f"/api/org/departments/{dep['id']}", headers=as_(DEAN), json={"name": "x y"}).status_code == 403
    assert client.delete(f"/api/org/departments/{dep['id']}", headers=p).status_code == 200
    assert client.delete(f"/api/org/faculties/{fac['id']}", headers=p).status_code == 200
    it = s["faculties"][0]
    assert client.delete(f"/api/org/faculties/{it['id']}", headers=p).status_code == 400  # has users
    # course edit
    cid = next(c["id"] for c in client.get("/api/courses", headers=as_(DEAN)).json() if c["code"] == "CS201")
    r = client.patch(f"/api/courses/{cid}", headers=as_(DEAN), json={"title": "هياكل البيانات والخوارزميات", "credits": 4})
    assert r.json()["title"] == "هياكل البيانات والخوارزميات"


def test_component_edit_rules(client, as_):
    t = as_("t.ahmed@nalut.edu.ly")
    cid = next(c["id"] for c in client.get("/api/courses", headers=t).json() if c["code"] == "CS101")
    comps = client.get(f"/api/courses/{cid}", headers=t).json()["components"]
    hw = comps[0]  # has scores in demo data
    assert client.patch(f"/api/components/{hw['id']}", headers=t, json={"max_score": 1}).status_code == 400
    assert client.patch(f"/api/components/{hw['id']}", headers=t, json={"name": "الواجبات والأنشطة"}).status_code == 200
    assert client.delete(f"/api/components/{hw['id']}", headers=t).status_code == 400
    new = client.post(f"/api/courses/{cid}/components", headers=t, json={"name": "مشاركة", "max_score": 5}).json()
    assert client.delete(f"/api/components/{new['id']}", headers=t).status_code == 200


# ------------------------------------------------------------------ archive

def test_archive_access_rules(client, as_):
    ali = me(client, as_("s.ali@nalut.edu.ly"))["id"]
    eng_student = me(client, as_("eng1@nalut.edu.ly"))["id"]
    for email in (DEAN, "registrar@nalut.edu.ly", PRES):
        assert client.get(f"/api/archive/students/{ali}", headers=as_(email)).status_code == 200, email
    for email in ("affairs@nalut.edu.ly", "t.ahmed@nalut.edu.ly", "s.ali@nalut.edu.ly", "student@demo2.edu.ly"):
        assert client.get(f"/api/archive/students/{ali}", headers=as_(email)).status_code in (403, 404), email
    assert client.get(f"/api/archive/students/{eng_student}", headers=as_(DEAN)).status_code == 404  # other faculty
    lst = client.get("/api/archive/students", headers=as_(DEAN)).json()
    assert lst["total"] == 12  # IT students only


def test_archive_record_and_documents(client, as_, db):
    d = as_("registrar@nalut.edu.ly")
    ali = me(client, as_("s.ali@nalut.edu.ly"))["id"]
    r = client.put(f"/api/archive/students/{ali}/record", headers=d, json={
        "national_id": "119900012345", "birth_date": "2004-05-01", "guardian_name": "محمد الطاهر",
        "high_school_score": 88.5, "status": "active"})
    assert r.status_code == 200 and r.json()["national_id"] == "119900012345"
    rec = db.query(StudentRecord).filter_by(student_id=ali).one()
    assert "119900012345" not in (rec.national_id_enc or "")  # encrypted at rest
    up = client.post(f"/api/archive/students/{ali}/documents", headers=d,
                     data={"doc_type": "high_school", "title": "شهادة الثانوية"},
                     files={"upload": ("hs.pdf", PDF, "application/pdf")})
    assert up.status_code == 200, up.text
    doc = up.json()
    f = db.get(StoredFile, doc["file"]["id"])
    assert f.encrypted and (settings.storage_dir / f.stored_name).read_bytes() != PDF
    assert client.get(f"/api/archive/documents/{doc['id']}/file", headers=d).content == PDF
    # not reachable through the generic file endpoint, not even by the student
    assert client.get(f"/api/files/{f.id}", headers=as_("s.ali@nalut.edu.ly")).status_code == 404
    bad = client.post(f"/api/archive/students/{ali}/documents", headers=d, data={"doc_type": "photo"},
                      files={"upload": ("x.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert bad.status_code == 400
    assert client.post(f"/api/archive/documents/{doc['id']}/delete", headers=d, json={"reason": ""}).status_code == 422
    assert client.post(f"/api/archive/documents/{doc['id']}/delete", headers=d, json={"reason": "نسخة غير واضحة"}).status_code == 200
    remaining = [x["id"] for x in client.get(f"/api/archive/students/{ali}", headers=d).json()["documents"]]
    assert doc["id"] not in remaining
    actions = {a.action for a in db.query(AuditLog).filter(AuditLog.action.like("archive.%"))}
    assert {"archive.record_updated", "archive.document_added", "archive.document_downloaded",
            "archive.document_deleted", "archive.viewed"} <= actions
    # personal values never land in the audit log
    assert not any("119900012345" in str(a.details) for a in db.query(AuditLog).all())


def test_push_open_marks_read(client, as_):
    s = as_("s.ali@nalut.edu.ly")
    n = client.get("/api/notifications", headers=s).json()["items"][0]
    r = client.post(f"/api/notifications/by-id/{n['id']}/read", headers=s)
    assert r.status_code == 200
    assert client.post(f"/api/notifications/by-id/{n['id']}/read", headers=as_("student2@nalut.edu.ly")).status_code == 404


def test_teacher_moves_own_lecture_times_only(client, as_):
    t = as_("t.ahmed@nalut.edu.ly")
    course = client.get("/api/courses", headers=t).json()[0]
    slots = [{"day": 1, "start": "10:00", "end": "11:30", "room": "قاعة 4"}]
    r = client.patch(f"/api/courses/{course['id']}", headers=t, json={"schedule": slots})
    assert r.status_code == 200, r.text
    assert client.patch(f"/api/courses/{course['id']}", headers=t, json={"title": "اسم آخر"}).status_code == 403
    s = as_("s.ali@nalut.edu.ly")
    assert client.patch(f"/api/courses/{course['id']}", headers=s, json={"schedule": []}).status_code in (403, 404)
