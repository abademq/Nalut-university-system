"""Study programmes: the plan by semester and each student's progress through it."""
from app.models import Program

DEAN = "dean.it@nalut.edu.ly"
ALI = "s.ali@nalut.edu.ly"  # computer science, first term: CS101 and CS201 running


def test_student_sees_plan_next_courses_and_what_must_be_passed(client, as_):
    p = client.get("/api/me/plan", headers=as_(ALI)).json()
    assert p["program"]["name"] == "علوم الحاسوب"  # from the department, no explicit placement needed
    assert p["level"] == 1 and p["next_semester"] == 2
    first = p["semesters"][0]
    assert {c["code"]: c["state"] for c in first["courses"]}["CS101"] == "in_progress"
    nxt = {c["code"]: c for c in p["next_courses"]}
    assert nxt["MATH101"]["overdue"] and nxt["MATH101"]["status"] == "open"   # first-semester course not taken yet
    assert nxt["CS102"]["status"] == "pending"   # opens if CS101, running now, is passed
    assert nxt["MATH102"]["status"] == "closed"  # needs MATH101, not taken
    assert "CS201" not in nxt                    # already being taken
    must = {m["code"]: m for m in p["must_pass"]}
    assert "برمجة 2 (CS102)" in must["CS101"]["unlocks"]
    assert p["earned_credits"] == 0 and p["remaining_credits"] == p["plan_credits"] > 0
    sid = client.get("/api/me", headers=as_(ALI)).json()["id"]
    staff = client.get(f"/api/students/{sid}/plan", headers=as_(DEAN)).json()
    assert staff["next_semester"] == 2


def test_plan_editing_rules_and_placement(client, as_, db):
    d = as_(DEAN)
    pid = db.query(Program).filter_by(code="CS").one().id
    plan = client.get(f"/api/programs/{pid}", headers=d).json()["courses"]
    assert any(c["code"] == "CS302" and c["prerequisites"] == ["CS201", "MATH102"] for c in plan)
    bad = [{"semester": 1, "code": "A1", "title": "أ", "credits": 3, "prerequisites": ["B2"]},
           {"semester": 2, "code": "B2", "title": "ب ب", "credits": 3}]
    assert client.put(f"/api/programs/{pid}/courses", headers=d, json={"courses": bad}).status_code == 422  # short title
    bad[0]["title"] = "مقرر أ"
    bad[1]["title"] = "مقرر ب"
    r = client.put(f"/api/programs/{pid}/courses", headers=d, json={"courses": bad})
    assert r.status_code == 400 and "فصل سابق" in r.json()["detail"]
    teacher = as_("t.ahmed@nalut.edu.ly")
    assert client.put(f"/api/programs/{pid}/courses", headers=teacher, json={"courses": []}).status_code == 403
    new = client.post("/api/programs", headers=d, json={"name": "نظم المعلومات", "code": "IS", "semesters": 8}).json()
    r = client.post(f"/api/programs/{new['id']}/students", headers=d, json={"student_codes": ["2023001", "2024001"]}).json()
    assert r["placed"] == ["2023001"] and r["unknown"] == ["2024001"]  # an engineering student is not in this faculty
    assert client.get("/api/me/plan", headers=as_(ALI)).json()["program"]["code"] == "IS"
    assert client.delete(f"/api/programs/{new['id']}", headers=d).status_code == 400  # has students


def test_semester_and_courses_passed_before_the_platform(client, as_, db):
    """A fifth-semester student whose first four semesters were before the platform."""
    from app.models import User

    d = as_(DEAN)
    st = db.query(User).filter_by(email="student3@nalut.edu.ly").one()  # computer science, CS101 and CS201 now
    before = client.get(f"/api/students/{st.id}/plan", headers=d).json()
    assert before["level"] == 1 and before["can_manage"] is True
    r = client.post(f"/api/students/{st.id}/prior-credits/bulk", headers=d, json={"up_to_semester": 1}).json()
    assert "MATH101" in r["added"] and "CS101" not in r["added"]  # CS101 is being taken now
    plan = client.get(f"/api/students/{st.id}/plan", headers=d).json()
    assert plan["semester_set_manually"] and plan["level"] == 2 and plan["next_semester"] == 3
    sem1 = {c["code"]: c for c in plan["semesters"][0]["courses"]}
    assert sem1["MATH101"]["state"] == "passed" and sem1["MATH101"]["source"] == "prior"
    nxt = {c["code"]: c for c in plan["next_courses"]}
    assert nxt["MATH102"]["status"] == "open"  # its prerequisite was passed before the platform
    # a course recognised from another university, with its mark
    t = client.post(f"/api/students/{st.id}/prior-credits", headers=d,
                    json={"code": "MATH102", "kind": "transfer", "percent": 80}).json()
    assert t["title"] == "رياضة 2" and t["credits"] == 3  # taken from the plan
    login = client.post("/api/auth/login", json={"identifier": st.email, "password": "Demo@12345"}).json()
    tr = client.get("/api/me/transcript", headers={"Authorization": f"Bearer {login['access_token']}"}).json()
    assert tr["terms"][0]["prior"] and tr["cumulative_average"] == 80.0  # only graded ones count in the average
    assert tr["earned_credits"] >= 3 + 3 + 2 + 3
    # registration now accepts MATH102's dependants; the teacher cannot change any of this
    assert client.put(f"/api/students/{st.id}/semester", headers=as_("t.ahmed@nalut.edu.ly"),
                      json={"semester": 4}).status_code == 403
    assert client.put(f"/api/students/{st.id}/semester", headers=d, json={"semester": None}).status_code == 200
    assert client.get(f"/api/students/{st.id}/plan", headers=d).json()["semester_set_manually"] is False
    assert client.delete(f"/api/prior-credits/{t['id']}", headers=d).status_code == 200
