"""End-to-end demo scenario from the project's success criteria."""
from datetime import datetime, timedelta, timezone

from conftest import PDF, nonce

STUDENT = "s.ali@nalut.edu.ly"
TEACHER = "t.ahmed@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"
PRESIDENT = "president@nalut.edu.ly"


def course_id(client, headers, code):
    return next(c["id"] for c in client.get("/api/courses", headers=headers).json() if c["code"] == code)


def test_full_scenario(client, as_):
    # 1. login with different roles
    for email, role in [(STUDENT, "student"), (TEACHER, "teacher"), (DEAN, "faculty_admin"),
                        (PRESIDENT, "university_admin"), ("registrar@nalut.edu.ly", "staff")]:
        assert client.get("/api/me", headers=as_(email)).json()["role"] == role

    # 2. administration sends an announcement that reaches the student app
    r = client.post("/api/notifications", headers=as_(DEAN), json={
        "category": "announcement", "priority": "urgent", "title": "تغيير موعد امتحان", "body": "نُقل امتحان CS101",
        "target_type": "faculty", "target_ids": [client.get("/api/me", headers=as_(DEAN)).json()["faculty"]["id"]],
        "channels": ["inapp", "push", "sms"]})
    assert r.status_code == 200, r.text
    inbox = client.get("/api/notifications", headers=as_(STUDENT)).json()
    assert any(n["title"] == "تغيير موعد امتحان" for n in inbox["items"])

    # 3. teacher creates an assignment, students are notified
    cid = course_id(client, as_(TEACHER), "CS101")
    due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    r = client.post(f"/api/courses/{cid}/assignments", headers=as_(TEACHER),
                    json={"title": "واجب الاختبار", "due_at": due, "max_score": 10})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    assert any(n["title"] == "مهمة جديدة: واجب الاختبار"
               for n in client.get("/api/notifications", headers=as_(STUDENT)).json()["items"])

    # 4. student uploads a file from the phone
    r = client.post(f"/api/assignments/{aid}/submission", headers=as_(STUDENT),
                    data={"final": "true", "note": "الحل"}, files={"upload": ("hw.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["status"] == "submitted"

    # 5. teacher downloads, grades and adds feedback (not yet released)
    file_id = sub["files"][0]["id"]
    assert client.get(f"/api/files/{file_id}", headers=as_(TEACHER)).content == PDF
    r = client.post(f"/api/submissions/{sub['id']}/grade", headers=as_(TEACHER),
                    json={"score": 9, "feedback": "ممتاز", "release": False})
    assert r.status_code == 200, r.text
    mine = client.get(f"/api/assignments/{aid}", headers=as_(STUDENT)).json()
    assert mine["submission"]["score"] is None  # not released yet

    # 6. grade appears to the student once released
    assert client.post(f"/api/assignments/{aid}/release-grades", headers=as_(TEACHER)).json()["released"] == 1
    mine = client.get(f"/api/assignments/{aid}", headers=as_(STUDENT)).json()
    assert mine["submission"]["score"] == 9 and mine["submission"]["feedback"] == "ممتاز"
    assert mine["my_status"] == "reviewed"

    # 7. attendance with a dynamic QR code
    r = client.post("/api/attendance/sessions", headers=as_(TEACHER), json={"course_id": cid, "location": "A101"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    qr = client.get(f"/api/attendance/sessions/{sid}/qr", headers=as_(TEACHER)).json()
    assert qr["image"].startswith("data:image/svg+xml")
    r = client.post("/api/attendance/check-in", headers={**as_(STUDENT), "X-Device-Id": "dev-ali"},
                    data={"payload": qr["payload"], "nonce": nonce()})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "present"

    # 8. administrative report about students, attendance and assignments
    rep = client.get("/api/reports/overview", headers=as_(DEAN)).json()
    assert rep["people"]["students"] > 0 and rep["courses"]
    assert any(c["attendance_rate"] is not None for c in rep["courses"])
    assert any(c["submission_rate"] is not None for c in rep["courses"])
    uni = client.get("/api/reports/overview", headers=as_(PRESIDENT)).json()
    assert len(uni["breakdown"]) == 3  # comparison between faculties

    # 9. access to data outside one's permissions is refused
    other_course = course_id(client, as_("t.salma@nalut.edu.ly"), "IS110")
    assert client.get(f"/api/courses/{other_course}/grades", headers=as_(TEACHER)).status_code == 403
    assert client.get(f"/api/files/{file_id}", headers=as_("student2@nalut.edu.ly")).status_code == 404
