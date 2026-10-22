"""One-time hand-off from the app to the web dashboard, and password change keeping the session."""
from conftest import PASSWORD

STUDENT = "s.ali@nalut.edu.ly"


def test_handoff_opens_the_dashboard_once(client, as_):
    h = as_(STUDENT)
    path = client.post("/api/auth/handoff/start", headers=h).json()["path"]
    code = path.rsplit("/", 1)[1]
    r = client.post("/api/auth/handoff", json={"code": code})
    assert r.status_code == 200 and r.json()["user"]["email"] == STUDENT
    assert client.post("/api/auth/handoff", json={"code": code}).status_code == 401  # used
    cid = code.split(".")[0]
    assert client.post("/api/auth/handoff", json={"code": f"{cid}.wrong-secret-xxxx"}).status_code == 401
    assert client.post("/api/auth/handoff", json={"code": "not-a-code-at-all"}).status_code == 401


def test_password_change_keeps_this_device_signed_in(client):
    r = client.post("/api/auth/login", headers={"X-Client": "mobile"},
                    json={"identifier": STUDENT, "password": PASSWORD}).json()
    old_refresh = r["refresh_token"]
    h = {"Authorization": f"Bearer {r['access_token']}", "X-Client": "mobile"}
    r = client.post("/api/auth/password/change", headers=h,
                    json={"current_password": PASSWORD, "new_password": "NewPass2026x"})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["access_token"] and new["refresh_token"] and new["refresh_token"] != old_refresh
    # the new refresh token works; the old one was revoked (reusing it counts as theft)
    assert client.post("/api/auth/refresh", headers={"X-Client": "mobile"},
                       json={"refresh_token": new["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/refresh", headers={"X-Client": "mobile"},
                       json={"refresh_token": old_refresh}).status_code == 401
