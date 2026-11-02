"""Courses and credits per student, prerequisites and the other registration rules."""
from app import grades
from app.models import AuditLog, Course, Enrollment, University, User
from app.tenancy import effective_settings

DEAN = "dean.it@nalut.edu.ly"
ALI = "2023001"  # s.ali: registered in CS101 and CS201 this term


def course_id(db, code):
    return db.query(Course).filter_by(code=code).order_by(Course.id.desc()).first().id


def new_course(client, h, code, schedule=(), credits=3):
    r = client.post("/api/courses", headers=h, json={"code": code, "title": f"مقرر {code}", "credits": credits,
                                                     "schedule": list(schedule)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def enroll(client, h, cid, *codes, **extra):
    return client.post(f"/api/courses/{cid}/enrollments", headers=h, json={"student_codes": list(codes), **extra})


def test_prerequisites_block_registration_until_passed(client, as_, db):
    d = as_(DEAN)
    cs201 = client.get(f"/api/courses/{course_id(db, 'CS201')}", headers=d).json()
    assert cs201["prerequisites"] == [{"code": "CS101", "title": "مقدمة في البرمجة"}]
    cid = new_course(client, d, "CS301")
    r = client.put(f"/api/courses/{cid}/prerequisites", headers=d, json={"codes": ["cs201"]})
    assert r.status_code == 200 and [p["code"] for p in r.json()["prerequisites"]] == ["CS201"]
    # a loop is refused, so is an unknown code
    assert client.put(f"/api/courses/{course_id(db, 'CS201')}/prerequisites", headers=d,
                      json={"codes": ["CS101", "CS301"]}).status_code == 400
    assert client.put(f"/api/courses/{cid}/prerequisites", headers=d, json={"codes": ["XX999"]}).status_code == 400
    # Ali has not passed CS201 (its results are not published)
    r = enroll(client, d, cid, ALI).json()
    assert r["added"] == [] and "CS201" in r["refused"][0]["problems"][0]
    assert enroll(client, d, cid, ALI, override=True).status_code == 400  # a reason is required
    r = enroll(client, d, cid, ALI, override=True, reason="موافقة مجلس القسم").json()
    assert r["added"] == [ALI] and r["overridden"] == [ALI]
    log = db.query(AuditLog).filter_by(action="course.enrolled", target_id=str(cid)).all()
    assert log[-1].details["reason"] == "موافقة مجلس القسم"


def test_a_published_pass_opens_the_next_course(client, as_, db):
    d = as_(DEAN)
    uni = db.query(University).filter_by(code="nalut").one()
    grading = effective_settings(uni)["grading"]
    is110 = db.get(Course, course_id(db, "IS110"))
    ids = [e.student_id for e in db.query(Enrollment).filter_by(course_id=is110.id)]
    passed = [db.get(User, i) for i in ids if grades.student_summary(db, is110, i, grading)["passed"]]
    failed = [db.get(User, i) for i in ids if grades.student_summary(db, is110, i, grading)["passed"] is False]
    assert passed
    cid = new_course(client, d, "IS210")
    client.put(f"/api/courses/{cid}/prerequisites", headers=d, json={"codes": ["IS110"]})
    r = enroll(client, d, cid, passed[0].code, *[f.code for f in failed[:1]]).json()
    assert passed[0].code in r["added"]
    assert [x["code"] for x in r["refused"]] == [f.code for f in failed[:1]]


def test_clash_and_credit_ceiling(client, as_, db):
    d = as_(DEAN)
    # CS101 meets on Saturday 08:30-10:00
    clash = new_course(client, d, "CS150", [{"day": 0, "start": "09:00", "end": "10:30", "room": "C1"}])
    r = enroll(client, d, clash, ALI).json()
    assert r["added"] == [] and "يتعارض" in r["refused"][0]["problems"][0]
    p = as_("president@nalut.edu.ly")
    cur = client.get("/api/settings", headers=p).json()["effective"]["registration"]
    assert client.put("/api/settings", headers=p, json={"settings": {"registration": {
        **cur, "max_credits_per_term": 6, "min_credits_per_term": 9}}}).status_code == 400  # min above max
    assert client.put("/api/settings", headers=p, json={"settings": {"registration": {
        **cur, "max_credits_per_term": 6, "min_credits_per_term": 0}}}).status_code == 200
    free = new_course(client, d, "CS160", [{"day": 5, "start": "08:00", "end": "09:00", "room": "C2"}])
    r = enroll(client, d, free, ALI).json()
    assert r["added"] == [] and "الحد الأعلى" in r["refused"][0]["problems"][0]


def test_students_see_their_courses_and_credits(client, as_):
    me = client.get("/api/me/academic", headers=as_("s.ali@nalut.edu.ly")).json()
    assert me["current_courses"] == 2 and me["current_credits"] == 6
    assert {c["code"] for c in me["courses"]} == {"CS101", "CS201"} and all(c["credits"] == 3 for c in me["courses"])
    assert me["load_warning"]  # 6 credits is under the default minimum of 12
    sid = client.get("/api/me", headers=as_("s.ali@nalut.edu.ly")).json()["id"]
    rep = client.get(f"/api/reports/person/{sid}", headers=as_(DEAN)).json()
    assert rep["academic"]["current_credits"] == 6
    assert client.get("/api/me/academic", headers=as_(DEAN)).status_code == 403


def test_transcript_term_and_cumulative_average_with_advice(client, as_, db):
    uni = db.query(University).filter_by(code="nalut").one()
    grading = effective_settings(uni)["grading"]
    is110 = db.get(Course, course_id(db, "IS110"))
    ids = [e.student_id for e in db.query(Enrollment).filter_by(course_id=is110.id)]
    failed = next(db.get(User, i) for i in ids if grades.student_summary(db, is110, i, grading)["passed"] is False)
    pct = grades.student_summary(db, is110, failed.id, grading)["percent"]
    from conftest import login
    h = login(client, failed.email)
    tr = client.get("/api/me/transcript", headers=h).json()
    assert len(tr["terms"]) == 1 and tr["terms"][0]["courses"][0]["code"] == "IS110"
    assert tr["terms"][0]["average"] == pct == tr["cumulative_average"] and tr["earned_credits"] == 0
    assert any("IS110" in a["text"] and a["level"] == "danger" for a in tr["advice"])  # retake it
    # results not yet published do not count
    ali = client.get("/api/me/transcript", headers=as_("s.ali@nalut.edu.ly")).json()
    assert ali["terms"] == [] and ali["cumulative_average"] is None
    rep = client.get(f"/api/reports/person/{failed.id}", headers=as_(DEAN)).json()
    assert rep["transcript"]["cumulative_average"] == pct
