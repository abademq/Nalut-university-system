from app import db as dbmod
from app.models import University, User
from app.security import totp_now
from conftest import PASSWORD


def test_login_by_email_or_phone(client):
    assert client.post("/api/auth/login", json={"identifier": "S.Ali@nalut.edu.ly", "password": PASSWORD}).status_code == 200
    assert client.post("/api/auth/login", json={"identifier": "0920000001", "password": PASSWORD}).status_code == 200


def test_generic_errors_and_lockout(client):
    unknown = client.post("/api/auth/login", json={"identifier": "nobody@x.ly", "password": "x"})
    wrong = client.post("/api/auth/login", json={"identifier": "student2@nalut.edu.ly", "password": "bad"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()  # no account enumeration
    for _ in range(4):
        client.post("/api/auth/login", json={"identifier": "student2@nalut.edu.ly", "password": "bad"})
    r = client.post("/api/auth/login", json={"identifier": "student2@nalut.edu.ly", "password": PASSWORD})
    assert r.status_code == 423  # locked even with the right password


def test_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"identifier": "x@y.ly", "password": "x"}).status_code
             for _ in range(12)]
    assert 429 in codes


def test_passwords_are_hashed(db):
    u = db.query(User).filter_by(email="s.ali@nalut.edu.ly").one()
    assert u.password_hash.startswith("scrypt$") and PASSWORD not in u.password_hash


def test_refresh_rotation_and_reuse_detection(client):
    r = client.post("/api/auth/login", json={"identifier": "s.ali@nalut.edu.ly", "password": PASSWORD},
                    headers={"X-Client": "mobile"})
    first = r.json()["refresh_token"]
    r2 = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert r2.status_code == 200
    second = r2.json()["refresh_token"]
    # reuse from another device (or after the 60-second grace for a lost reply) is theft
    assert client.post("/api/auth/refresh", headers={"User-Agent": "attacker"},
                       json={"refresh_token": first}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": second}).status_code == 401  # family revoked


def test_cookie_refresh_requires_header(client):
    client.post("/api/auth/login", json={"identifier": "s.ali@nalut.edu.ly", "password": PASSWORD})
    assert client.post("/api/auth/refresh").status_code == 403
    assert client.post("/api/auth/refresh", headers={"X-Requested-With": "nus-web"}).status_code == 200


def test_mfa_enforced_for_admins(client, db):
    uni = db.query(University).filter_by(code="nalut").one()
    uni.settings = {**uni.settings, "security": {"require_mfa_for_admins": True}}
    db.commit()
    r = client.post("/api/auth/login", json={"identifier": "dean.it@nalut.edu.ly", "password": PASSWORD}).json()
    assert r.get("mfa_setup_required") and "access_token" not in r
    setup_headers = {"Authorization": f"Bearer {r['setup_token']}"}
    # a setup token is not an access token
    assert client.get("/api/me", headers=setup_headers).status_code == 401
    secret = client.post("/api/auth/mfa/setup", headers=setup_headers).json()["secret"]
    assert client.post("/api/auth/mfa/enable", headers=setup_headers, json={"code": "000000"}).status_code == 400
    r = client.post("/api/auth/mfa/enable", headers=setup_headers, json={"code": totp_now(secret)})
    assert r.status_code == 200 and r.json()["access_token"]
    # next login needs the TOTP code
    r = client.post("/api/auth/login", json={"identifier": "dean.it@nalut.edu.ly", "password": PASSWORD}).json()
    assert r == {"mfa_required": True, "method": "totp"}
    r = client.post("/api/auth/login", json={"identifier": "dean.it@nalut.edu.ly", "password": PASSWORD,
                                             "mfa_code": totp_now(secret)})
    assert r.status_code == 200
    stored = db.query(User).filter_by(email="dean.it@nalut.edu.ly").one()
    db.refresh(stored)
    assert secret not in (stored.mfa_secret_enc or "")  # encrypted at rest
    # students are not affected
    assert "access_token" in client.post("/api/auth/login", json={"identifier": "s.ali@nalut.edu.ly",
                                                                  "password": PASSWORD}).json()


def test_password_reset_flow(client, caplog, monkeypatch):
    """Long token path, used when no SMS provider is set up (the token goes by e-mail / dev log)."""
    import logging

    from app import mfa
    monkeypatch.setattr(mfa, "sms_available", lambda: False)
    caplog.set_level(logging.INFO, logger="nus.auth")
    assert client.post("/api/auth/password/forgot", json={"identifier": "nobody@x.ly"}).json()["ok"]
    client.post("/api/auth/password/forgot", json={"identifier": "s.ali@nalut.edu.ly"})
    token = [r.getMessage().split(": ")[-1] for r in caplog.records if "reset token" in r.getMessage()][-1]
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "short"}).status_code == 400
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "NewPass2026x"}).status_code == 200
    assert client.post("/api/auth/password/reset", json={"token": token, "new_password": "NewPass2026y"}).status_code == 400
    assert client.post("/api/auth/login", json={"identifier": "s.ali@nalut.edu.ly", "password": "NewPass2026x"}).status_code == 200


