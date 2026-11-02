"""Deleting an account for good: directly by the deciders, or on request from a head of department
or an employee; everything belonging to the account goes, the audit log keeps the record."""
from app.models import AccountDeletionRequest, AttendanceRecord, AuditLog, Enrollment, GradeEntry, Submission, User

PRES = "president@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"


def test_request_then_faculty_administration_deletes(client, as_, db):
    ali = db.query(User).filter_by(email="s.ali@nalut.edu.ly").one()
    sid, name = ali.id, ali.full_name
    reg = as_("registrar@nalut.edu.ly")  # an employee: may ask, not delete
    assert client.post(f"/api/users/{sid}/delete", headers=reg, json={"reason": "خطأ في التسجيل"}).status_code == 403
    r = client.post(f"/api/users/{sid}/deletion-requests", headers=reg, json={"reason": "حساب مكرر بالخطأ"})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/users/{sid}/deletion-requests", headers=reg, json={"reason": "مرة ثانية"}).status_code == 400
    d = as_(DEAN)
    pending = [x for x in client.get("/api/account-deletions", headers=d).json() if x["status"] == "pending"]
    assert pending and pending[0]["can_decide"] and pending[0]["target"]["full_name"] == name
    assert any(x["id"] == r.json()["id"] for x in client.get("/api/account-deletions", headers=reg).json())
    ok = client.post(f"/api/account-deletions/{pending[0]['id']}", headers=d, json={"approve": True})
    assert ok.status_code == 200 and ok.json()["deleted"]
    db.expire_all()
    assert db.get(User, sid) is None
    for model, col in ((Enrollment, Enrollment.student_id), (Submission, Submission.student_id),
                       (GradeEntry, GradeEntry.student_id), (AttendanceRecord, AttendanceRecord.user_id)):
        assert db.query(model).filter(col == sid).count() == 0
    log = db.query(AuditLog).filter_by(action="user.deleted", target_id=str(sid)).one()
    assert log.details["name"] == name and log.details["reason"] == "حساب مكرر بالخطأ"
    assert db.query(AccountDeletionRequest).one().status == "approved"
    assert client.get("/api/audit/verify", headers=as_(PRES)).json()["ok"]


def test_university_only_option_and_rejection(client, as_, db):
    p = as_(PRES)
    cur = client.get("/api/settings", headers=p).json()["effective"]["accounts"]
    assert client.put("/api/settings", headers=p, json={"settings": {"accounts": {**cur, "deletion_approver": "university"}}}).status_code == 200
    st = db.query(User).filter_by(email="student2@nalut.edu.ly").one()
    d = as_(DEAN)
    assert client.post(f"/api/users/{st.id}/delete", headers=d, json={"reason": "طلب الطالب"}).status_code == 403
    req = client.post(f"/api/users/{st.id}/deletion-requests", headers=d, json={"reason": "طلب الطالب"}).json()
    assert client.post(f"/api/account-deletions/{req['id']}", headers=d, json={"approve": True}).status_code == 403
    no = client.post(f"/api/account-deletions/{req['id']}", headers=p, json={"approve": False, "note": "يبقى"})
    assert no.status_code == 200
    db.expire_all()
    assert db.get(User, st.id) is not None
    assert client.post(f"/api/users/{st.id}/delete", headers=p, json={"reason": "بقرار الإدارة"}).json()["deleted"]
