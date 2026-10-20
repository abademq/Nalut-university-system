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
