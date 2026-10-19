"""Authorization and tenant isolation."""


def ids(client, headers, path="/api/courses"):
    return {c["code"]: c["id"] for c in client.get(path, headers=headers).json()}


def test_student_sees_only_enrolled_courses(client, as_):
    codes = set(ids(client, as_("s.ali@nalut.edu.ly")))
    assert codes == {"CS101", "CS201"}
    ce101 = ids(client, as_("t.khaled@nalut.edu.ly"))["CE101"]
    assert client.get(f"/api/courses/{ce101}", headers=as_("s.ali@nalut.edu.ly")).status_code == 403


def test_other_university_is_invisible(client, as_):
    other = ids(client, as_("student@demo2.edu.ly"))["MATH101"]
    for email in ("president@nalut.edu.ly", "t.ahmed@nalut.edu.ly", "s.ali@nalut.edu.ly"):
        assert client.get(f"/api/courses/{other}", headers=as_(email)).status_code == 404
    users = client.get("/api/users?limit=200", headers=as_("president@nalut.edu.ly")).json()["items"]
    assert all(not (u["email"] or "").endswith("demo2.edu.ly") for u in users)
    # same student number exists in both universities but never leaks
    found = client.get("/api/users?q=2023001", headers=as_("president@nalut.edu.ly")).json()["items"]
    assert len(found) == 1


def test_teacher_cannot_grade_or_teach_other_course(client, as_):
    is110 = ids(client, as_("t.salma@nalut.edu.ly"))["IS110"]
    t = as_("t.ahmed@nalut.edu.ly")
    assert client.put(f"/api/courses/{is110}/grades", headers=t, json={"entries": []}).status_code == 403
    assert client.post(f"/api/courses/{is110}/assignments", headers=t,
                       json={"title": "x" * 5, "due_at": "2030-01-01T00:00:00Z"}).status_code == 403
    assert client.post("/api/attendance/sessions", headers=t, json={"course_id": is110}).status_code == 403


def test_student_cannot_use_admin_or_teacher_endpoints(client, as_):
    s = as_("s.ali@nalut.edu.ly")
    cs101 = ids(client, s)["CS101"]
    assert client.get(f"/api/courses/{cs101}/grades", headers=s).status_code == 403
    assert client.get(f"/api/courses/{cs101}/students", headers=s).status_code == 403
    assert client.post("/api/users", headers=s, json={"full_name": "x", "role": "student"}).status_code == 403
    assert client.get("/api/audit", headers=s).status_code == 403
    assert client.get("/api/reports/overview", headers=s).status_code == 403
    me = client.get("/api/me", headers=s).json()
    assert client.patch(f"/api/users/{me['id']}", headers=s, json={"role": "university_admin"}).status_code == 403


def test_admin_cannot_escalate_or_cross_faculty(client, as_):
    dean = as_("dean.it@nalut.edu.ly")
    me = client.get("/api/me", headers=dean).json()
    # cannot change own role
    assert client.patch(f"/api/users/{me['id']}", headers=dean, json={"role": "university_admin"}).status_code == 403
    # cannot create a university admin
    r = client.post("/api/users", headers=dean, json={"full_name": "x y", "role": "university_admin",
                                                      "email": "x@nalut.edu.ly"})
    assert r.status_code == 403
    # cannot manage a user of another faculty
    eng_teacher = client.get("/api/users?q=t.khaled", headers=as_("president@nalut.edu.ly")).json()["items"][0]
    assert client.patch(f"/api/users/{eng_teacher['id']}", headers=dean, json={"is_active": False}).status_code == 403
    # can create a student in own faculty; temp password must be changed
    r = client.post("/api/users", headers=dean, json={"full_name": "طالب جديد", "role": "student",
                                                      "email": "new@nalut.edu.ly", "code": "2026999"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["faculty_id"] == me["faculty"]["id"]


def test_unpublished_results_hidden_from_student(client, as_):
    grades = {g["course"]["code"]: g for g in client.get("/api/me/grades", headers=as_("student5@nalut.edu.ly")).json()}
    assert grades["IS110"]["published"] and grades["IS110"]["letter"]
    assert not grades["CS101"]["published"] and "scores" not in grades["CS101"]
    assert not grades["CS201"]["published"]  # submitted but not approved


def test_staff_sees_only_own_office_requests(client, as_):
    assert len(client.get("/api/requests?scope=office", headers=as_("registrar@nalut.edu.ly")).json()) == 1
    assert client.get("/api/requests?scope=office", headers=as_("affairs@nalut.edu.ly")).json() == []
    assert client.get("/api/requests?scope=office", headers=as_("s.ali@nalut.edu.ly")).status_code == 403
    rid = client.get("/api/requests", headers=as_("s.ali@nalut.edu.ly")).json()[0]["id"]
    assert client.get(f"/api/requests/{rid}", headers=as_("student2@nalut.edu.ly")).status_code == 404


def test_unauthenticated_and_forged_tokens(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    import jwt
    forged = jwt.encode({"sub": "1", "typ": "access", "exp": 9999999999}, "wrong-key", algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
