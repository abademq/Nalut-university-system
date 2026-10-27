"""Grades workflow, imports, files, notifications and messaging."""
import io
import zipfile

from conftest import PDF

TEACHER = "t.ahmed@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"


def cid(client, h, code):
    return next(c["id"] for c in client.get("/api/courses", headers=h).json() if c["code"] == code)


def test_results_workflow_and_audit(client, as_):
    t, dean = as_(TEACHER), as_(DEAN)
    c = cid(client, t, "CS101")
    g = client.get(f"/api/courses/{c}/grades", headers=t).json()
    st, comp = g["students"][0], g["components"][-1]  # final exam: not yet marked in the demo data
    r = client.put(f"/api/courses/{c}/grades", headers=t,
                   json={"entries": [{"student_id": st["id"], "component_id": comp["id"], "score": 15}]})
    assert r.status_code == 200
    # changing an existing grade needs a reason
    r = client.put(f"/api/courses/{c}/grades", headers=t,
                   json={"entries": [{"student_id": st["id"], "component_id": comp["id"], "score": 17}]})
    assert r.status_code == 400
    r = client.put(f"/api/courses/{c}/grades", headers=t, json={
        "entries": [{"student_id": st["id"], "component_id": comp["id"], "score": 17}], "reason": "خطأ في الرصد"})
    assert r.status_code == 200
    hist = client.get(f"/api/courses/{c}/grades/history", headers=t).json()
    assert hist[0]["reason"] == "خطأ في الرصد" and hist[0]["old"] == 15
    # out of range
    r = client.put(f"/api/courses/{c}/grades", headers=t,
                   json={"entries": [{"student_id": st["id"], "component_id": comp["id"], "score": 999}], "reason": "x y z"})
    assert r.status_code == 400

    assert client.post(f"/api/courses/{c}/results/submit", headers=t, json={}).status_code == 200
    # teacher cannot approve or publish
    assert client.post(f"/api/courses/{c}/results/approve", headers=t, json={}).status_code == 403
    assert client.post(f"/api/courses/{c}/results/publish", headers=dean, json={}).status_code == 400  # not approved
    # locked while awaiting approval
    assert client.put(f"/api/courses/{c}/grades", headers=t, json={"entries": []}).status_code == 400
    assert client.post(f"/api/courses/{c}/results/approve", headers=dean, json={}).status_code == 200
    s = as_("s.ali@nalut.edu.ly")
    assert not next(x for x in client.get("/api/me/grades", headers=s).json() if x["course"]["id"] == c)["published"]
    assert client.post(f"/api/courses/{c}/results/publish", headers=dean, json={}).status_code == 200
    assert next(x for x in client.get("/api/me/grades", headers=s).json() if x["course"]["id"] == c)["published"]
    actions = [a["action"] for a in client.get("/api/audit?action=results", headers=dean).json()]
    assert {"results.submitted", "results.approved", "results.published"} <= set(actions)


def test_grade_import_validates_before_commit(client, as_):
    t = as_(TEACHER)
    c = cid(client, t, "CS101")
    bad = "student_number,واجبات,الامتحان النصفي\n2023001,15,18\n2023011,10,10\n2023002,abc,10\n2023003,50,10\n"
    r = client.post(f"/api/courses/{c}/grades/import", headers=t, files={"upload": ("g.csv", bad.encode(), "text/csv")})
    body = r.json()
    assert not body["can_commit"] and len(body["errors"]) == 3  # not enrolled, non-numeric, out of range
    assert client.post(f"/api/grade-imports/{body['id']}/commit", headers=t).status_code == 400
    good = "student_number,واجبات,الامتحان النصفي\n2023001,15,18\n٢٠٢٣٠٠٢,12.5,10\n"
    r = client.post(f"/api/courses/{c}/grades/import", headers=t, files={"upload": ("g.csv", good.encode(), "text/csv")})
    assert r.json()["can_commit"], r.json()
    assert client.post(f"/api/grade-imports/{r.json()['id']}/commit", headers=t).json()["changed"] >= 3


def test_xlsx_import(client, as_):
    from openpyxl import Workbook
    t = as_(TEACHER)
    c = cid(client, t, "CS101")
    wb = Workbook()
    ws = wb.active
    ws.append(["student_number", "الامتحان النهائي"])
    ws.append(["2023004", 55])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/courses/{c}/grades/import", headers=t, files={"upload": ("g.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.json()["can_commit"], r.json()


def _assignment(client, as_):
    t = as_(TEACHER)
    c = cid(client, t, "CS101")
    return client.post(f"/api/courses/{c}/assignments", headers=t,
                       json={"title": "رفع ملفات", "due_at": "2099-01-01T00:00:00Z", "max_file_mb": 1,
                             "allowed_extensions": ["pdf", "docx", "png"]}).json()["id"]


