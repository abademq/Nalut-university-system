"""Attendance without a screen: the teacher's code, Bluetooth, and the fixed staff QR."""
from datetime import timedelta

from app import attendance as svc
from app.models import AttendanceRecord, AttendanceSession, StaffScan
from conftest import nonce

TEACHER = "t.ahmed@nalut.edu.ly"
STUDENT = "s.ali@nalut.edu.ly"
ROOM = {"latitude": 31.87, "longitude": 10.98}


def _cs101(client, as_):
    return next(c["id"] for c in client.get("/api/courses", headers=as_(TEACHER)).json() if c["code"] == "CS101")


def _post(client, headers, device="dev-1", **data):
    return client.post("/api/attendance/check-in", headers={**headers, "X-Device-Id": device},
                       data={"nonce": nonce(), **data})


def test_teacher_code_alone_with_chosen_duration(client, as_, db):
    t = as_(TEACHER)
    assert client.post("/api/attendance/sessions", headers=t, json={
        "course_id": _cs101(client, as_), "method": "code"}).status_code == 400  # no room location
    r = client.post("/api/attendance/sessions", headers=t, json={
        "course_id": _cs101(client, as_), "method": "code", "code_seconds": 300, **ROOM})
    assert r.status_code == 200 and r.json()["method"] == "code"
    sid = r.json()["id"]
    c = client.get(f"/api/attendance/sessions/{sid}/code", headers=t).json()
    assert len(c["code"]) == 4 and c["code_seconds"] == 300 and c["expires_in"] <= 300
    h = as_(STUDENT)
    wrong = "0000" if c["code"] != "0000" else "1111"
    assert client.post("/api/attendance/prepare", headers=h, json={"short_code": wrong}).status_code == 400
    p = client.post("/api/attendance/prepare", headers=h, json={"short_code": c["code"]})
    assert p.status_code == 200 and p.json()["id"] == sid and p.json()["require_location"]
    # a friend at home has the code but not the location: sent to review, not counted present
    r = _post(client, h, short_code=c["code"], latitude=32.5, longitude=13.1)
    assert r.status_code == 200 and r.json()["status"] == "pending_review"
    assert db.query(AttendanceRecord).filter_by(session_id=sid).one().method == "code"
    # whole-session code: the same all along
    sid2 = client.post("/api/attendance/sessions", headers=t, json={
        "course_id": _cs101(client, as_), "method": "code", "code_seconds": 0, **ROOM}).json()["id"]
    s2 = db.get(AttendanceSession, sid2)
    opt = svc.option_of(db, s2)
    assert svc.teacher_code(s2, opt) == svc.teacher_code(s2, opt, 0)


def test_bluetooth_signal_checks_in_and_expires(client, as_, db):
    t = as_(TEACHER)
    sid = client.post("/api/attendance/sessions", headers=t, json={
        "course_id": _cs101(client, as_), "method": "bluetooth"}).json()["id"]
    b = client.get(f"/api/attendance/sessions/{sid}/ble", headers=t).json()
    assert len(bytes.fromhex(b["data"])) == 16 and b["uuid"].replace("-", "") == b["data"] and b["data"][:4] == "4e55"
    h = as_(STUDENT)
    forged = b["data"][:-2] + ("00" if b["data"][-2:] != "00" else "11")
    assert client.post("/api/attendance/prepare", headers=h, json={"payload": f"NUB1:{forged}"}).status_code == 400
    s = db.get(AttendanceSession, sid)
    raw = bytes.fromhex(b["data"])
    old_w = int.from_bytes(raw[6:10], "big") - 5
    old = raw[:6] + old_w.to_bytes(4, "big") + svc._ble_mac(s, old_w)
    assert client.post("/api/attendance/prepare", headers=h, json={"payload": f"NUB1:{old.hex()}"}).status_code == 400
    p = client.post("/api/attendance/prepare", headers=h, json={"payload": f"NUB1:{b['data']}"}).json()
    r = _post(client, h, session_id=str(sid), ticket=p["ticket"])
    assert r.status_code == 200 and r.json()["status"] in ("present", "late")
    assert db.query(AttendanceRecord).filter_by(session_id=sid).one().method == "bluetooth"


def test_fixed_staff_qr_records_every_entry_and_exit(client, as_, db):
    dean = as_("dean.it@nalut.edu.ly")
    cp = client.post("/api/attendance/checkpoints", headers=dean, json={"name": "المدخل الرئيسي", **ROOM}).json()
    payload = client.get(f"/api/attendance/checkpoints/{cp['id']}/qr", headers=dean).json()["payload"]
    assert "<img" in client.get(f"/api/attendance/checkpoints/{cp['id']}/poster", headers=dean).text
    link = client.post(f"/api/attendance/checkpoints/{cp['id']}/link", headers=dean).json()["url"]
    assert "تسجيل الدوام" in client.get(link).text
    h = as_("registrar@nalut.edu.ly")
    assert client.post("/api/attendance/prepare", headers=as_(STUDENT), json={"payload": payload}).status_code == 403
    p = client.post("/api/attendance/prepare", headers=h, json={"payload": payload}).json()
    assert p["method"] == "post" and p["action"] == "in"
    assert _post(client, h, payload=payload, **ROOM).status_code == 200
    rec = db.query(AttendanceRecord).filter_by(session_id=p["id"]).one()
    assert rec.method == "post" and db.query(StaffScan).one().kind == "in"
    # leaving: refused away from work, recorded at work; a later exit replaces the earlier one
    for sc in db.query(StaffScan):
        sc.at = sc.at - timedelta(minutes=3)
    rec.check_in_at = rec.check_in_at - timedelta(minutes=3)
    db.commit()
    assert client.post("/api/attendance/prepare", headers=h, json={"payload": payload}).json()["action"] == "out"
    assert _post(client, h, payload=payload, latitude=32.5, longitude=13.1).status_code == 400
    r = _post(client, h, payload=payload, **ROOM)
    assert r.status_code == 200 and r.json()["check_out_at"]
    db.refresh(rec)
    rec.check_out_at = rec.check_out_at - timedelta(minutes=2)
    db.commit()
    first_out = rec.check_out_at
    assert _post(client, h, payload=payload, **ROOM).status_code == 200
    db.refresh(rec)
    assert rec.check_out_at > first_out
    day = client.get(f"/api/attendance/checkpoints/{cp['id']}/scans", headers=dean).json()
    person = day["people"][0]
    assert [s["kind"] for s in person["scans"]] == ["in", "out", "out"]
    assert len(client.get("/api/attendance/my-scans", headers=h).json()) == 3
    # a new code makes the printed poster stop working
    client.post(f"/api/attendance/checkpoints/{cp['id']}/rotate", headers=dean)
    assert client.post("/api/attendance/prepare", headers=h, json={"payload": payload}).status_code == 400
