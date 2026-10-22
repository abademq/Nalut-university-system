"""SMS second factor, MFA policy by role / capability / account, and the Resala client."""
import io
import json
import re
import urllib.error

from datetime import timedelta

import pytest
from conftest import PASSWORD

from app import resala
from app.models import OtpChallenge, University, User
from app.notifications import LogSmsProvider

DEAN = "dean.it@nalut.edu.ly"
PRES = "president@nalut.edu.ly"


def last_code():
    return re.search(r"\d{6}", LogSmsProvider.sent[-1][1]).group(0)


def set_security(db, **sec):
    uni = db.query(University).filter_by(code="nalut").one()
    uni.settings = {**uni.settings, "security": {**uni.settings.get("security", {}), **sec}}
    db.commit()


def age_codes(db):
    """Moves earlier codes past the one-per-minute limit."""
    for c in db.query(OtpChallenge).all():
        c.created_at = c.created_at - timedelta(minutes=2)
    db.commit()


def login(client, ident, code=None):
    body = {"identifier": ident, "password": PASSWORD}
    if code:
        body["mfa_code"] = code
    return client.post("/api/auth/login", json=body)


def test_sms_enrolment_and_login(client, db):
    set_security(db, require_mfa_for_admins=True)
    r = login(client, DEAN).json()
    assert r["mfa_setup_required"] and "sms" in r["methods"] and r["phone_hint"]
    setup = {"Authorization": f"Bearer {r['setup_token']}"}
    assert client.post("/api/auth/mfa/sms/start", headers=setup).json()["sent"] is True
    assert client.post("/api/auth/mfa/sms/enable", headers=setup, json={"code": "000000"}).status_code == 400
    r = client.post("/api/auth/mfa/sms/enable", headers=setup, json={"code": last_code()})
    assert r.status_code == 200 and r.json()["access_token"]
    # stored as a keyed hash only
    assert all(not c.code_hash.isdigit() for c in db.query(OtpChallenge).all())

    # next login: password first, then the code that was just sent
    age_codes(db)
    first = login(client, DEAN).json()
    assert first["mfa_required"] and first["method"] == "sms" and first["sent"]
    # asking again within a minute does not send another SMS
    count = len(LogSmsProvider.sent)
    again = login(client, DEAN).json()
    assert again["sent"] is False and again["retry_after"] > 0 and len(LogSmsProvider.sent) == count
    assert login(client, DEAN, "111111").status_code == 401
    code = last_code()
    ok = login(client, DEAN, code)
    assert ok.status_code == 200 and ok.json()["user"]["mfa_method"] == "sms"
    assert login(client, DEAN, code).status_code == 401  # a code works once


def test_policy_by_role_capability_and_account(client, db, as_):
    p = as_(PRES)  # signed in before the policy below also covers university admins
    teacher = db.query(User).filter_by(email="t.ahmed@nalut.edu.ly").one()
    assert "access_token" in login(client, teacher.email).json()
    set_security(db, mfa_required_roles=["teacher"])
    assert login(client, teacher.email).json().get("mfa_setup_required")
    set_security(db, mfa_required_roles=[], mfa_required_capabilities=["archive.access"])
    assert login(client, "registrar@nalut.edu.ly").json().get("mfa_setup_required")  # registrar holds it
    assert "access_token" in login(client, teacher.email).json()
    # one account, chosen by an administrator
    r = client.post(f"/api/users/{teacher.id}/mfa", headers=p, json={"required": True})
    assert r.status_code == 200 and r.json()["mfa_required"] is True
    assert login(client, teacher.email).json().get("mfa_setup_required")
    # methods offered follow the settings
    set_security(db, mfa_methods=["totp"])
    assert login(client, teacher.email).json()["methods"] == ["totp"]
    assert client.put("/api/settings", headers=p,
                      json={"settings": {"security": {"mfa_methods": []}}}).status_code == 400


def test_admin_reset_lets_the_user_enrol_again(client, db, as_):
    p = as_(PRES)
    set_security(db, require_mfa_for_admins=True)
    r = login(client, DEAN).json()
    setup = {"Authorization": f"Bearer {r['setup_token']}"}
    client.post("/api/auth/mfa/sms/start", headers=setup)
    client.post("/api/auth/mfa/sms/enable", headers=setup, json={"code": last_code()})
    dean = db.query(User).filter_by(email=DEAN).one()
    r = client.post(f"/api/users/{dean.id}/mfa", headers=p, json={"reset": True})
    assert r.json()["mfa_enabled"] is False
    assert login(client, DEAN).json().get("mfa_setup_required")


# ------------------------------------------------------------------ Resala client


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(status, payload, seen):
    def _open(req, timeout):
        seen.append(req)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(json.dumps(payload).encode()))
        return FakeResp(json.dumps(payload).encode())
    return _open


def test_resala_calls_and_errors():
    seen = []
    c = resala.ResalaClient("rsl_test", opener=opener(201, {"id": "9b1f", "pin": "482913", "code": "218", "region": "LY",
                                                             "number": "910001234", "content": "x", "hit_count": 0,
                                                             "created_at": "", "updated_at": "", "sender_name": "UNI"},
                                                      seen))
    pin = c.send_pin("218910001234", test=True, sender="UNI")
    assert pin.pin == "482913" and pin.sender_name == "UNI"
    req = seen[-1]
    assert req.get_method() == "POST" and req.full_url.endswith("/pins?test=true&sender=UNI")
    assert req.headers["Authorization"] == "Bearer rsl_test" and json.loads(req.data) == {"phone": "218910001234"}

    c = resala.ResalaClient("rsl_test", opener=opener(201, {"is_prod": False, "total_messages": 2, "succeeded": 1,
                                                             "failed": 0, "failed_numbers": [],
                                                             "invalid_numbers": ["218850000000"],
                                                             "sender_names": {"libyana": "UNI"},
                                                             "sms_template_version": None}, seen))
    res = c.send_template("tpl-1", [resala.TemplateRecord("218910001234", ["عنوان", "نص"])])
    assert res.invalid_numbers == ["218850000000"] and res.sender_names["libyana"] == "UNI"
    assert json.loads(seen[-1].data)["records"][0] == {"phone": "218910001234", "$1": "عنوان", "$2": "نص"}
    assert "sms_template_id=tpl-1" in seen[-1].full_url

    c = resala.ResalaClient("rsl_test", opener=opener(422, {"type": "InputValidation", "message": "خطأ",
                                                             "errors": {"phone": ["رقم غير صالح"]}}, seen))
    with pytest.raises(resala.ResalaError) as e:
        c.send_pin("123")
    assert e.value.type == resala.INPUT_VALIDATION and e.value.errors == {"phone": ["رقم غير صالح"]}
    c = resala.ResalaClient("rsl_test", opener=opener(400, {"type": "InsufficientCredit", "message": "..."}, seen))
    with pytest.raises(resala.ResalaError) as e:
        c.sent_view(page=1)
    assert e.value.type == resala.INSUFFICIENT_CREDIT


def test_libyan_mobile_normalization():
    assert resala.libyan_mobile("0912345678") == "218912345678"
    assert resala.libyan_mobile("+218 94-123-4567") == "218941234567"
    assert resala.libyan_mobile("٠٩٢١٢٣٤٥٦٧") == "218921234567"
    assert resala.libyan_mobile("0951234567") is None  # not a Libyan mobile prefix
    assert resala.libyan_mobile("+201001234567") is None
