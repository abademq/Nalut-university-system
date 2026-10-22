"""Reports and statistics, always limited to the caller's scope."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import attendance as att
from .. import grades as grade_svc
from ..db import get_db, utcnow
from ..deps import forbidden, get_course_for, get_current_user, tenant_settings, visible_course_ids
from ..models import (
    Assignment,
    AttendanceRecord,
    AttendanceSession,
    Course,
    Department,
    Enrollment,
    Faculty,
    Role,
    ServiceRequest,
    Submission,
    User,
)

router = APIRouter(prefix="/api", tags=["reports"])

REPORT_ROLES = (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.TEACHER, Role.ASSISTANT)


def _pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


def course_stats(db: Session, course: Course, since=None) -> dict:
    enrolled = db.scalar(select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id,
                                                                 Enrollment.status == "active")) or 0
    sess_q = select(AttendanceSession.id).where(AttendanceSession.course_id == course.id,
                                                AttendanceSession.status == "closed")
    if since:
        sess_q = sess_q.where(AttendanceSession.starts_at >= since)
    sessions = db.scalars(sess_q).all()
    by = dict(db.execute(select(AttendanceRecord.status, func.count()).where(
        AttendanceRecord.session_id.in_(sessions or [-1])).group_by(AttendanceRecord.status)).all())
    attended = by.get("present", 0) + by.get("late", 0) + by.get("excused", 0)
    counted = sum(v for k, v in by.items() if k != "pending_review")
    assignments = db.scalars(select(Assignment).where(Assignment.course_id == course.id,
                                                      Assignment.status == "published",
                                                      Assignment.due_at <= utcnow())).all()
    expected = enrolled * len(assignments)
    subs = db.scalars(select(Submission).where(Submission.assignment_id.in_([a.id for a in assignments] or [-1]),
                                               Submission.status.in_(["submitted", "reviewed"]))).all()
    max_by = {a.id: a.max_score for a in assignments}
    scored = [100 * s.score / max_by[s.assignment_id] for s in subs if s.score is not None]
    return {
        "course": {"id": course.id, "code": course.code, "title": course.title, "faculty_id": course.faculty_id,
                   "department_id": course.department_id},
        "enrolled": enrolled, "sessions": len(sessions), "attendance_rate": _pct(attended, counted),
        "late": by.get("late", 0), "absent": by.get("absent", 0) + by.get("rejected", 0),
        "assignments_due": len(assignments), "submission_rate": _pct(len(subs), expected),
        "avg_score_percent": round(sum(scored) / len(scored), 1) if scored else None,
        "result_status": grade_svc.result_for(db, course.id).status,
    }


def _student_risk(db: Session, course: Course, student_id: int, att_policy: dict, grading: dict) -> list[str]:
    reasons = []
    absence = att.course_absence(db, course.id, student_id)
    if absence["sessions"] and absence["absence_percent"] >= att_policy["warning_absence_percent"]:
        reasons.append(f"غياب {absence['absence_percent']}%")
    due = db.scalars(select(Assignment).where(Assignment.course_id == course.id, Assignment.status == "published",
                                              Assignment.due_at <= utcnow())).all()
    if due:
        subs = {s.assignment_id: s for s in db.scalars(select(Submission).where(
            Submission.student_id == student_id, Submission.assignment_id.in_([a.id for a in due])))}
        missing = sum(1 for a in due if a.id not in subs or subs[a.id].status == "in_progress")
        if missing >= 2 or (missing and missing == len(due)):
            reasons.append(f"{missing} مهام غير مسلمة")
        scored = [100 * subs[a.id].score / a.max_score for a in due if a.id in subs and subs[a.id].score is not None]
        if scored and sum(scored) / len(scored) < grading["low_performance_percent"]:
            reasons.append(f"متوسط الدرجات {round(sum(scored) / len(scored), 1)}%")
    return reasons


def _scoped_courses(db: Session, user: User) -> list[Course]:
    if user.role not in REPORT_ROLES:
        raise forbidden()
    ids = visible_course_ids(db, user)
    return list(db.scalars(select(Course).where(Course.id.in_(ids)).order_by(Course.code))) if ids else []


@router.get("/reports/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courses = _scoped_courses(db, user)
    since = utcnow() - timedelta(days=30)
    stats = [course_stats(db, c, since) for c in courses]
    people = select(User.role, func.count()).where(User.university_id == user.university_id, User.is_active.is_(True))
    if user.role == Role.FACULTY_ADMIN:
        people = people.where(User.faculty_id == user.faculty_id)
    counts = dict(db.execute(people.group_by(User.role)).all()) if user.role in Role.ADMINS else {}

    def agg(items: list[dict]) -> dict:
        def wavg(key, weight):
            pairs = [(s[key], s[weight]) for s in items if s[key] is not None and s[weight]]
            total = sum(w for _, w in pairs)
            return round(sum(v * w for v, w in pairs) / total, 1) if total else None
        return {"courses": len(items), "enrolments": sum(s["enrolled"] for s in items),
                "attendance_rate": wavg("attendance_rate", "sessions"),
                "submission_rate": wavg("submission_rate", "assignments_due"),
                "avg_score_percent": wavg("avg_score_percent", "enrolled")}

    breakdown = []
    if user.role == Role.UNIVERSITY_ADMIN:
        for f in db.scalars(select(Faculty).where(Faculty.university_id == user.university_id)):
            items = [s for s in stats if s["course"]["faculty_id"] == f.id]
            students = db.scalar(select(func.count(User.id)).where(User.faculty_id == f.id, User.role == Role.STUDENT))
            breakdown.append({"id": f.id, "name": f.name, "students": students, **agg(items)})
    elif user.role == Role.FACULTY_ADMIN:
        for d in db.scalars(select(Department).where(Department.faculty_id == user.faculty_id)):
            items = [s for s in stats if s["course"]["department_id"] == d.id]
            students = db.scalar(select(func.count(User.id)).where(User.department_id == d.id,
                                                                   User.role == Role.STUDENT))
            breakdown.append({"id": d.id, "name": d.name, "students": students, **agg(items)})

    pending_review = db.scalar(select(func.count(AttendanceRecord.id)).join(
        AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(
        AttendanceSession.course_id.in_([c.id for c in courses] or [-1]), AttendanceRecord.status == "pending_review"))
    req_q = select(func.count(ServiceRequest.id)).where(ServiceRequest.university_id == user.university_id,
                                                        ServiceRequest.status.not_in(["approved", "rejected"]))
    if user.role == Role.FACULTY_ADMIN:
        req_q = req_q.where(ServiceRequest.faculty_id == user.faculty_id)
    return {
        "people": {"students": counts.get(Role.STUDENT, 0),
                   "teaching": counts.get(Role.TEACHER, 0) + counts.get(Role.ASSISTANT, 0),
                   "staff": counts.get(Role.STAFF, 0) + counts.get(Role.FACULTY_ADMIN, 0)
                   + counts.get(Role.UNIVERSITY_ADMIN, 0)},
        "totals": agg(stats),
        "breakdown": breakdown,
        "courses": stats,
        "pending_attendance_reviews": pending_review,
        "results_awaiting_approval": sum(1 for s in stats if s["result_status"] == "submitted"),
        "open_requests": db.scalar(req_q) if user.role in Role.ADMINS else None,
    }


@router.get("/reports/at-risk")
def at_risk(course_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Students that may need follow-up. A signal for a human advisor, never an automatic decision."""
    courses = _scoped_courses(db, user)
    if course_id:
        courses = [c for c in courses if c.id == course_id]
    cfg = tenant_settings(db, user)
    out = []
    for c in courses:
        students = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(
            Enrollment.course_id == c.id, Enrollment.status == "active")).all()
        for s in students:
            reasons = _student_risk(db, c, s.id, cfg["attendance"], cfg["grading"])
            if reasons:
                out.append({"student": {"id": s.id, "full_name": s.full_name, "code": s.code},
                            "course": {"id": c.id, "code": c.code, "title": c.title}, "reasons": reasons})
    return out


