from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import attendance as svc
from .. import audit, files
from ..db import as_utc, get_db, utcnow
from ..deps import (
    client_ip,
    forbidden,
    get_course_for,
    get_current_user,
    not_found,
    visible_course_ids,
)
from ..models import (
    AttendanceChange,
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    Role,
    StoredFile,
    User,
    UserDevice,
)

router = APIRouter(prefix="/api", tags=["attendance"])


def _session_for(db: Session, user: User, sid: int) -> AttendanceSession:
    """Session managed by ``user`` (course instructors / admins in scope)."""
    s = db.get(AttendanceSession, sid)
    if not s or s.university_id != user.university_id:
        raise not_found("جلسة الحضور غير موجودة")
    if s.kind == "course":
        get_course_for(db, user, s.course_id, teach=True)
    elif not (user.role == Role.UNIVERSITY_ADMIN
              or (user.role == Role.FACULTY_ADMIN and s.faculty_id == user.faculty_id)):
        raise forbidden()
    return s


def _session_out(db: Session, s: AttendanceSession) -> dict:
    counts = dict(db.execute(select(AttendanceRecord.status, func.count()).where(
        AttendanceRecord.session_id == s.id).group_by(AttendanceRecord.status)).all())
    course = db.get(Course, s.course_id) if s.course_id else None
    expected = db.scalar(select(func.count(Enrollment.id)).where(
        Enrollment.course_id == s.course_id, Enrollment.status == "active")) if course else None
    return {"id": s.id, "kind": s.kind, "title": s.title, "course_id": s.course_id,
            "course_title": course.title if course else None, "location": s.location,
            "starts_at": s.starts_at, "ends_at": s.ends_at, "status": s.status, "risk_level": s.risk_level,
            "require_location": s.require_location, "require_selfie": s.require_selfie,
            "rotation_seconds": s.rotation_seconds, "late_after_minutes": s.late_after_minutes,
            "has_geofence": s.latitude is not None, "radius_m": s.radius_m,
            "counts": counts, "expected": expected}


class SessionIn(BaseModel):
    kind: str = Field(default="course", pattern="^(course|staff)$")
    course_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=20, le=5000)
    starts_at: datetime | None = None
    duration_minutes: int = Field(default=90, ge=5, le=720)
    risk_level: str = Field(default="normal", pattern="^(normal|high)$")
    require_location: bool | None = None
    require_selfie: bool | None = None
    late_after_minutes: int | None = Field(default=None, ge=0, le=180)


