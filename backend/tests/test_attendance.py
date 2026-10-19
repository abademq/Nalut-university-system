"""Anti-fraud properties of the attendance module."""
from app import attendance as svc
from app.models import AttendanceRecord, AttendanceSession, StoredFile
from conftest import nonce

TEACHER = "t.ahmed@nalut.edu.ly"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def open_session(client, as_, **extra):
    cs101 = next(c["id"] for c in client.get("/api/courses", headers=as_(TEACHER)).json() if c["code"] == "CS101")
    r = client.post("/api/attendance/sessions", headers=as_(TEACHER), json={"course_id": cs101, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def qr(client, as_, sid):
    return client.get(f"/api/attendance/sessions/{sid}/qr", headers=as_(TEACHER)).json()


def scan(client, headers, payload, device="dev-1", **data):
    return client.post("/api/attendance/check-in", headers={**headers, "X-Device-Id": device},
                       data={"payload": payload, "nonce": data.pop("nonce", nonce()), **data})


def test_qr_rotates_and_old_codes_expire(client, as_, db):
    sid = open_session(client, as_)
    s = db.get(AttendanceSession, sid)
    w = svc.current_window(s)
    assert svc.token_for(s, w) != svc.token_for(s, w + 1)
    stale = f"NUS1:{sid}:{w - 2}:{svc.token_for(s, w - 2)}"  # two windows old
    r = scan(client, as_("s.ali@nalut.edu.ly"), stale)
    assert r.status_code == 400
    previous = f"NUS1:{sid}:{w - 1}:{svc.token_for(s, w - 1)}"  # grace window accepted
    assert scan(client, as_("s.ali@nalut.edu.ly"), previous).status_code == 200


def test_forged_token_rejected(client, as_):
    sid = open_session(client, as_)
    payload = qr(client, as_, sid)["payload"]
    forged = payload[:-3] + ("AAA" if not payload.endswith("AAA") else "BBB")
    assert scan(client, as_("s.ali@nalut.edu.ly"), forged).status_code == 400


def test_duplicate_and_replay_rejected(client, as_):
    sid = open_session(client, as_)
    payload = qr(client, as_, sid)["payload"]
    n = nonce()
    assert scan(client, as_("s.ali@nalut.edu.ly"), payload, nonce=n).status_code == 200
    assert scan(client, as_("s.ali@nalut.edu.ly"), payload, nonce=n).status_code == 409  # replayed request
    assert scan(client, as_("s.ali@nalut.edu.ly"), payload).status_code == 409  # already recorded


def test_not_enrolled_cannot_check_in(client, as_):
    sid = open_session(client, as_)
    payload = qr(client, as_, sid)["payload"]
    assert scan(client, as_("student12@nalut.edu.ly"), payload).status_code == 403  # not in CS101
    assert scan(client, as_("student@demo2.edu.ly"), payload).status_code == 404  # other university


def test_shared_device_goes_to_review_not_penalty(client, as_, db):
    sid = open_session(client, as_)
    payload = qr(client, as_, sid)["payload"]
    assert scan(client, as_("s.ali@nalut.edu.ly"), payload, device="phone-X").json()["status"] == "present"
    r = scan(client, as_("student2@nalut.edu.ly"), payload, device="phone-X")
    assert r.json()["status"] == "pending_review"
    statuses = {rec.user_id: rec.status for rec in db.query(AttendanceRecord).filter_by(session_id=sid)}
    assert set(statuses.values()) == {"pending_review"}  # both flagged for a human, none marked absent
    queue = client.get("/api/attendance/review-queue", headers=as_(TEACHER)).json()
    rec_id = next(q["record"]["id"] for q in queue if q["session"]["id"] == sid)
    r = client.post(f"/api/attendance/records/{rec_id}/review", headers=as_(TEACHER),
                    json={"approve": True, "reason": "تحقق الأستاذ من الحضور"})
    assert r.json()["status"] == "present"


def test_geofence_and_required_factors(client, as_):
    sid = open_session(client, as_, risk_level="high", latitude=31.8686, longitude=10.9813, radius_m=100)
    payload = qr(client, as_, sid)["payload"]
    s = as_("s.ali@nalut.edu.ly")
    assert scan(client, s, payload).status_code == 400  # location required
    r = client.post("/api/attendance/check-in", headers={**s, "X-Device-Id": "d"},
                    data={"payload": payload, "nonce": nonce(), "latitude": "31.8686", "longitude": "10.9813"})
    assert r.status_code == 400  # live selfie required for high-risk sessions
    r = client.post("/api/attendance/check-in", headers={**s, "X-Device-Id": "d"},
                    data={"payload": payload, "nonce": nonce(), "latitude": "32.5", "longitude": "13.1"},
                    files={"selfie": ("live.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200 and r.json()["status"] == "pending_review"  # far away -> human review


def test_selfie_encrypted_and_access_restricted(client, as_, db):
    from app.config import settings
    sid = open_session(client, as_, require_selfie=True)
    payload = qr(client, as_, sid)["payload"]
    r = client.post("/api/attendance/check-in", headers={**as_("s.ali@nalut.edu.ly"), "X-Device-Id": "d"},
                    data={"payload": payload, "nonce": nonce()}, files={"selfie": ("live.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    rec = db.query(AttendanceRecord).filter_by(session_id=sid).one()
    f = db.get(StoredFile, rec.selfie_file_id)
    assert f.encrypted and f.delete_after is not None
    assert (settings.storage_dir / f.stored_name).read_bytes() != JPEG  # encrypted at rest
    assert client.get(f"/api/attendance/records/{rec.id}/selfie", headers=as_(TEACHER)).content == JPEG
    assert client.get(f"/api/attendance/records/{rec.id}/selfie",
                      headers=as_("student2@nalut.edu.ly")).status_code in (403, 404)
    assert client.get(f"/api/files/{f.id}", headers=as_("s.ali@nalut.edu.ly")).status_code == 404


def test_manual_correction_requires_reason_and_is_traceable(client, as_, db):
    sid = open_session(client, as_)
    student = client.get("/api/me", headers=as_("student3@nalut.edu.ly")).json()["id"]
    r = client.post(f"/api/attendance/sessions/{sid}/manual", headers=as_(TEACHER),
                    json={"user_id": student, "status": "excused", "reason": ""})
    assert r.status_code == 422
    r = client.post(f"/api/attendance/sessions/{sid}/manual", headers=as_(TEACHER),
                    json={"user_id": student, "status": "excused", "reason": "عذر طبي"})
    assert r.status_code == 200
    hist = client.get(f"/api/attendance/records/{r.json()['id']}/history", headers=as_(TEACHER)).json()
    assert hist[-1]["reason"] == "عذر طبي" and hist[-1]["actor"]
    assert client.get("/api/attendance/integrity", headers=as_("president@nalut.edu.ly")).json()["ok"]


def test_tampering_is_detected(client, as_, db):
    rec = db.query(AttendanceRecord).filter_by(status="absent").first()
    rec.status = "present"  # silent edit without a change log
    db.commit()
    result = client.get("/api/attendance/integrity", headers=as_("president@nalut.edu.ly")).json()
    assert not result["ok"]
    assert any(p["record_id"] == rec.id for p in result["problems"])


def test_close_marks_absent_and_alerts(client, as_, db):
    sid = open_session(client, as_)
    r = client.post(f"/api/attendance/sessions/{sid}/close", headers=as_(TEACHER)).json()
    assert r["absent_marked"] == 10
    # the frequently absent seeded student has threshold alerts (warning to student; no automatic sanction)
    items = client.get("/api/notifications", headers=as_("student9@nalut.edu.ly")).json()["items"]
    assert any("غياب" in n["title"] for n in items)


def test_staff_check_in_and_out(client, as_, db):
    r = client.post("/api/attendance/sessions", headers=as_("dean.it@nalut.edu.ly"),
                    json={"kind": "staff", "title": "دوام", "duration_minutes": 480})
    sid = r.json()["id"]
    payload = client.get(f"/api/attendance/sessions/{sid}/qr", headers=as_("dean.it@nalut.edu.ly")).json()["payload"]
    h = as_("registrar@nalut.edu.ly")
    assert scan(client, h, payload).status_code == 200
    rec = db.query(AttendanceRecord).filter_by(session_id=sid).one()
    from datetime import timedelta
    rec.check_in_at = rec.check_in_at - timedelta(hours=1)
    db.commit()
    r = scan(client, h, payload)
    assert r.status_code == 200 and r.json()["check_out_at"]
    assert scan(client, as_("s.ali@nalut.edu.ly"), payload).status_code == 403  # students are not staff


def test_short_code_fallback(client, as_, db):
    sid = open_session(client, as_)
    code = qr(client, as_, sid)["short_code"]
    r = client.post("/api/attendance/check-in", headers={**as_("s.ali@nalut.edu.ly"), "X-Device-Id": "d"},
                    data={"short_code": code, "session_id": str(sid), "nonce": nonce()})
    assert r.status_code == 200, r.text


def test_requirements_visible_only_to_participants(client, as_):
    sid = open_session(client, as_, risk_level="high", latitude=31.8686, longitude=10.9813)
    r = client.get(f"/api/attendance/sessions/{sid}/requirements", headers=as_("s.ali@nalut.edu.ly")).json()
    assert r["require_selfie"] and r["require_location"]
    assert client.get(f"/api/attendance/sessions/{sid}/requirements",
                      headers=as_("student12@nalut.edu.ly")).status_code == 404
    # the QR itself is only available to the session's managers
    assert client.get(f"/api/attendance/sessions/{sid}/qr", headers=as_("s.ali@nalut.edu.ly")).status_code == 403