def test_upload_validation(client, as_):
    aid = _assignment(client, as_)
    s = as_("s.ali@nalut.edu.ly")

    def up(name, data):
        return client.post(f"/api/assignments/{aid}/submission", headers=s, data={"final": "true"},
                           files={"upload": (name, data, "application/pdf")})

    assert up("virus.exe", b"MZ\x90\x00").status_code == 400  # extension not allowed
    assert up("fake.pdf", b"MZ\x90\x00" + b"x" * 50).status_code == 400  # executable disguised as pdf
    assert up("fake.png", PDF).status_code == 400  # content does not match extension
    assert up("big.pdf", b"%PDF-" + b"0" * (1024 * 1024 + 10)).status_code == 413
    macro = io.BytesIO()
    with zipfile.ZipFile(macro, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", "<x/>")
        z.writestr("word/vbaProject.bin", "macro")
    assert up("macro.docx", macro.getvalue()).status_code == 400
    assert up("ok.pdf", PDF).status_code == 200


def test_late_and_resubmission_versions(client, as_):
    aid = _assignment(client, as_)
    s = as_("s.ali@nalut.edu.ly")
    client.post(f"/api/assignments/{aid}/submission", headers=s, data={"final": "false"},
                files={"upload": ("v1.pdf", PDF, "application/pdf")})
    assert client.get(f"/api/assignments/{aid}", headers=s).json()["my_status"] == "in_progress"
    r = client.post(f"/api/assignments/{aid}/submission", headers=s, data={"final": "true"},
                    files={"upload": ("v2.pdf", PDF, "application/pdf")})
    assert r.json()["version"] == 2 and len(r.json()["files"]) == 2
    hist = client.get(f"/api/submissions/{r.json()['id']}/history", headers=s).json()
    assert [h["action"] for h in hist] == ["saved", "submitted"]


def test_notification_authority(client, as_):
    t = as_(TEACHER)
    c = cid(client, t, "CS101")
    # teachers cannot issue official warnings
    r = client.post("/api/notifications", headers=t, json={"category": "official_warning", "title": "تحذير",
                    "body": "تحذير رسمي", "target_type": "course", "target_ids": [c]})
    assert r.status_code == 403
    # teachers cannot address the whole university or another course
    r = client.post("/api/notifications", headers=t, json={"category": "announcement", "title": "عام",
                    "body": "إعلان", "target_type": "university", "target_ids": []})
    assert r.status_code == 403
    is110 = cid(client, as_("t.salma@nalut.edu.ly"), "IS110")
    r = client.post("/api/notifications", headers=t, json={"category": "announcement", "title": "عام",
                    "body": "إعلان", "target_type": "course", "target_ids": [is110]})
    assert r.status_code == 403
    # faculty admin can warn a student of the faculty
    student = client.get("/api/me", headers=as_("student9@nalut.edu.ly")).json()["id"]
    r = client.post("/api/notifications", headers=as_(DEAN), json={
        "category": "official_warning", "priority": "urgent", "title": "إنذار أكاديمي", "body": "تجاوز حد الغياب",
        "target_type": "user", "target_ids": [student], "channels": ["inapp", "sms"]})
    assert r.status_code == 200 and r.json()["recipients"] == 1
    assert any(a["action"] == "warning.issued" for a in client.get("/api/audit", headers=as_(DEAN)).json())
    # notification settings belong to the administration: users cannot mute anything
    r = client.put("/api/me/notification-prefs", headers=as_("s.ali@nalut.edu.ly"),
                   json={"push": False, "muted_categories": ["announcement"]})
    assert r.status_code == 403


def test_scheduled_notification(client, as_):
    from app import worker
    r = client.post("/api/notifications", headers=as_(DEAN), json={
        "category": "announcement", "title": "لاحقاً", "body": "مجدول", "target_type": "faculty",
        "target_ids": [client.get("/api/me", headers=as_(DEAN)).json()["faculty"]["id"]],
        "scheduled_at": "2000-01-01T00:00:00Z"})
    assert r.json()["status"] == "sent"  # past dates are sent immediately
    r = client.post("/api/notifications", headers=as_(DEAN), json={
        "category": "announcement", "title": "مستقبلاً", "body": "مجدول", "target_type": "faculty",
        "target_ids": [client.get("/api/me", headers=as_(DEAN)).json()["faculty"]["id"]],
        "scheduled_at": "2099-01-01T00:00:00Z"})
    assert r.json()["status"] == "scheduled"
    worker.run_once()
    sent = {n["title"]: n["status"] for n in client.get("/api/notifications/sent", headers=as_(DEAN)).json()}
    assert sent["مستقبلاً"] == "scheduled"


def test_messaging_policy(client, as_):
    s = as_("s.ali@nalut.edu.ly")
    contacts = client.get("/api/contacts", headers=s).json()
    assert {c["role"] for c in contacts} <= {"teacher", "assistant"}
    teacher_id = client.get("/api/me", headers=as_(TEACHER)).json()["id"]
    salma = client.get("/api/me", headers=as_("t.salma@nalut.edu.ly")).json()["id"]  # does not teach this student
    other_student = client.get("/api/me", headers=as_("student2@nalut.edu.ly")).json()["id"]
    assert client.post("/api/conversations", headers=s, json={"recipient_ids": [salma], "subject": "سؤال",
                                                               "body": "مرحبا"}).status_code == 403
    assert client.post("/api/conversations", headers=s, json={"recipient_ids": [other_student], "subject": "سؤال",
                                                               "body": "مرحبا"}).status_code == 403
    r = client.post("/api/conversations", headers=s, json={"recipient_ids": [teacher_id], "subject": "سؤال",
                                                           "body": "مرحبا"})
    assert r.status_code == 200
    conv = r.json()["id"]
    assert client.get(f"/api/conversations/{conv}/messages", headers=as_("student2@nalut.edu.ly")).status_code == 404
    msgs = client.get(f"/api/conversations/{conv}/messages", headers=as_(TEACHER)).json()["messages"]
    r = client.post(f"/api/messages/{msgs[0]['id']}/report", headers=as_(TEACHER), json={"reason": "محتوى غير لائق"})
    assert r.status_code == 200
    reports = client.get("/api/message-reports", headers=as_(DEAN)).json()
    assert client.post(f"/api/message-reports/{reports[0]['id']}", headers=as_(DEAN), json={"action": "hide"}).status_code == 200
    body = client.get(f"/api/conversations/{conv}/messages", headers=s).json()["messages"][0]["body"]
    assert "أُخفيت" in body


def test_service_request_flow(client, as_):
    s = as_("s.ali@nalut.edu.ly")
    r = client.post("/api/requests", headers=s, data={"type": "transcript", "subject": "كشف درجات"})
    rid = r.json()["id"]
    reg = as_("registrar@nalut.edu.ly")
    assert client.post(f"/api/requests/{rid}/actions", headers=reg, json={"action": "rejected"}).status_code == 400
    r = client.post(f"/api/requests/{rid}/actions", headers=reg,
                    json={"action": "needs_documents", "comment": "أرفق صورة البطاقة"})
    assert r.json()["status"] == "needs_documents"
    r = client.post(f"/api/requests/{rid}/documents", headers=s, files={"upload": ("id.pdf", PDF, "application/pdf")})
    assert r.json()["status"] == "in_review"
    r = client.post(f"/api/requests/{rid}/actions", headers=reg, json={"action": "approved"})
    assert r.json()["status"] == "approved"
    titles = [n["title"] for n in client.get("/api/notifications", headers=s).json()["items"]]
    assert any("معتمد" in t for t in titles)
    assert client.post(f"/api/requests/{rid}/actions", headers=as_("affairs@nalut.edu.ly"),
                       json={"action": "comment", "comment": "x"}).status_code == 404


def test_reports(client, as_):
    t = as_(TEACHER)
    risk = client.get("/api/reports/at-risk", headers=t).json()
    assert any(r["student"]["code"] == "2023009" for r in risk)
    rows = client.get("/api/reports/attendance?period=week", headers=t).json()
    assert rows and all("rate" in r for r in rows)
    csv = client.get("/api/reports/attendance?format=csv", headers=as_(DEAN))
    assert csv.headers["content-type"].startswith("text/csv")
    assert client.get("/api/reports/staff-attendance", headers=as_(DEAN)).json()
    assert client.get("/api/me/insights", headers=as_("student9@nalut.edu.ly")).json()["attention"]


def test_message_attachment_reaches_the_other_side(client, as_):
    s = as_("s.ali@nalut.edu.ly")
    teacher_id = client.get("/api/me", headers=as_(TEACHER)).json()["id"]
    conv = client.post("/api/conversations", headers=s, json={"recipient_ids": [teacher_id], "subject": "واجب",
                                                              "body": "مرفق الواجب"}).json()["id"]
    pdf = b"%PDF-1.4\n% homework\n"
    # a file with no text is accepted; an empty message is not
    assert client.post(f"/api/conversations/{conv}/messages", headers=s, data={"body": ""}).status_code == 400
    r = client.post(f"/api/conversations/{conv}/messages", headers=s, data={"body": ""},
                    files={"upload": ("homework.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    msgs = client.get(f"/api/conversations/{conv}/messages", headers=as_(TEACHER)).json()["messages"]
    f = msgs[-1]["file"]
    assert f["name"] == "homework.pdf"
    got = client.get(f"/api/files/{f['id']}", headers=as_(TEACHER))
    assert got.status_code == 200 and got.content == pdf
    assert client.get(f"/api/files/{f['id']}", headers=as_("student2@nalut.edu.ly")).status_code == 404
