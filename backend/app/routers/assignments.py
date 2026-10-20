"""Assignments, research and projects: publishing, submissions and grading."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, files, notifications
from ..db import as_utc, get_db, utcnow
from ..deps import (
    can_teach_course,
    client_ip,
    forbidden,
    get_course_for,
    get_current_user,
    is_enrolled,
    not_found,
    tenant_settings,
    visible_course_ids,
)
from ..models import (
    Assignment,
    Course,
    Enrollment,
    Role,
    Submission,
    SubmissionEvent,
    SubmissionFile,
    User,
)

router = APIRouter(prefix="/api", tags=["assignments"])

KINDS = {"homework", "research", "project", "quiz", "activity"}


def display_status(a: Assignment, s: Submission | None, *, for_student: bool) -> str:
    now = utcnow()
    if s and s.status == "reviewed" and (s.grade_released or not for_student):
        return "reviewed"
    if s and s.status in ("submitted", "reviewed"):
        return "late" if s.is_late else "submitted"
    if now > a.due_at:
        return "late"
    if s and s.version > 0:
        return "in_progress"
    return "not_started"


def assignment_out(a: Assignment, course: Course | None = None) -> dict:
    return {"id": a.id, "course_id": a.course_id, "course_title": course.title if course else None,
            "course_code": course.code if course else None, "title": a.title, "description": a.description,
            "kind": a.kind, "open_at": a.open_at, "due_at": a.due_at, "allow_late": a.allow_late,
            "max_score": a.max_score, "allowed_extensions": a.allowed_extensions, "max_file_mb": a.max_file_mb,
            "status": a.status}


def submission_out(db: Session, s: Submission, *, for_student: bool) -> dict:
    sf = db.scalars(select(SubmissionFile).where(SubmissionFile.submission_id == s.id)
                    .order_by(SubmissionFile.version.desc(), SubmissionFile.id)).all()
    show_grade = not for_student or s.grade_released
    return {
        "id": s.id, "student_id": s.student_id, "status": s.status, "note": s.note, "submitted_at": s.submitted_at,
        "is_late": s.is_late, "version": s.version,
        "score": s.score if show_grade else None, "feedback": s.feedback if show_grade else None,
        "graded_at": s.graded_at if show_grade else None, "grade_released": s.grade_released,
        "files": [{**files.file_info(x.file), "version": x.version} for x in sf],
    }


def _get_assignment(db: Session, user: User, aid: int, *, teach: bool = False) -> tuple[Assignment, Course]:
    a = db.get(Assignment, aid)
    if not a or a.university_id != user.university_id:
        raise not_found("المهمة غير موجودة")
    course = get_course_for(db, user, a.course_id, teach=teach)
    if user.role == Role.STUDENT and (a.status != "published" or a.open_at > utcnow()):
        raise not_found("المهمة غير متاحة")
    return a, course


@router.get("/assignments")
def list_assignments(course_id: int | None = None, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    ids = visible_course_ids(db, user)
    if course_id is not None:
        if course_id not in ids:
            raise forbidden()
        ids = [course_id]
    if not ids:
        return []
    stmt = select(Assignment, Course).join(Course, Course.id == Assignment.course_id).where(Assignment.course_id.in_(ids))
    student = user.role == Role.STUDENT
    if student:
        stmt = stmt.where(Assignment.status == "published", Assignment.open_at <= utcnow())
    out = []
    for a, c in db.execute(stmt.order_by(Assignment.due_at)).all():
        item = assignment_out(a, c)
        if student:
            s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.student_id == user.id))
            item["my_status"] = display_status(a, s, for_student=True)
            item["my_score"] = s.score if s and s.grade_released else None
        else:
            enrolled = db.scalar(select(func.count(Enrollment.id)).where(Enrollment.course_id == c.id,
                                                                         Enrollment.status == "active"))
            subs = db.execute(select(Submission.status, func.count()).where(Submission.assignment_id == a.id)
                              .group_by(Submission.status)).all()
            by = dict(subs)
            item["stats"] = {"enrolled": enrolled, "submitted": by.get("submitted", 0) + by.get("reviewed", 0),
                             "reviewed": by.get("reviewed", 0)}
        out.append(item)
    return out


class AssignmentIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=10000)
    kind: str = "homework"
    open_at: datetime | None = None
    due_at: datetime
    allow_late: bool = True
    max_score: float = Field(default=10, gt=0, le=1000)
    allowed_extensions: list[str] | None = None
    max_file_mb: int = Field(default=10, ge=1, le=100)
    publish: bool = True


@router.post("/courses/{course_id}/assignments")
def create_assignment(course_id: int, body: AssignmentIn, request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail="نوع المهمة غير صحيح")
    cfg = tenant_settings(db, user)["uploads"]
    allowed = [e.lower().lstrip(".") for e in (body.allowed_extensions or ["pdf", "docx", "jpg", "jpeg", "png", "txt"])]
    bad = [e for e in allowed if e not in cfg["allowed_extensions"]]
    if bad:
        raise HTTPException(status_code=400, detail=f"امتدادات غير مسموحة: {', '.join(bad)}")
    open_at = as_utc(body.open_at) or utcnow()
    due_at = as_utc(body.due_at)
    if due_at <= open_at:
        raise HTTPException(status_code=400, detail="موعد التسليم يجب أن يكون بعد تاريخ الفتح")
    a = Assignment(university_id=course.university_id, course_id=course.id, created_by=user.id, title=body.title,
                   description=body.description, kind=body.kind, open_at=open_at, due_at=due_at,
                   allow_late=body.allow_late, max_score=body.max_score, allowed_extensions=allowed,
                   max_file_mb=min(body.max_file_mb, cfg["max_file_mb"]),
                   status="published" if body.publish else "draft")
    db.add(a)
    db.flush()
    if a.status == "published":
        _announce(db, user, a, course)
    audit.record(db, "assignment.created", actor=user, target_type="assignment", target_id=a.id,
                 ip=client_ip(request))
    db.commit()
    return assignment_out(a, course)


def _announce(db: Session, sender: User, a: Assignment, course: Course) -> None:
    notifications.create(
        db, sender=sender, university_id=course.university_id, category="announcement",
        title=f"مهمة جديدة: {a.title}", body=f"مقرر {course.title} — آخر موعد للتسليم {a.due_at:%Y-%m-%d %H:%M} UTC",
        target_type="course", target_ids=[course.id], course_id=course.id, link=f"#/assignments/{a.id}",
        priority="normal", scheduled_at=a.open_at if a.open_at > utcnow() else None, automatic=True,
    )


class AssignmentPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_at: datetime | None = None
    allow_late: bool | None = None
    status: str | None = Field(default=None, pattern="^(draft|published|archived)$")


@router.patch("/assignments/{aid}")
def patch_assignment(aid: int, body: AssignmentPatch, request: Request, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    a, course = _get_assignment(db, user, aid, teach=True)
    data = body.model_dump(exclude_unset=True)
    was_draft = a.status == "draft"
    old_due = a.due_at
    if "due_at" in data:
        data["due_at"] = as_utc(data["due_at"])
    for k, v in data.items():
        setattr(a, k, v)
    if was_draft and a.status == "published":
        _announce(db, user, a, course)
    elif "due_at" in data and a.due_at != old_due and a.status == "published":
        a.reminder_sent = False
        notifications.create(
            db, sender=user, university_id=course.university_id, category="announcement", priority="important",
            title=f"تغيير موعد التسليم: {a.title}", body=f"الموعد الجديد {a.due_at:%Y-%m-%d %H:%M} UTC",
            target_type="course", target_ids=[course.id], course_id=course.id, link=f"#/assignments/{a.id}",
            automatic=True)
    audit.record(db, "assignment.updated", actor=user, target_type="assignment", target_id=a.id,
                 details={"fields": sorted(data)}, ip=client_ip(request))
    db.commit()
    return assignment_out(a, course)


@router.get("/assignments/{aid}")
def get_assignment(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a, course = _get_assignment(db, user, aid)
    out = assignment_out(a, course)
    if user.role == Role.STUDENT:
        s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.student_id == user.id))
        out["my_status"] = display_status(a, s, for_student=True)
        out["submission"] = submission_out(db, s, for_student=True) if s else None
    elif can_teach_course(db, user, course):
        students = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(
            Enrollment.course_id == course.id, Enrollment.status == "active").order_by(User.full_name)).all()
        subs = {s.student_id: s for s in db.scalars(select(Submission).where(Submission.assignment_id == a.id))}
        out["submissions"] = [{
            "student": {"id": st.id, "full_name": st.full_name, "code": st.code},
            "status": display_status(a, subs.get(st.id), for_student=False),
            "submission": submission_out(db, subs[st.id], for_student=False) if st.id in subs else None,
        } for st in students]
    return out


@router.post("/assignments/{aid}/submission")
async def submit(aid: int, request: Request, final: bool = Form(True), note: str = Form("", max_length=2000),
                 upload: list[UploadFile] = File(default_factory=list), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if user.role != Role.STUDENT:
        raise forbidden("التسليم متاح للطلبة فقط")
    a, course = _get_assignment(db, user, aid)
    if not is_enrolled(db, user.id, course.id):
        raise forbidden()
    now = utcnow()
    late = now > a.due_at
    if late and not a.allow_late:
        raise HTTPException(status_code=400, detail="انتهى موعد التسليم")
    if len(upload) > 5:
        raise HTTPException(status_code=400, detail="الحد الأقصى 5 ملفات")
    s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.student_id == user.id))
    if s and s.status == "reviewed":
        raise HTTPException(status_code=400, detail="تمت مراجعة التسليم ولا يمكن تعديله")
    if not s:
        s = Submission(assignment_id=a.id, student_id=user.id, status="in_progress", version=0)
        db.add(s)
        db.flush()
    if not upload and not db.scalar(select(SubmissionFile.id).where(SubmissionFile.submission_id == s.id)):
        raise HTTPException(status_code=400, detail="أرفق ملفاً واحداً على الأقل")
    stored = []
    if upload:
        s.version += 1
        for up in upload:
            data = await files.read_upload(up, a.max_file_mb)
            f = files.store(db, owner=user, purpose="submission", filename=up.filename or "file", data=data,
                            allowed_extensions=a.allowed_extensions)
            db.add(SubmissionFile(submission_id=s.id, file_id=f.id, version=s.version))
            stored.append({"id": f.id, "name": f.original_name, "sha256": f.sha256})
    s.note = note
    if final:
        s.status, s.submitted_at, s.is_late = "submitted", now, late
    db.add(SubmissionEvent(submission_id=s.id, actor_id=user.id, action="submitted" if final else "saved",
                           details={"version": s.version, "files": stored, "late": late}))
    db.commit()
    return submission_out(db, s, for_student=True)


class GradeIn(BaseModel):
    score: float = Field(ge=0)
    feedback: str = Field(default="", max_length=5000)
    release: bool = False
    reason: str = Field(default="", max_length=500)


@router.post("/submissions/{sid}/grade")
def grade_submission(sid: int, body: GradeIn, request: Request, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if not s:
        raise not_found()
    a, course = _get_assignment(db, user, s.assignment_id, teach=True)
    if body.score > a.max_score:
        raise HTTPException(status_code=400, detail=f"الدرجة القصوى {a.max_score}")
    if s.status == "in_progress":
        raise HTTPException(status_code=400, detail="لم يسلّم الطالب بعد")
    if s.score is not None and s.score != body.score and len(body.reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="تعديل درجة مسجلة يتطلب ذكر السبب")
    old = s.score
    s.score, s.feedback, s.status = body.score, body.feedback, "reviewed"
    s.graded_by, s.graded_at = user.id, utcnow()
    db.add(SubmissionEvent(submission_id=s.id, actor_id=user.id, action="graded",
                           details={"old": old, "new": body.score, "reason": body.reason}))
    if old is not None and old != body.score:
        audit.record(db, "submission.regraded", actor=user, target_type="submission", target_id=s.id,
                     details={"old": old, "new": body.score, "reason": body.reason}, ip=client_ip(request))
    if body.release and not s.grade_released:
        _release(db, user, a, course, [s])
    db.commit()
    return submission_out(db, s, for_student=False)


def _release(db: Session, user: User, a: Assignment, course: Course, subs: list[Submission]) -> None:
    for s in subs:
        s.grade_released = True
    notifications.notify_users(
        db, course.university_id, [s.student_id for s in subs], f"تم تقييم: {a.title}",
        f"صدرت درجة وملاحظات المهمة في مقرر {course.title}.", category="academic_note",
        course_id=course.id, link=f"#/assignments/{a.id}", sender=user)


@router.post("/assignments/{aid}/release-grades")
def release_grades(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a, course = _get_assignment(db, user, aid, teach=True)
    subs = db.scalars(select(Submission).where(Submission.assignment_id == a.id, Submission.status == "reviewed",
                                               Submission.grade_released.is_(False))).all()
    if subs:
        _release(db, user, a, course, list(subs))
    db.commit()
    return {"released": len(subs)}


@router.get("/submissions/{sid}/history")
def submission_history(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if not s:
        raise not_found()
    a, course = _get_assignment(db, user, s.assignment_id)
    if user.role == Role.STUDENT and s.student_id != user.id:
        raise forbidden()
    if user.role != Role.STUDENT and not can_teach_course(db, user, course):
        raise forbidden()
    events = db.scalars(select(SubmissionEvent).where(SubmissionEvent.submission_id == s.id)
                        .order_by(SubmissionEvent.id)).all()
    return [{"action": e.action, "details": e.details if user.role != Role.STUDENT or e.action != "graded" else {},
             "created_at": e.created_at} for e in events]