@router.get("/reports/attendance")
def attendance_report(course_id: int | None = None, period: str = Query(default="day", pattern="^(day|week|month)$"),
                      days: int = Query(default=30, ge=1, le=366), format: str = "json",
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courses = _scoped_courses(db, user)
    if course_id:
        get_course_for(db, user, course_id, teach=True)
        courses = [c for c in courses if c.id == course_id]
    since = utcnow() - timedelta(days=days)
    rows = db.execute(select(AttendanceSession.starts_at, AttendanceRecord.status).join(
        AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id).where(
        AttendanceSession.course_id.in_([c.id for c in courses] or [-1]), AttendanceSession.starts_at >= since)).all()
    buckets: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for starts, status in rows:
        if period == "day":
            key = starts.strftime("%Y-%m-%d")
        elif period == "week":
            iso = starts.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        else:
            key = starts.strftime("%Y-%m")
        buckets[key][status] += 1
    out = []
    for key in sorted(buckets):
        b = buckets[key]
        attended = b["present"] + b["late"] + b["excused"]
        counted = sum(v for k, v in b.items() if k != "pending_review")
        out.append({"period": key, "present": b["present"], "late": b["late"], "absent": b["absent"] + b["rejected"],
                    "excused": b["excused"], "pending": b["pending_review"], "rate": _pct(attended, counted)})
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["period", "present", "late", "absent", "excused", "pending", "attendance_rate"])
        for r in out:
            w.writerow([r["period"], r["present"], r["late"], r["absent"], r["excused"], r["pending"], r["rate"]])
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=attendance-report.csv"})
    return out


