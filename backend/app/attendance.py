"""Attendance service: rotating QR codes, check-in verification and risk scoring.

Security model
--------------
* The QR shown in the room changes every ``rotation_seconds``. Its token is an
  HMAC of (session id, time window) under a per-session random secret that never
  leaves the server, so codes cannot be predicted and expire quickly.
* A scanned code is accepted for the current and the previous window only.
* Each check-in request carries a client-generated nonce that is stored; replaying
  the same request is refused.
* A valid code is *not* proof of presence. Extra signals (geofence, device reuse
  across accounts, new device, optional live selfie) produce a risk score; above
  the policy threshold the check-in waits for human review. No signal punishes a
  user automatically.
* Records are chained by hash and every status change is logged with its reason,
  so silent edits can be detected (:func:`verify_integrity`).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, notifications
from .biometrics import get_verifier
from .db import utcnow
from .models import (
    AttendanceAlert,
    AttendanceChange,
    AttendanceNonce,
    AttendanceRecord,
    AttendanceSession,
    Course,
    CourseStaff,
    Enrollment,
    Role,
    University,
    User,
    UserDevice,
)
from .security import limiter
from .tenancy import DEFAULT_SETTINGS, effective_settings

QR_PREFIX = "NUS1"
COUNTED_ABSENT = {"absent", "rejected"}
STATUSES = {"present", "late", "absent", "excused", "pending_review", "rejected"}

_chain_lock = threading.Lock()


# --------------------------------------------------------------------------- rotating codes


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def current_window(session: AttendanceSession, at=None) -> int:
    return int((at or utcnow()).timestamp() // session.rotation_seconds)


def _mac(session: AttendanceSession, window: int) -> bytes:
    return hmac.new(session.secret.encode(), f"{session.id}:{window}".encode(), hashlib.sha256).digest()


def token_for(session: AttendanceSession, window: int) -> str:
    return base64.b32encode(_mac(session, window)[:10]).decode().rstrip("=")


def short_code_for(session: AttendanceSession, window: int) -> str:
    """6-digit code for manual entry when the camera cannot read the QR."""
    return f"{int.from_bytes(_mac(session, window)[10:14], 'big') % 1_000_000:06d}"


def issue_ticket(session: AttendanceSession, user_id: int, at=None) -> str:
    """A scan ticket: proof that this user scanned a valid code of this session at this time.

    The slow parts of a check-in (location fix, live photo, upload on a weak network) can then
    take longer than the code's 15 seconds without the student being refused. The ticket is
    bound to the user and the session, so it cannot be handed to someone else."""
    issued = int((at or utcnow()).timestamp())
    mac = hmac.new(session.secret.encode(), f"ticket:{user_id}:{session.id}:{issued}".encode(), hashlib.sha256)
    return f"{issued}.{mac.hexdigest()[:32]}"


def verify_ticket(session: AttendanceSession, user_id: int, ticket: str, max_age_seconds: int) -> bool:
    try:
        issued_s, sig = ticket.split(".", 1)
        issued = int(issued_s)
    except ValueError:
        return False
    now = int(utcnow().timestamp())
    if issued > now + 5 or now - issued > max_age_seconds:
        return False
    expected = issue_ticket(session, user_id, datetime.fromtimestamp(issued, timezone.utc)).split(".", 1)[1]
    return hmac.compare_digest(expected, sig)


def qr_state(session: AttendanceSession) -> dict:
    now = utcnow()
    window = current_window(session, now)
    expires_in = session.rotation_seconds - (now.timestamp() % session.rotation_seconds)
    return {
        "payload": f"{QR_PREFIX}:{session.id}:{window}:{token_for(session, window)}",
        "short_code": short_code_for(session, window),
        "window": window,
        "expires_in": round(expires_in, 1),
        "rotation_seconds": session.rotation_seconds,
    }


def parse_payload(payload: str) -> tuple[int, int, str]:
    try:
        prefix, sid, window, token = payload.strip().split(":")
        if prefix != QR_PREFIX:
            raise ValueError
        return int(sid), int(window), token
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="رمز QR غير صالح") from exc


def verify_code(session: AttendanceSession, *, window: int | None, token: str | None,
                short_code: str | None) -> bool:
    now_window = current_window(session)
    for w in (now_window, now_window - 1):
        if token is not None and window == w and hmac.compare_digest(token_for(session, w), token):
            return True
        if short_code is not None and hmac.compare_digest(short_code_for(session, w), short_code.strip()):
            return True
    return False


# --------------------------------------------------------------------------- policy


def policy_for(db: Session, university_id: int, faculty=None) -> dict:
    return effective_settings(db.get(University, university_id), faculty)["attendance"]


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- integrity


def _record_material(rec: AttendanceRecord) -> str:
    return json.dumps(
        [rec.university_id, rec.session_id, rec.user_id, rec.method, rec.initial_status,
         rec.check_in_at.isoformat() if rec.check_in_at else None, rec.device_id,
         rec.latitude, rec.longitude, rec.created_at.isoformat()],
        sort_keys=True, ensure_ascii=False,
    )


def _seal(db: Session, rec: AttendanceRecord) -> None:
    with _chain_lock:
        prev = db.scalar(select(AttendanceRecord.record_hash).order_by(AttendanceRecord.id.desc()).limit(1))
        rec.prev_hash = prev
        rec.record_hash = hashlib.sha256(((prev or "") + _record_material(rec)).encode()).hexdigest()
        db.add(rec)
        db.flush()


def verify_integrity(db: Session) -> dict:
    """Check the hash chain and that each status is explained by its change log."""
    prev = None
    problems = []
    records = db.scalars(select(AttendanceRecord).order_by(AttendanceRecord.id)).all()
    for rec in records:
        expected = hashlib.sha256(((prev or "") + _record_material(rec)).encode()).hexdigest()
        if rec.prev_hash != prev or rec.record_hash != expected:
            problems.append({"record_id": rec.id, "problem": "hash_mismatch"})
        status = rec.initial_status
        for ch in db.scalars(
            select(AttendanceChange).where(AttendanceChange.record_id == rec.id).order_by(AttendanceChange.id)
        ):
            status = ch.new_status
        if status != rec.status:
            problems.append({"record_id": rec.id, "problem": "status_without_change_log"})
        prev = rec.record_hash
    return {"ok": not problems, "checked": len(records), "problems": problems[:50]}


def change_status(db: Session, rec: AttendanceRecord, actor: User | None, new_status: str, reason: str,
                  *, ip: str | None = None) -> None:
    if new_status not in STATUSES:
        raise HTTPException(status_code=400, detail="حالة غير صحيحة")
    if not reason or len(reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="يجب ذكر سبب التعديل")
    old = rec.status
    if old == new_status:
        return
    rec.status = new_status
    db.add(AttendanceChange(record_id=rec.id, actor_id=actor.id if actor else None, old_status=old,
                            new_status=new_status, reason=reason.strip()))
    audit.record(db, "attendance.change", actor=actor, university_id=rec.university_id,
                 target_type="attendance_record", target_id=rec.id,
                 details={"old": old, "new": new_status, "reason": reason.strip(), "user_id": rec.user_id}, ip=ip)


# --------------------------------------------------------------------------- check-in


def eligible(db: Session, user: User, session: AttendanceSession) -> bool:
    if user.university_id != session.university_id:
        return False
    if session.kind == "course":
        return user.role == Role.STUDENT and db.scalar(
            select(Enrollment.id).where(Enrollment.course_id == session.course_id,
                                        Enrollment.student_id == user.id, Enrollment.status == "active")
        ) is not None
    return user.role in Role.EMPLOYEES and (session.faculty_id is None or user.faculty_id == session.faculty_id)


def check_in(db: Session, user: User, *, payload: str | None, short_code: str | None, session_id: int | None,
             nonce: str, device_id: str | None, latitude: float | None, longitude: float | None,
             selfie: bytes | None, ip: str | None, ticket: str | None = None) -> AttendanceRecord:
    if not limiter.hit(f"checkin:{user.id}", 10, 60):
        raise HTTPException(status_code=429, detail="محاولات كثيرة، حاول بعد قليل")
    if not nonce or not (16 <= len(nonce) <= 80):
        raise HTTPException(status_code=400, detail="معرف الطلب غير صالح")

    window = token = None
    if payload:
        session_id, window, token = parse_payload(payload)
    elif not ((short_code or ticket) and session_id):
        raise HTTPException(status_code=400, detail="أدخل رمز الحضور")

    session = db.get(AttendanceSession, session_id)
    if not session or session.university_id != user.university_id:
        raise HTTPException(status_code=404, detail="جلسة الحضور غير موجودة")

    # single-use request id: stops replay of a captured request
    if db.scalar(select(AttendanceNonce.id).where(AttendanceNonce.nonce == nonce)):
        raise HTTPException(status_code=409, detail="تم استخدام هذا الطلب من قبل")
    db.add(AttendanceNonce(nonce=nonce, user_id=user.id))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="تم استخدام هذا الطلب من قبل") from exc

    now = utcnow()
    policy = policy_for(db, session.university_id)
    opens = int(policy.get("open_before_minutes", 10))
    if session.status != "open" or now > session.ends_at or now < session.starts_at - timedelta(minutes=opens):
        raise HTTPException(status_code=400, detail="جلسة الحضور مغلقة")
    if not eligible(db, user, session):
        raise HTTPException(status_code=403, detail="أنت غير مسجل في هذه الجلسة")
    if ticket and not payload:
        if not verify_ticket(session, user.id, ticket, int(policy.get("scan_ticket_seconds", 120))):
            raise HTTPException(status_code=400, detail="انتهت مهلة التسجيل بعد المسح، امسح الرمز الحالي مرة أخرى")
    elif not verify_code(session, window=window, token=token, short_code=None if payload else short_code):
        raise HTTPException(status_code=400, detail="رمز الحضور منتهي الصلاحية أو غير صحيح، امسح الرمز الحالي")

    existing = db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id,
                                                        AttendanceRecord.user_id == user.id))
    if existing:
        if session.kind == "staff" and existing.check_out_at is None and existing.check_in_at \
                and now - existing.check_in_at >= timedelta(minutes=1):
            existing.check_out_at = now
            early = int(policy.get("staff_early_leave_minutes", 0))
            if early and now < session.ends_at - timedelta(minutes=early) and "early_leave" not in existing.risk_flags:
                existing.risk_flags = [*existing.risk_flags, "early_leave"]  # a signal for reports, status kept
            db.flush()
            return existing
        raise HTTPException(status_code=409, detail="تم تسجيل حضورك مسبقاً في هذه الجلسة")

    if session.require_location and (latitude is None or longitude is None):
        raise HTTPException(status_code=400, detail="هذه الجلسة تتطلب مشاركة الموقع")
    if session.require_selfie and not selfie:
        raise HTTPException(status_code=400, detail="هذه الجلسة تتطلب التقاط صورة حية")

    weights = {**DEFAULT_SETTINGS["attendance"]["risk_weights"], **(policy.get("risk_weights") or {})}
    score, flags = 0, []
    distance = None
    if latitude is not None and longitude is not None and session.latitude is not None:
        distance = haversine_m(latitude, longitude, session.latitude, session.longitude)
        if distance > session.radius_m:
            score += weights["outside_geofence"]
            flags.append("outside_geofence")
    if not device_id:
        score += weights["no_device_id"]
        flags.append("no_device_id")
    else:
        same_device = db.scalars(select(AttendanceRecord).where(
            AttendanceRecord.session_id == session.id, AttendanceRecord.device_id == device_id,
            AttendanceRecord.user_id != user.id)).all()
        if same_device:
            score += weights["shared_device"]
            flags.append("shared_device")
            for other in same_device:
                if "shared_device" not in other.risk_flags:
                    other.risk_flags = [*other.risk_flags, "shared_device"]  # signal only; record kept intact
                if other.status in ("present", "late"):
                    other.provisional_status = other.status
                    change_status(db, other, None, "pending_review", "جهاز مشترك مع حساب آخر في نفس الجلسة")
        else:
            recent_other = db.scalar(select(func.count(UserDevice.id)).where(
                UserDevice.device_id == device_id, UserDevice.user_id != user.id,
                UserDevice.last_seen >= now - timedelta(days=7)))
            if recent_other:
                score += weights["device_used_by_other_account"]
                flags.append("device_used_by_other_account")
        known = db.scalars(select(UserDevice).where(UserDevice.user_id == user.id)).all()
        mine = next((d for d in known if d.device_id == device_id), None)
        if known and not mine:
            score += weights["new_device"]
            flags.append("new_device")
        if mine:
            mine.last_seen = now
        else:
            db.add(UserDevice(user_id=user.id, device_id=device_id))

    status = "late" if now > session.starts_at + timedelta(minutes=session.late_after_minutes) else "present"
    selfie_file_id = face = None
    if selfie:
        from . import files

        retention = timedelta(days=int(policy.get("selfie_retention_days", 30)))
        f = files.store(db, owner=user, purpose="selfie", filename="live.jpg", data=selfie,
                        allowed_extensions=["jpg", "jpeg", "png"], encrypt=True, delete_after=now + retention)
        selfie_file_id = f.id
        result = get_verifier().verify(user.id, selfie)
        face = result.status
        if result.status in ("no_match", "liveness_failed"):
            score += weights["face_mismatch"]
            flags.append("face_" + result.status)

    provisional = None
    if score >= int(policy.get("review_threshold", 50)):
        provisional, status = status, "pending_review"

    rec = AttendanceRecord(
        university_id=session.university_id, session_id=session.id, user_id=user.id, status=status,
        initial_status=status, provisional_status=provisional, method="qr", check_in_at=now,
        device_id=device_id, ip=ip, latitude=latitude, longitude=longitude,
        distance_m=round(distance, 1) if distance is not None else None, risk_score=score, risk_flags=flags,
        selfie_file_id=selfie_file_id, face_check=face, created_at=now,
    )
    _seal(db, rec)
    return rec


def manual_mark(db: Session, actor: User, session: AttendanceSession, target: User, status: str, reason: str,
                *, ip: str | None = None) -> AttendanceRecord:
    if not eligible(db, target, session):
        raise HTTPException(status_code=400, detail="المستخدم غير مسجل في هذه الجلسة")
    rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id,
                                                   AttendanceRecord.user_id == target.id))
    if rec:
        change_status(db, rec, actor, status, reason, ip=ip)
        rec.reviewed_by, rec.reviewed_at = actor.id, utcnow()
        return rec
    if status not in STATUSES or not reason or len(reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="يجب تحديد الحالة وذكر السبب")
    now = utcnow()
    rec = AttendanceRecord(
        university_id=session.university_id, session_id=session.id, user_id=target.id, status=status,
        initial_status=status, method="manual", check_in_at=now if status in ("present", "late") else None,
        risk_score=0, risk_flags=[], reviewed_by=actor.id, reviewed_at=now, created_at=now,
    )
    _seal(db, rec)
    db.add(AttendanceChange(record_id=rec.id, actor_id=actor.id, old_status=None, new_status=status,
                            reason=reason.strip()))
    audit.record(db, "attendance.manual", actor=actor, target_type="attendance_record", target_id=rec.id,
                 details={"user_id": target.id, "session_id": session.id, "status": status, "reason": reason}, ip=ip)
    return rec


def review(db: Session, actor: User, rec: AttendanceRecord, approve: bool, reason: str, *, ip=None) -> None:
    if rec.status != "pending_review":
        raise HTTPException(status_code=400, detail="السجل ليس قيد المراجعة")
    new_status = (rec.provisional_status or "present") if approve else "rejected"
    change_status(db, rec, actor, new_status, reason, ip=ip)
    rec.reviewed_by, rec.reviewed_at = actor.id, utcnow()


# --------------------------------------------------------------------------- closing & thresholds


def course_absence(db: Session, course_id: int, student_id: int) -> dict:
    sessions = db.scalars(select(AttendanceSession.id).where(
        AttendanceSession.course_id == course_id, AttendanceSession.status == "closed")).all()
    total = len(sessions)
    if not total:
        return {"sessions": 0, "absent": 0, "late": 0, "present": 0, "absence_percent": 0.0}
    rows = db.execute(select(AttendanceRecord.status, func.count()).where(
        AttendanceRecord.session_id.in_(sessions), AttendanceRecord.user_id == student_id
    ).group_by(AttendanceRecord.status)).all()
    by = dict(rows)
    absent = sum(by.get(s, 0) for s in COUNTED_ABSENT) + (total - sum(by.values()))
    return {"sessions": total, "absent": absent, "late": by.get("late", 0),
            "present": by.get("present", 0) + by.get("late", 0), "excused": by.get("excused", 0),
            "pending": by.get("pending_review", 0), "absence_percent": round(100 * absent / total, 1)}


def check_thresholds(db: Session, course: Course) -> int:
    policy = policy_for(db, course.university_id)
    warn, limit = policy["warning_absence_percent"], policy["limit_absence_percent"]
    sent = 0
    students = db.scalars(select(Enrollment.student_id).where(Enrollment.course_id == course.id,
                                                              Enrollment.status == "active")).all()
    instructors = db.scalars(select(CourseStaff.user_id).where(CourseStaff.course_id == course.id)).all()
    fac_admins = db.scalars(select(User.id).where(User.faculty_id == course.faculty_id,
                                                  User.role == Role.FACULTY_ADMIN)).all()
    for sid in students:
        stats = course_absence(db, course.id, sid)
        pct = stats["absence_percent"]
        for level, threshold in (("limit", limit), ("warning", warn)):
            if pct < threshold:
                continue
            exists = db.scalar(select(AttendanceAlert.id).where(
                AttendanceAlert.course_id == course.id, AttendanceAlert.user_id == sid,
                AttendanceAlert.level == level))
            if exists:
                break
            db.add(AttendanceAlert(course_id=course.id, user_id=sid, level=level))
            student = db.get(User, sid)
            if level == "warning":
                notifications.notify_users(
                    db, course.university_id, [sid], f"تنبيه غياب: {course.title}",
                    f"بلغت نسبة غيابك {pct}% في مقرر {course.title}. الحد المسموح {limit}%.",
                    category="system", priority="important", course_id=course.id, link="#/attendance", topic="attendance_alert")
            else:
                notifications.notify_users(
                    db, course.university_id, [sid], f"تجاوز حد الغياب: {course.title}",
                    f"بلغت نسبة غيابك {pct}% في مقرر {course.title} وتجاوزت الحد المعتمد ({limit}%). "
                    "سيتم عرض حالتك على الجهة المختصة للمراجعة.",
                    category="system", priority="urgent", course_id=course.id, link="#/attendance", topic="attendance_alert")
                notifications.notify_users(
                    db, course.university_id, [*instructors, *fac_admins],
                    f"طالب تجاوز حد الغياب: {course.title}",
                    f"الطالب {student.full_name} ({student.code}) بلغت نسبة غيابه {pct}%. "
                    "يحتاج إلى مراجعة واتخاذ الإجراء وفق اللوائح (لا يُتخذ إجراء تلقائي).",
                    category="system", priority="important", course_id=course.id, topic="attendance_alert")
            sent += 1
            break
    return sent


def close_session(db: Session, session: AttendanceSession, actor: User | None = None) -> int:
    """Close a session; enrolled students without a record are marked absent."""
    if session.status == "closed" and session.absences_processed:
        return 0
    session.status = "closed"
    if session.ends_at > utcnow():
        session.ends_at = utcnow()
    created = 0
    if session.kind == "course" and not session.absences_processed:
        have = set(db.scalars(select(AttendanceRecord.user_id).where(AttendanceRecord.session_id == session.id)))
        students = db.scalars(select(Enrollment.student_id).where(
            Enrollment.course_id == session.course_id, Enrollment.status == "active")).all()
        for sid in students:
            if sid in have:
                continue
            now = utcnow()
            _seal(db, AttendanceRecord(
                university_id=session.university_id, session_id=session.id, user_id=sid, status="absent",
                initial_status="absent", method="system", risk_score=0, risk_flags=[], created_at=now))
            created += 1
        session.absences_processed = True
        db.flush()
        check_thresholds(db, db.get(Course, session.course_id))
    session.absences_processed = True
    audit.record(db, "attendance.session_closed", actor=actor, university_id=session.university_id,
                 target_type="attendance_session", target_id=session.id, details={"absent_marked": created})
    return created
