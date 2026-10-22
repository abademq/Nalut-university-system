"""Platform administrator: managing any university, and the configurable permission matrix."""
from conftest import PASSWORD

from app.models import AuditLog, University, User
from app.security import totp_now

PRES = "president@nalut.edu.ly"
DEAN = "dean.it@nalut.edu.ly"


def platform(client):
    """Platform admins always enrol MFA; do it once and return headers."""
    r = client.post("/api/auth/login", json={"identifier": "platform@demo.ly", "password": PASSWORD}).json()
    setup = {"Authorization": f"Bearer {r['setup_token']}"}
    secret = client.post("/api/auth/mfa/setup", headers=setup).json()["secret"]
    token = client.post("/api/auth/mfa/enable", headers=setup, json={"code": totp_now(secret)}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def uni_id(db, code="nalut"):
    return db.query(University).filter_by(code=code).one().id


def test_platform_admin_manages_a_university_as_its_admin(client, db):
    h = platform(client)
    nalut = uni_id(db)
    act = {**h, "X-Act-As-University": str(nalut)}
    # without the header it is the platform account; with it, the university's administration
    assert client.get("/api/me", headers=h).json()["role"] == "platform_admin"
    prof = client.get("/api/me", headers=act).json()
    assert prof["role"] == "university_admin" and prof["university"]["id"] == nalut and prof["acting"] is True
    assert client.get("/api/users?limit=200", headers=act).status_code == 200
    # can edit the university's own administrators, which a university admin cannot
    pres = db.query(User).filter_by(email=PRES).one()
    r = client.patch(f"/api/users/{pres.id}", headers=act, json={"full_name": "رئيس معدل"})
    assert r.status_code == 200, r.text
    # edit settings and the current term
    assert client.put("/api/settings", headers=act, json={"settings": {"grading": {"pass_mark": 60}}}).status_code == 200
    # the account itself never changed role
    db.expire_all()
    assert db.query(User).filter_by(email="platform@demo.ly").one().role == "platform_admin"
    row = db.query(AuditLog).filter_by(action="user.updated").order_by(AuditLog.id.desc()).first()
    assert row.details.get("by_platform_admin") is True and row.university_id == nalut


def test_acting_header_is_ignored_for_other_users_and_account_endpoints(client, as_, db):
    nalut2 = uni_id(db, "demo2")
    p = as_(PRES)
    me = client.get("/api/me", headers={**p, "X-Act-As-University": str(nalut2)}).json()
    assert me["university"]["code"] == "nalut" and not me.get("acting")
    h = platform(client)
    bad = client.get("/api/users", headers={**h, "X-Act-As-University": "99999"})
    assert bad.status_code == 400


def test_only_platform_admin_edits_permissions(client, as_, db):
    p = as_(PRES)
    cat = client.get("/api/permissions", headers=p).json()
    assert cat["editable"] is False and "notify.official_warning" in cat["current"]
    r = client.put("/api/settings", headers=p, json={"settings": {"permissions": {"banners.manage": []}}})
    assert r.status_code == 403
    act = {**platform(client), "X-Act-As-University": str(uni_id(db))}
    assert client.get("/api/permissions", headers=act).json()["editable"] is True
    bad = client.put("/api/settings", headers=act, json={"settings": {"permissions": {"banners.manage": ["student"]}}})
    assert bad.status_code == 400


def test_permission_matrix_is_enforced(client, as_, db):
    act = {**platform(client), "X-Act-As-University": str(uni_id(db))}
    d = as_(DEAN)
    assert client.get("/api/banners/manage", headers=d).status_code == 200
    staff = as_("registrar@nalut.edu.ly")
    msg = {"category": "announcement", "title": "تجربة", "body": "نص التجربة", "target_type": "university"}
    assert client.post("/api/notifications", headers=staff, json=msg).status_code == 403
    matrix = {"banners.manage": [], "users.manage": [], "results.approve": [], "archive.access": [],
              "notify.announcement": ["faculty_admin", "staff", "teacher", "assistant"]}
    r = client.put("/api/settings", headers=act, json={"settings": {"permissions": matrix}})
    assert r.status_code == 200, r.text
    assert client.get("/api/banners/manage", headers=d).status_code == 403
    assert client.get("/api/results/pending", headers=d).status_code == 403
    assert client.get("/api/archive/students", headers=d).status_code == 403
    r = client.post("/api/users", headers=d, json={"full_name": "طالب جديد", "role": "student",
                                                   "email": "new.s@nalut.edu.ly"})
    assert r.status_code == 403
    # the university administration keeps every capability
    assert client.get("/api/banners/manage", headers=as_(PRES)).status_code == 200
    # newly granted: staff may now send announcements (within their scope)
    r = client.post("/api/notifications", headers=staff, json={**msg, "target_type": "faculty",
                                                                "target_ids": [me_faculty(client, staff)]})
    assert r.status_code != 403 or "غير مصرح لك بإصدار" not in r.text


def me_faculty(client, h):
    f = client.get("/api/me", headers=h).json()["faculty"]
    return f["id"] if f else 0


def test_teaching_and_admin_actions_are_configurable(client, as_, db):
    """Every former fixed rule is now a capability: revoke, see it refused, the rest unchanged."""
    act = {**platform(client), "X-Act-As-University": str(uni_id(db))}
    t, d = as_("t.ahmed@nalut.edu.ly"), as_(DEAN)
    course = client.get("/api/courses", headers=t).json()[0]
    cid = course["id"]
    slots = {"schedule": [{"day": 1, "start": "10:00", "end": "11:30", "room": "قاعة 4"}]}
    assert client.patch(f"/api/courses/{cid}", headers=t, json=slots).status_code == 200
    assert client.get("/api/reports/overview", headers=t).status_code == 200
    assert client.get("/api/audit", headers=d).status_code == 200
    catalog = {c["key"] for c in client.get("/api/permissions", headers=act).json()["capabilities"]}
    assert {"courses.schedule", "grades.enter", "attendance.manage", "reports.view", "audit.view"} <= catalog

    revoke = {k: [] for k in ("courses.schedule", "courses.components", "grades.enter", "results.submit",
                              "assignments.manage", "attendance.manage", "reports.view", "audit.view",
                              "messages.moderate", "courses.manage")}
    assert client.put("/api/settings", headers=act, json={"settings": {"permissions": revoke}}).status_code == 200
    assert client.patch(f"/api/courses/{cid}", headers=t, json=slots).status_code == 403
    assert client.post(f"/api/courses/{cid}/components", headers=t,
                       json={"name": "عملي", "max_score": 10}).status_code == 403
    assert client.put(f"/api/courses/{cid}/grades", headers=t, json={"entries": [], "reason": ""}).status_code == 403
    assert client.post(f"/api/courses/{cid}/results/submit", headers=t, json={"note": ""}).status_code == 403
    assert client.post(f"/api/courses/{cid}/assignments", headers=t,
                       json={"title": "مهمة", "kind": "homework", "max_score": 10,
                             "due_at": "2030-01-01T10:00:00Z"}).status_code == 403
    r = client.post("/api/attendance/sessions", headers=t, json={"kind": "course", "course_id": cid, "title": "جلسة"})
    assert r.status_code == 403
    assert client.get("/api/reports/overview", headers=t).status_code == 403
    assert client.get("/api/audit", headers=d).status_code == 403
    assert client.get("/api/message-reports", headers=d).status_code == 403
    assert client.patch(f"/api/courses/{cid}", headers=d, json={"title": "اسم جديد للمقرر"}).status_code == 403
    me_id = client.get("/api/me", headers=t).json()["id"]
    assert client.get(f"/api/reports/person/{me_id}", headers=t).status_code == 200  # own report always
    # the university administration is never locked out
    p = as_(PRES)
    assert client.patch(f"/api/courses/{cid}", headers=p, json=slots).status_code == 200
    assert client.get("/api/audit", headers=p).status_code == 200
    # and the profile tells the app what to show
    assert "grades.enter" not in client.get("/api/me", headers=t).json()["can"]


def test_staff_can_be_granted_banners(client, as_, db):
    act = {**platform(client), "X-Act-As-University": str(uni_id(db))}
    staff = as_("registrar@nalut.edu.ly")
    assert client.get("/api/banners/manage", headers=staff).status_code == 403
    r = client.put("/api/settings", headers=act, json={"settings": {"permissions": {"banners.manage": ["staff"]}}})
    assert r.status_code == 200, r.text
    r = client.post("/api/banners", headers=staff, json={"title": "إعلان من شؤون الطلبة"})
    assert r.status_code == 200, r.text


def test_admins_edit_their_own_details(client, as_, db):
    h = platform(client)
    r = client.patch("/api/me/profile", headers=h, json={"current_password": "wrong", "full_name": "مشرف"})
    assert r.status_code == 400
    r = client.patch("/api/me/profile", headers=h, json={"current_password": PASSWORD, "full_name": "عبد الرحمن",
                                                         "email": "Owner@Abade.ly", "phone": "0912345670"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["full_name"] == "عبد الرحمن" and me["email"] == "owner@abade.ly" and me["phone"] == "0912345670"
    assert any(a.action == "user.profile_self_updated" for a in db.query(AuditLog).all())
    # taken by another account / both identifiers removed
    taken = client.patch("/api/me/profile", headers=h, json={"current_password": PASSWORD, "email": PRES})
    assert taken.status_code == 400
    empty = client.patch("/api/me/profile", headers=h, json={"current_password": PASSWORD, "email": "", "phone": ""})
    assert empty.status_code == 400
    # while managing a university it still edits the real platform account, never the university's admin
    act = {**h, "X-Act-As-University": str(uni_id(db))}
    r = client.patch("/api/me/profile", headers=act, json={"current_password": PASSWORD, "full_name": "اسم آخر"})
    assert r.status_code == 200 and r.json()["role"] == "platform_admin"
    # the new email signs in
    assert client.post("/api/auth/login", json={"identifier": "owner@abade.ly", "password": PASSWORD}).status_code == 200
    # other roles ask their administration
    s = as_("s.ali@nalut.edu.ly")
    assert client.patch("/api/me/profile", headers=s, json={"current_password": PASSWORD,
                                                            "full_name": "اسم جديد"}).status_code == 403


def test_find_who_holds_a_phone(client, as_, db):
    p = as_(PRES)
    st = db.query(User).filter_by(email="s.ali@nalut.edu.ly").one()
    st.phone = "0916166288"
    db.commit()
    # found by phone in any format
    for q in ("0916166288", "916166288", "+218 91 616 6288", "٠٩١٦١٦٦٢٨٨"):
        items = client.get("/api/users", headers=p, params={"q": q}).json()["items"]
        assert [u["id"] for u in items] == [st.id], q
    # creating another account with the same number says who has it, in any format
    r = client.post("/api/users", headers=p, json={"full_name": "طالب جديد", "role": "student",
                                                   "phone": "+218916166288"})
    assert r.status_code == 400 and st.full_name in r.json()["detail"]
    # the platform administrator searches every university
    h = platform(client)
    items = client.get("/api/users", headers=h, params={"q": "0916166288"}).json()["items"]
    assert items[0]["id"] == st.id and items[0]["university"]