@router.get("/reports/staff-attendance")
def staff_attendance(days: int = Query(default=30, ge=1, le=366), user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if user.role not in (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN):
        raise forbidden()
    since = utcnow() - timedelta(days=days)
    stmt = select(AttendanceRecord, AttendanceSession).join(
        AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(
        AttendanceSession.university_id == user.university_id, AttendanceSession.kind == "staff",
        AttendanceSession.starts_at >= since)
    if user.role == Role.FACULTY_ADMIN:
        stmt = stmt.where(AttendanceSession.faculty_id == user.faculty_id)
    per: dict[int, dict] = {}
    for r, s in db.execute(stmt).all():
        p = per.setdefault(r.user_id, {"days": 0, "late": 0, "hours": 0.0, "pending": 0})
        p["days"] += 1
        p["late"] += r.status == "late"
        p["pending"] += r.status == "pending_review"
        if r.check_in_at and r.check_out_at:
            p["hours"] += (r.check_out_at - r.check_in_at).total_seconds() / 3600
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(per) or [-1])))}
    return [{"user": {"id": uid, "full_name": users[uid].full_name, "role": users[uid].role},
             **{**v, "hours": round(v["hours"], 1)}} for uid, v in per.items()]


@router.get("/me/insights")
def my_insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rule-based hints for a student about where to focus (no automated decisions)."""
    if user.role != Role.STUDENT:
        raise forbidden()
    cfg = tenant_settings(db, user)
    tips = []
    for cid in visible_course_ids(db, user):
        c = db.get(Course, cid)
        reasons = _student_risk(db, c, user.id, cfg["attendance"], cfg["grading"])
        if reasons:
            tips.append({"course": {"id": c.id, "title": c.title}, "reasons": reasons})
    upcoming = db.execute(select(Assignment, Course).join(Course, Course.id == Assignment.course_id).where(
        Assignment.course_id.in_(visible_course_ids(db, user) or [-1]), Assignment.status == "published",
        Assignment.open_at <= utcnow(), Assignment.due_at > utcnow(),
        Assignment.due_at <= utcnow() + timedelta(days=7)).order_by(Assignment.due_at)).all()
    pending = []
    for a, c in upcoming:
        s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.student_id == user.id))
        if not s or s.status == "in_progress":
            pending.append({"id": a.id, "title": a.title, "course": c.title, "due_at": a.due_at})
    return {"attention": tips, "due_soon": pending}


# --------------------------------------------------------------------------- one person, simplified


def _can_see_person(db: Session, viewer: User, target: User) -> bool:
    if viewer.id == target.id:
        return True
    if viewer.university_id != target.university_id:
        return False
    if viewer.role == Role.UNIVERSITY_ADMIN:
        return True
    if viewer.role == Role.FACULTY_ADMIN:
        return target.faculty_id == viewer.faculty_id
    if viewer.role in Role.INSTRUCTORS and target.role == Role.STUDENT:
        return bool(set(visible_course_ids(db, viewer)) & _enrolled_ids(db, target.id))
    return False


def _enrolled_ids(db: Session, student_id: int) -> set[int]:
    return set(db.scalars(select(Enrollment.course_id).where(Enrollment.student_id == student_id,
                                                             Enrollment.status == "active")))


def _student_report(db: Session, viewer: User, s: User) -> dict:
    ids = _enrolled_ids(db, s.id)
    if viewer.role in Role.INSTRUCTORS:
        ids &= set(visible_course_ids(db, viewer))  # a teacher sees only the courses they share
    cfg = tenant_settings(db, s)
    staff_view = viewer.id != s.id
    courses = []
    for c in db.scalars(select(Course).where(Course.id.in_(ids or [-1])).order_by(Course.code)):
        absence = att.course_absence(db, c.id, s.id)
        due = db.scalars(select(Assignment).where(Assignment.course_id == c.id, Assignment.status == "published",
                                                  Assignment.due_at <= utcnow())).all()
        subs = {x.assignment_id: x for x in db.scalars(select(Submission).where(
            Submission.student_id == s.id, Submission.assignment_id.in_([a.id for a in due] or [-1])))}
        done = sum(1 for a in due if a.id in subs and subs[a.id].status in ("submitted", "reviewed"))
        scored = [100 * subs[a.id].score / a.max_score for a in due
                  if a.id in subs and subs[a.id].score is not None and subs[a.id].grade_released]
        res = grade_svc.result_for(db, c.id)
        summary = grade_svc.student_summary(db, c, s.id, cfg["grading"])
        published = res.status == "published"
        courses.append({
            "course": {"id": c.id, "code": c.code, "title": c.title},
            "absence_percent": absence["absence_percent"], "sessions": absence["sessions"],
            "late": absence["late"], "submitted": done, "due": len(due),
            "avg_score_percent": round(sum(scored) / len(scored), 1) if scored else None,
            "grade": {"letter": summary["letter"], "label": summary["label"], "percent": summary["percent"]}
            if published else None,
            # running total before publication, for the course's staff and administration only
            "running_percent": summary["percent"] if staff_view and not published else None,
            "alerts": _student_risk(db, c, s.id, cfg["attendance"], cfg["grading"]),
        })
    due_total = sum(c["due"] for c in courses)
    scores = [c["avg_score_percent"] for c in courses if c["avg_score_percent"] is not None]
    return {"kind": "student", "summary": {
        "courses": len(courses),
        "absence_percent": round(sum(c["absence_percent"] for c in courses) / len(courses), 1) if courses else None,
        "submission_rate": _pct(sum(c["submitted"] for c in courses), due_total),
        "avg_score_percent": round(sum(scores) / len(scores), 1) if scores else None,
        "alerts": sum(len(c["alerts"]) for c in courses)}, "courses": courses}


def _teacher_report(db: Session, t: User) -> dict:
    since = utcnow() - timedelta(days=30)
    courses = list(db.scalars(select(Course).where(Course.id.in_(visible_course_ids(db, t) or [-1])).order_by(Course.code)))
    stats = [course_stats(db, c) for c in courses]
    held = db.scalar(select(func.count(AttendanceSession.id)).where(
        AttendanceSession.course_id.in_([c.id for c in courses] or [-1]), AttendanceSession.starts_at >= since)) or 0
    pending = db.scalar(select(func.count(AttendanceRecord.id)).join(
        AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(
        AttendanceSession.course_id.in_([c.id for c in courses] or [-1]),
        AttendanceRecord.status == "pending_review")) or 0
    rates = [s["attendance_rate"] for s in stats if s["attendance_rate"] is not None]
    subs = [s["submission_rate"] for s in stats if s["submission_rate"] is not None]
    return {"kind": "teacher", "summary": {
        "courses": len(stats), "students": sum(s["enrolled"] for s in stats), "sessions_30d": held,
        "pending_reviews": pending, "attendance_rate": round(sum(rates) / len(rates), 1) if rates else None,
        "submission_rate": round(sum(subs) / len(subs), 1) if subs else None},
        "courses": stats}


def _staff_report(db: Session, u: User) -> dict:
    from ..models import ServiceRequestEvent

    since = utcnow() - timedelta(days=30)
    rows = db.execute(select(AttendanceRecord.status, AttendanceSession.starts_at).join(
        AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(
        AttendanceRecord.user_id == u.id, AttendanceSession.kind == "staff",
        AttendanceSession.starts_at >= since)).all()
    handled = db.scalar(select(func.count(ServiceRequestEvent.id)).where(
        ServiceRequestEvent.actor_id == u.id, ServiceRequestEvent.created_at >= since,
        ServiceRequestEvent.action.in_(["in_review", "needs_documents", "forwarded", "approved", "rejected"]))) or 0
    open_q = select(func.count(ServiceRequest.id)).where(ServiceRequest.university_id == u.university_id,
                                                         ServiceRequest.status.not_in(["approved", "rejected"]))
    if u.role == Role.STAFF:
        open_q = open_q.where(ServiceRequest.office == u.office)
    if u.faculty_id:
        open_q = open_q.where(ServiceRequest.faculty_id == u.faculty_id)
    return {"kind": "staff", "summary": {
        "days_present_30d": sum(1 for st, _ in rows if st in ("present", "late")),
        "late_30d": sum(1 for st, _ in rows if st == "late"),
        "requests_handled_30d": handled, "open_requests": db.scalar(open_q) or 0}}


@router.get("/reports/person/{uid}")
def person_report(uid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A short, readable summary of one student, teacher or staff member (or yourself)."""
    target = db.get(User, uid)
    if not target or not _can_see_person(db, user, target):
        raise forbidden()
    who = {"id": target.id, "full_name": target.full_name, "role": target.role, "code": target.code}
    if target.role == Role.STUDENT:
        return {"user": who, **_student_report(db, user, target)}
    if target.role in Role.INSTRUCTORS:
        return {"user": who, **_teacher_report(db, target)}
    return {"user": who, **_staff_report(db, target)}
