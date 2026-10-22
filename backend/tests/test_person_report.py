"""Simplified per-person reports and who may see them."""
from app.models import User


def uid(db, email):
    return db.query(User).filter_by(email=email).one().id


def test_reports_by_role_and_visibility(client, as_, db):
    s = as_("s.ali@nalut.edu.ly")
    me = client.get(f"/api/reports/person/{uid(db, 's.ali@nalut.edu.ly')}", headers=s).json()
    assert me["kind"] == "student" and me["summary"]["courses"] >= 1
    first = me["courses"][0]
    assert {"absence_percent", "submitted", "due", "alerts"} <= set(first) and first["running_percent"] is None
    # a student cannot see someone else
    assert client.get(f"/api/reports/person/{uid(db, 'student2@nalut.edu.ly')}", headers=s).status_code == 403
    # the teacher sees their student (only shared courses) and the running total
    t = as_("t.ahmed@nalut.edu.ly")
    r = client.get(f"/api/reports/person/{uid(db, 's.ali@nalut.edu.ly')}", headers=t).json()
    assert r["kind"] == "student" and len(r["courses"]) <= len(me["courses"])
    assert client.get(f"/api/reports/person/{uid(db, 'registrar@nalut.edu.ly')}", headers=t).status_code == 403
    p = as_("president@nalut.edu.ly")
    teacher = client.get(f"/api/reports/person/{uid(db, 't.ahmed@nalut.edu.ly')}", headers=p).json()
    assert teacher["kind"] == "teacher" and teacher["summary"]["courses"] >= 1
    staff = client.get(f"/api/reports/person/{uid(db, 'registrar@nalut.edu.ly')}", headers=p).json()
    assert staff["kind"] == "staff" and "requests_handled_30d" in staff["summary"]
    # a faculty admin cannot see another faculty's people
    d = as_("dean.eng@nalut.edu.ly")
    assert client.get(f"/api/reports/person/{uid(db, 's.ali@nalut.edu.ly')}", headers=d).status_code == 403
