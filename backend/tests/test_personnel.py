"""Staff and faculty members' employment files: access, scope, documents, audit."""
from conftest import PASSWORD

from app.models import AuditLog, User
from test_platform import PRES, platform, uni_id

PDF = b"%PDF-1.4\n% employment file\n"


def uid(db, email):
    return db.query(User).filter_by(email=email).one().id


def test_faculty_and_staff_files(client, as_, db):
    p, dean, t, reg = as_(PRES), as_("dean.it@nalut.edu.ly"), as_("t.ahmed@nalut.edu.ly"), as_("registrar@nalut.edu.ly")
    teacher = uid(db, "t.ahmed@nalut.edu.ly")
    # sections list the right people
    fac = client.get("/api/personnel?section=faculty", headers=p).json()["items"]
    staff = client.get("/api/personnel?section=staff", headers=p).json()["items"]
    assert teacher in [x["id"] for x in fac] and teacher not in [x["id"] for x in staff]
    assert all(x["role"] in ("teacher", "assistant") for x in fac)
    assert all(x["role"] in ("staff", "faculty_admin") for x in staff)
    # the university administration fills the file
    body = {"national_id": "119900112233", "data": {"academic_rank": "assistant_professor", "hire_date": "2015-09-01",
                                                     "general_specialization": "حاسوب", "teaching_load_hours": 12}}
    r = client.put(f"/api/personnel/{teacher}/record", headers=p, json=body)
    assert r.status_code == 200, r.text
    assert client.put(f"/api/personnel/{teacher}/record", headers=p,
                      json={"data": {"academic_rank": "king"}}).status_code == 400
    assert client.put(f"/api/personnel/{teacher}/record", headers=p, json={"data": {"job_title": "x"}}).status_code == 400
    doc = client.post(f"/api/personnel/{teacher}/documents", headers=p, data={"doc_type": "cv"},
                      files={"upload": ("cv.pdf", PDF, "application/pdf")})
    assert doc.status_code == 200, doc.text
    f = client.get(f"/api/personnel/{teacher}", headers=p).json()
    assert f["record"]["national_id"] == "119900112233" and f["record"]["academic_rank"] == "assistant_professor"
    assert f["documents"][0]["type_label"] == "السيرة الذاتية" and f["teaching"]
    # the faculty administration may read (default) but not edit; staff see nothing by default
    assert client.get(f"/api/personnel/{teacher}", headers=dean).status_code == 200
    assert client.put(f"/api/personnel/{teacher}/record", headers=dean, json={"data": {}}).status_code == 404
    assert client.get("/api/personnel?section=staff", headers=reg).status_code == 403
    assert client.get(f"/api/personnel/{teacher}", headers=reg).status_code == 404
    # another faculty's administration does not see this teacher
    assert client.get(f"/api/personnel/{teacher}", headers=as_("dean.eng@nalut.edu.ly")).status_code == 404
    # the teacher reads their own file and documents, never edits it
    mine = client.get("/api/personnel/me", headers=t).json()
    assert mine["record"]["academic_rank"] == "assistant_professor" and mine["can_manage"] is False
    assert client.get(f"/api/personnel/documents/{doc.json()['id']}/file", headers=t).status_code == 200
    assert client.put(f"/api/personnel/{teacher}/record", headers=t, json={"data": {}}).status_code == 404
    # the general file endpoint never serves these documents
    assert client.get(f"/api/files/{doc.json()['file']['id']}", headers=dean).status_code in (403, 404)
    # granted through a permission group, a staff member manages staff files
    act = {**platform(client), "X-Act-As-University": str(uni_id(db))}
    g = client.post("/api/permission-groups", headers=act, json={"name": "شؤون الموظفين",
                                                                 "capabilities": ["staff.view", "staff.manage"]}).json()
    client.put(f"/api/permission-groups/{g['id']}/members", headers=act, json={"user_ids": [uid(db, "registrar@nalut.edu.ly")]})
    other_staff = uid(db, "affairs@nalut.edu.ly")
    assert client.get("/api/personnel?section=staff", headers=reg).status_code == 200
    r = client.put(f"/api/personnel/{other_staff}/record", headers=reg, json={"data": {"job_title": "مسجل"}})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/personnel/{teacher}", headers=reg).status_code == 404  # still not faculty files
    assert client.post(f"/api/personnel/documents/{doc.json()['id']}/delete", headers=p,
                       json={"reason": "نسخة قديمة"}).status_code == 200
    actions = {a.action for a in db.query(AuditLog).all()}
    assert {"personnel.viewed", "personnel.record_updated", "personnel.document_added",
            "personnel.document_downloaded", "personnel.document_deleted"} <= actions
    assert "119900112233" not in str([a.details for a in db.query(AuditLog).all()])