@router.post("/attendance/sessions")
def create_session(body: SessionIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    faculty_id = None
    course = None
    if body.kind == "course":
        if not body.course_id:
            raise HTTPException(status_code=400, detail="حدد المقرر")
        course = get_course_for(db, user, body.course_id, teach=True)
        faculty_id = course.faculty_id
    else:
        if user.role not in (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN):
            raise forbidden("جلسات دوام الموظفين من صلاحيات الإدارة")
        faculty_id = user.faculty_id if user.role == Role.FACULTY_ADMIN else None
    policy = svc.policy_for(db, user.university_id)
    level = policy["levels"].get(body.risk_level, {})
    starts = as_utc(body.starts_at) or utcnow()
    require_location = level.get("require_location", False) if body.require_location is None else body.require_location
    if require_location and body.latitude is None:
        raise HTTPException(status_code=400, detail="التحقق بالموقع يتطلب تحديد إحداثيات القاعة")
    s = AttendanceSession(
        university_id=user.university_id, faculty_id=faculty_id, kind=body.kind,
        course_id=course.id if course else None,
        title=body.title or (f"محاضرة {course.title}" if course else "دوام الموظفين"),
        location=body.location, latitude=body.latitude, longitude=body.longitude,
        radius_m=body.radius_m or policy["default_radius_m"], starts_at=starts,
        ends_at=starts + timedelta(minutes=body.duration_minutes),
        late_after_minutes=policy["late_after_minutes"] if body.late_after_minutes is None else body.late_after_minutes,
        rotation_seconds=int(policy["rotation_seconds"]), risk_level=body.risk_level,
        require_location=require_location,
        require_selfie=level.get("require_selfie", False) if body.require_selfie is None else body.require_selfie,
        secret=svc.new_secret(), created_by=user.id,
    )
    db.add(s)
    db.flush()
    audit.record(db, "attendance.session_created", actor=user, target_type="attendance_session", target_id=s.id,
                 details={"kind": s.kind, "course_id": s.course_id, "risk_level": s.risk_level}, ip=client_ip(request))
    db.commit()
    return _session_out(db, s)


@router.get("/attendance/sessions")
def list_sessions(course_id: int | None = None, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    stmt = select(AttendanceSession).where(AttendanceSession.university_id == user.university_id)
    if user.role in Role.INSTRUCTORS or (user.role in (Role.FACULTY_ADMIN, Role.UNIVERSITY_ADMIN) and course_id):
        ids = visible_course_ids(db, user)
        if course_id:
            if course_id not in ids:
                raise forbidden()
            ids = [course_id]
        stmt = stmt.where(AttendanceSession.course_id.in_(ids or [-1]))
    elif user.role == Role.FACULTY_ADMIN:
        stmt = stmt.where(AttendanceSession.faculty_id == user.faculty_id)
    elif user.role != Role.UNIVERSITY_ADMIN:
        raise forbidden()
    rows = db.scalars(stmt.order_by(AttendanceSession.starts_at.desc()).limit(100)).all()
    return [_session_out(db, s) for s in rows]


@router.get("/attendance/sessions/{sid}")
def get_session(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _session_for(db, user, sid)
    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == s.id)).all()
    by_user = {r.user_id: r for r in records}
    if s.kind == "course":
        people = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(
            Enrollment.course_id == s.course_id, Enrollment.status == "active").order_by(User.full_name)).all()
    else:
        people = db.scalars(select(User).where(User.id.in_(list(by_user) or [-1])).order_by(User.full_name)).all()
    return {**_session_out(db, s), "people": [{
        "user": {"id": p.id, "full_name": p.full_name, "code": p.code},
        "record": _record_out(by_user[p.id]) if p.id in by_user else None} for p in people]}


def _record_out(r: AttendanceRecord) -> dict:
    return {"id": r.id, "status": r.status, "method": r.method, "check_in_at": r.check_in_at,
            "check_out_at": r.check_out_at, "risk_score": r.risk_score, "risk_flags": r.risk_flags,
            "distance_m": r.distance_m, "has_selfie": r.selfie_file_id is not None, "face_check": r.face_check,
            "provisional_status": r.provisional_status}


