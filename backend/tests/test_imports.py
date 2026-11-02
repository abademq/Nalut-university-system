"""Entering existing students and earlier results from Excel, and starting again from nothing."""
import io

from openpyxl import Workbook, load_workbook

PRES = "president@nalut.edu.ly"


def xlsx(rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client, h, kind, rows):
    return client.post(f"/api/import/{kind}/preview", headers=h,
                       files={"upload": ("data.xlsx", xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_template_students_and_results(client, as_):
    p = as_(PRES)
    t = client.get("/api/import/students/template", headers=p)
    assert t.status_code == 200
    header = [c.value for c in next(load_workbook(io.BytesIO(t.content)).active.iter_rows(max_row=1))]
    assert header[:3] == ["رقم القيد", "الاسم", "البريد"]
    rows = [header,
            ["2019001", "خالد سالم", "khaled19@example.ly", "0919990001", "تقنية المعلومات", "علوم الحاسوب", "2019", "مستمر", 6, "CS"],
            ["2015002", "هدى علي", "", "", "كلية تقنية المعلومات", "", "2015", "متخرج", "", ""],
            ["2018003", "عمر", "", "", "الطب", "", "", "مستمر", "", ""]]
    r = upload(client, p, "students", rows).json()
    assert r["can_commit"] is False and r["errors"][0]["line"] == 4 and "الطب" in r["errors"][0]["problems"][0]
    r = upload(client, p, "students", rows[:3]).json()
    assert r["can_commit"] and r["summary"]["create"] == 2
    done = client.post(f"/api/import/jobs/{r['id']}/commit", headers=p).json()
    assert done["created"] == 2 and {x["code"] for x in done["passwords"]} == {"2019001", "2015002"}
    assert client.post(f"/api/import/jobs/{r['id']}/commit", headers=p).status_code == 400  # once only
    # the new student signs in with the temporary password and sees semester 6 of their plan
    pw = next(x["password"] for x in done["passwords"] if x["code"] == "2019001")
    login = {"identifier": "khaled19@example.ly", "password": pw}
    first = client.post("/api/auth/login", json=login).json()
    assert first.get("first_login")  # a code by SMS at the first sign-in, as for every new account
    import re

    from app.notifications import LogSmsProvider
    code = re.search(r"\d{6}", LogSmsProvider.sent[-1][1]).group(0)
    tok = client.post("/api/auth/login", json={**login, "mfa_code": code}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get("/api/me/plan", headers=h).json()["level"] == 6
    # earlier results
    res = upload(client, p, "results", [["رقم القيد", "رمز المقرر", "اسم المقرر", "الوحدات", "الدرجة", "الفصل", "النوع"],
                                         ["2019001", "MATH101", "", "", "82", "خريف 2019", "سابق"],
                                         ["2019001", "ENG101", "", "", "", "", "معادلة"],
                                         ["2099999", "MATH101", "", "", "70", "", ""]]).json()
    assert not res["can_commit"] and "2099999" in res["errors"][0]["problems"][0]
    res = upload(client, p, "results", [["رقم القيد", "رمز المقرر", "اسم المقرر", "الوحدات", "الدرجة", "الفصل", "النوع"],
                                         ["2019001", "MATH101", "", "", "82", "خريف 2019", "سابق"],
                                         ["2019001", "ENG101", "", "", "", "", "معادلة"]]).json()
    assert res["can_commit"] and res["sample"][0]["course_title"] == "رياضة 1"  # from the plan
    assert client.post(f"/api/import/jobs/{res['id']}/commit", headers=p).json() == {"added": 2, "updated": 0}
    tr = client.get("/api/me/transcript", headers=h).json()
    assert tr["cumulative_average"] == 82.0 and tr["earned_credits"] == 5
    assert upload(client, as_("t.ahmed@nalut.edu.ly"), "students", rows[:2]).status_code == 403


def test_reset_keeps_the_university_and_the_platform_account(client, tmp_path, monkeypatch):
    """Runs on the test database of the client fixture, never the real one."""
    from app import reset
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Course, Faculty, Program, University, User

    files_dir = tmp_path / "files"  # the client fixture's file store
    assert settings.storage_dir == files_dir
    (files_dir / "x.bin").write_bytes(b"1")
    monkeypatch.setattr(reset, "backup", lambda: [])
    counts = reset.reset(keep_structure=True)
    db = SessionLocal()
    assert db.query(University).count() >= 1 and db.query(Course).count() == 0
    assert {u.role for u in db.query(User)} == {"platform_admin"}
    assert db.query(Faculty).count() == counts["faculties"] > 0 and db.query(Program).count() == 1
    assert not any((tmp_path / "files").iterdir())
    db.close()