def test_deactivated_user_loses_access(client, as_):
    h = as_("student3@nalut.edu.ly")
    uid = client.get("/api/me", headers=h).json()["id"]
    assert client.patch(f"/api/users/{uid}", headers=as_("dean.it@nalut.edu.ly"), json={"is_active": False}).status_code == 200
    assert client.get("/api/me", headers=h).status_code == 401


def test_audit_chain(client, as_):
    as_("president@nalut.edu.ly")
    r = client.get("/api/audit/verify", headers=as_("president@nalut.edu.ly")).json()
    assert r["ok"] and r["checked"] > 0
    s = dbmod.SessionLocal()
    from app.models import AuditLog
    row = s.query(AuditLog).first()
    row.details = {"tampered": True}
    s.commit()
    s.close()
    assert not client.get("/api/audit/verify", headers=as_("president@nalut.edu.ly")).json()["ok"]


def test_lockout_limits_come_from_institution_settings(client, as_):
    admin = as_("president@nalut.edu.ly")
    cur = client.get("/api/settings", headers=admin).json()["effective"]["security"]
    assert client.put("/api/settings", headers=admin, json={"settings": {"security": {
        **cur, "max_login_failures": 3, "lockout_minutes": 5}}}).status_code == 200
    for _ in range(3):
        client.post("/api/auth/login", json={"identifier": "t.ahmed@nalut.edu.ly", "password": "wrong-password"})
    r = client.post("/api/auth/login", json={"identifier": "t.ahmed@nalut.edu.ly", "password": "Demo@12345"})
    assert r.status_code == 423


def test_lost_refresh_reply_retried_from_same_device_keeps_the_user_signed_in(client):
    """Weak network: the app refreshes, the reply never arrives, the app retries with the old token."""
    ua = {"User-Agent": "NalutApp/1.0", "X-Client": "mobile"}
    r = client.post("/api/auth/login", headers=ua, json={"identifier": "s.ali@nalut.edu.ly", "password": "Demo@12345"})
    old = r.json()["refresh_token"]
    first = client.post("/api/auth/refresh", headers=ua, json={"refresh_token": old})
    assert first.status_code == 200  # this reply is "lost"
    retry = client.post("/api/auth/refresh", headers=ua, json={"refresh_token": old})
    assert retry.status_code == 200
    new = retry.json()["refresh_token"]
    # the token from the lost reply no longer works, the retried one does
    assert client.post("/api/auth/refresh", headers=ua, json={"refresh_token": first.json()["refresh_token"]}).status_code == 401
    # ... and that was treated as theft: every session is revoked
    assert client.post("/api/auth/refresh", headers=ua, json={"refresh_token": new}).status_code == 401


def test_reused_refresh_token_from_another_device_is_theft(client):
    ua = {"User-Agent": "NalutApp/1.0", "X-Client": "mobile"}
    r = client.post("/api/auth/login", headers=ua, json={"identifier": "s.ali@nalut.edu.ly", "password": "Demo@12345"})
    old = r.json()["refresh_token"]
    good = client.post("/api/auth/refresh", headers=ua, json={"refresh_token": old}).json()["refresh_token"]
    thief = {"User-Agent": "curl/8", "X-Client": "mobile"}
    assert client.post("/api/auth/refresh", headers=thief, json={"refresh_token": old}).status_code == 401
    assert client.post("/api/auth/refresh", headers=ua, json={"refresh_token": good}).status_code == 401