@router.get("/attendance/sessions/{sid}/qr")
def session_qr(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _session_for(db, user, sid)
    if s.status != "open" or utcnow() > s.ends_at:
        raise HTTPException(status_code=400, detail="الجلسة مغلقة")
    state = svc.qr_state(s)
    img = qrcode.make(state["payload"], image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    state["image"] = "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
    state["present"] = db.scalar(select(func.count(AttendanceRecord.id)).where(
        AttendanceRecord.session_id == s.id, AttendanceRecord.status.in_(["present", "late", "pending_review"])))
    return state


@router.get("/attendance/sessions/{sid}/requirements")
def session_requirements(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What the scanning app must collect for this session (for eligible participants)."""
    s = db.get(AttendanceSession, sid)
    if not s or s.university_id != user.university_id or not svc.eligible(db, user, s):
        raise not_found("جلسة الحضور غير موجودة")
    return {"id": s.id, "title": s.title, "status": s.status, "require_location": s.require_location,
            "require_selfie": s.require_selfie, "has_geofence": s.latitude is not None}


@router.post("/attendance/sessions/{sid}/close")
def close(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _session_for(db, user, sid)
    created = svc.close_session(db, s, user)
    db.commit()
    return {"absent_marked": created, **_session_out(db, s)}


@router.post("/attendance/check-in")
async def check_in(request: Request, payload: str | None = Form(None, max_length=200),
                   short_code: str | None = Form(None, max_length=10), session_id: int | None = Form(None),
                   nonce: str = Form(..., max_length=80), latitude: float | None = Form(None),
                   longitude: float | None = Form(None), selfie: UploadFile | None = File(None),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    selfie_bytes = await files.read_upload(selfie, 3) if selfie is not None else None
    device_id = (request.headers.get("x-device-id") or "")[:100] or None
    rec = svc.check_in(db, user, payload=payload, short_code=short_code, session_id=session_id, nonce=nonce,
                       device_id=device_id, latitude=latitude, longitude=longitude, selfie=selfie_bytes,
                       ip=client_ip(request))
    db.commit()
    s = db.get(AttendanceSession, rec.session_id)
    messages = {
        "present": "تم تسجيل حضورك بنجاح",
        "late": "تم تسجيل حضورك (متأخر)",
        "pending_review": "تم استلام تسجيلك وسيُراجع من المسؤول",
    }
    msg = "تم تسجيل الانصراف" if rec.check_out_at else messages.get(rec.status, "تم التسجيل")
    return {"status": rec.status, "message": msg, "session": s.title, "check_in_at": rec.check_in_at,
            "check_out_at": rec.check_out_at}


class ManualIn(BaseModel):
    user_id: int
    status: str = Field(pattern="^(present|late|absent|excused)$")
    reason: str = Field(min_length=3, max_length=500)


@router.post("/attendance/sessions/{sid}/manual")
def manual(sid: int, body: ManualIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    s = _session_for(db, user, sid)
    target = db.get(User, body.user_id)
    if not target or target.university_id != user.university_id:
        raise not_found()
    rec = svc.manual_mark(db, user, s, target, body.status, body.reason, ip=client_ip(request))
    db.commit()
    return _record_out(rec)


class ReviewIn(BaseModel):
    approve: bool
    reason: str = Field(min_length=3, max_length=500)


def _record_for(db: Session, user: User, rid: int) -> tuple[AttendanceRecord, AttendanceSession]:
    r = db.get(AttendanceRecord, rid)
    if not r or r.university_id != user.university_id:
        raise not_found()
    return r, _session_for(db, user, r.session_id)


@router.post("/attendance/records/{rid}/review")
def review(rid: int, body: ReviewIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    r, _ = _record_for(db, user, rid)
    svc.review(db, user, r, body.approve, body.reason, ip=client_ip(request))
    db.commit()
    return _record_out(r)


@router.get("/attendance/records/{rid}/history")
def record_history(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r, _ = _record_for(db, user, rid)
    rows = db.scalars(select(AttendanceChange).where(AttendanceChange.record_id == r.id)
                      .order_by(AttendanceChange.id)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({c.actor_id for c in rows if c.actor_id})))}
    return [{"old": c.old_status, "new": c.new_status, "reason": c.reason,
             "actor": names.get(c.actor_id, "النظام"), "created_at": c.created_at} for c in rows]


@router.get("/attendance/records/{rid}/selfie")
def record_selfie(rid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r, _ = _record_for(db, user, rid)
    if not r.selfie_file_id:
        raise not_found("لا توجد صورة")
    f = db.get(StoredFile, r.selfie_file_id)
    # every access to biometric-adjacent data is audited
    audit.record(db, "attendance.selfie_viewed", actor=user, target_type="attendance_record", target_id=r.id,
                 ip=client_ip(request))
    db.commit()
    return files.download_response(f, inline=True)


@router.get("/attendance/review-queue")
def review_queue(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(AttendanceRecord, AttendanceSession).join(
        AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(
        AttendanceRecord.university_id == user.university_id, AttendanceRecord.status == "pending_review")
    if user.role in Role.INSTRUCTORS:
        stmt = stmt.where(AttendanceSession.course_id.in_(visible_course_ids(db, user) or [-1]))
    elif user.role == Role.FACULTY_ADMIN:
        stmt = stmt.where(AttendanceSession.faculty_id == user.faculty_id)
    elif user.role != Role.UNIVERSITY_ADMIN:
        raise forbidden()
    rows = db.execute(stmt.order_by(AttendanceRecord.id.desc()).limit(200)).all()
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.user_id for r, _ in rows} or {-1})))}
    return [{"record": _record_out(r), "session": {"id": s.id, "title": s.title, "starts_at": s.starts_at},
             "user": {"id": r.user_id, "full_name": users[r.user_id].full_name, "code": users[r.user_id].code}}
            for r, s in rows]


@router.get("/me/attendance")
def my_attendance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = {"courses": [], "records": []}
    if user.role == Role.STUDENT:
        for cid in visible_course_ids(db, user):
            c = db.get(Course, cid)
            out["courses"].append({"course": {"id": c.id, "code": c.code, "title": c.title},
                                   **svc.course_absence(db, cid, user.id)})
    rows = db.execute(select(AttendanceRecord, AttendanceSession).join(
        AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(
        AttendanceRecord.user_id == user.id).order_by(AttendanceSession.starts_at.desc()).limit(100)).all()
    out["records"] = [{"session": s.title, "kind": s.kind, "starts_at": s.starts_at, "status": r.status,
                       "check_in_at": r.check_in_at, "check_out_at": r.check_out_at, "method": r.method}
                      for r, s in rows]
    return out


@router.get("/attendance/integrity")
def integrity(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.UNIVERSITY_ADMIN:
        raise forbidden()
    return svc.verify_integrity(db)


@router.get("/attendance/anomalies")
def anomalies(days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Patterns worth a human look. These are signals for review, not verdicts."""
    if user.role not in (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, *Role.INSTRUCTORS):
        raise forbidden()
    since = utcnow() - timedelta(days=min(days, 180))
    scope = select(User.id).where(User.university_id == user.university_id)
    if user.role == Role.FACULTY_ADMIN:
        scope = scope.where(User.faculty_id == user.faculty_id)
    elif user.role in Role.INSTRUCTORS:
        scope = select(Enrollment.student_id).where(Enrollment.course_id.in_(visible_course_ids(db, user) or [-1]))
    shared = db.execute(select(UserDevice.device_id, func.count(func.distinct(UserDevice.user_id))).where(
        UserDevice.user_id.in_(scope), UserDevice.last_seen >= since).group_by(UserDevice.device_id).having(
        func.count(func.distinct(UserDevice.user_id)) > 1)).all()
    shared_out = []
    for device_id, n in shared:
        users = db.scalars(select(User).join(UserDevice, UserDevice.user_id == User.id).where(
            UserDevice.device_id == device_id, User.id.in_(scope))).all()
        shared_out.append({"device": device_id[:8] + "…", "accounts": n,
                           "users": [{"id": u.id, "full_name": u.full_name, "code": u.code} for u in users]})
    flagged = db.execute(select(AttendanceRecord.user_id, func.count()).where(
        AttendanceRecord.user_id.in_(scope), AttendanceRecord.created_at >= since,
        AttendanceRecord.risk_score > 0).group_by(AttendanceRecord.user_id).order_by(func.count().desc()).limit(20)).all()
    names = {u.id: u for u in db.scalars(select(User).where(User.id.in_([uid for uid, _ in flagged] or [-1])))}
    return {
        "shared_devices": shared_out,
        "frequently_flagged": [{"user": {"id": uid, "full_name": names[uid].full_name, "code": names[uid].code},
                                "flagged_checkins": n} for uid, n in flagged],
        "pending_review": db.scalar(select(func.count(AttendanceRecord.id)).where(
            AttendanceRecord.user_id.in_(scope), AttendanceRecord.status == "pending_review")),
    }
