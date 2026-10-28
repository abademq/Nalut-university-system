"""Official course results: entry, import, approval workflow and publication."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, grades, notifications, permissions
from ..db import get_db, utcnow
from ..deps import (
    client_ip,
    forbidden,
    get_course_for,
    get_current_user,
    is_course_admin,
    not_found,
    tenant_settings,
    visible_course_ids,
)
from ..models import (
    AssessmentComponent,
    Course,
    Enrollment,
    GradeChange,
    GradeImport,
    Role,
    User,
)

router = APIRouter(prefix="/api", tags=["grades"])


def _result_out(res) -> dict:
    return {"status": res.status, "submitted_at": res.submitted_at, "approved_at": res.approved_at,
            "published_at": res.published_at, "note": res.note}


@router.get("/courses/{course_id}/grades")
def course_grades(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    grading = tenant_settings(db, user)["grading"]
    comps = grades.components(db, course.id)
    students = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(
        Enrollment.course_id == course.id, Enrollment.status == "active").order_by(User.full_name)).all()
    return {
        "course": {"id": course.id, "code": course.code, "title": course.title},
        "result": _result_out(grades.result_for(db, course.id)),
        "components": [{"id": c.id, "name": c.name, "max_score": c.max_score} for c in comps],
        "students": [{"id": s.id, "full_name": s.full_name, "code": s.code,
                      **grades.student_summary(db, course, s.id, grading, comps)} for s in students],
    }


class ComponentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    max_score: float = Field(gt=0, le=1000)


@router.post("/courses/{course_id}/components")
def add_component(course_id: int, body: ComponentIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    permissions.require(db, user, "courses.components")
    if grades.result_for(db, course.id).status != "draft":
        raise HTTPException(status_code=400, detail="لا يمكن تعديل عناصر التقييم بعد رفع النتائج")
    n = len(grades.components(db, course.id))
    c = AssessmentComponent(course_id=course.id, name=body.name, max_score=body.max_score, position=n)
    db.add(c)
    db.commit()
    return {"id": c.id}


class EntryIn(BaseModel):
    student_id: int
    component_id: int
    score: float | None = None


class EntriesIn(BaseModel):
    entries: list[EntryIn] = Field(max_length=5000)
    reason: str = Field(default="", max_length=500)


@router.put("/courses/{course_id}/grades")
def save_grades(course_id: int, body: EntriesIn, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    permissions.require(db, user, "grades.enter")
    res = grades.result_for(db, course.id)
    if res.status != "draft":
        raise HTTPException(status_code=400, detail="النتائج مرفوعة للاعتماد؛ يجب إعادتها إلى المسودة أولاً")
    comps = {c.id: c for c in grades.components(db, course.id)}
    enrolled = set(db.scalars(select(Enrollment.student_id).where(Enrollment.course_id == course.id,
                                                                  Enrollment.status == "active")))
    changed = 0
    for e in body.entries:
        if e.component_id not in comps or e.student_id not in enrolled:
            raise HTTPException(status_code=400, detail="طالب أو عنصر تقييم غير صحيح")
        changed += grades.set_score(db, user, course, e.student_id, comps[e.component_id], e.score, body.reason,
                                    ip=client_ip(request))
    db.commit()
    return {"changed": changed}


@router.get("/courses/{course_id}/grades/history")
def grade_history(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    rows = db.scalars(select(GradeChange).where(GradeChange.course_id == course.id)
                      .order_by(GradeChange.id.desc()).limit(500)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({r.actor_id for r in rows} | {r.student_id for r in rows})))}
    comps = {c.id: c.name for c in grades.components(db, course.id)}
    return [{"student": names.get(r.student_id), "component": comps.get(r.component_id), "old": r.old_score,
             "new": r.new_score, "reason": r.reason, "source": r.source, "actor": names.get(r.actor_id),
             "created_at": r.created_at} for r in rows]


@router.post("/courses/{course_id}/grades/import")
async def import_preview(course_id: int, upload: UploadFile = File(...), user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    permissions.require(db, user, "grades.enter")
    data = await files.read_upload(upload, 5)
    rows, errors = grades.parse_import(db, course, upload.filename or "", data)
    imp = GradeImport(course_id=course.id, uploaded_by=user.id, filename=files.safe_filename(upload.filename or ""),
                      rows=rows, errors=errors)
    db.add(imp)
    db.commit()
    return {"id": imp.id, "rows": rows, "errors": errors, "can_commit": not errors and bool(rows)}


@router.post("/grade-imports/{import_id}/commit")
def import_commit(import_id: int, request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    imp = db.get(GradeImport, import_id)
    if not imp:
        raise not_found()
    course = get_course_for(db, user, imp.course_id, teach=True)
    permissions.require(db, user, "grades.enter")
    if imp.status != "preview":
        raise HTTPException(status_code=400, detail="تمت معالجة هذا الاستيراد مسبقاً")
    if imp.errors:
        raise HTTPException(status_code=400, detail="صحح الأخطاء قبل اعتماد الاستيراد")
    if grades.result_for(db, course.id).status != "draft":
        raise HTTPException(status_code=400, detail="النتائج ليست في حالة مسودة")
    comps = {c.id: c for c in grades.components(db, course.id)}
    changed = 0
    for row in imp.rows:
        for cid, score in row["scores"].items():
            changed += grades.set_score(db, user, course, row["student_id"], comps[int(cid)], score,
                                        f"استيراد ملف #{imp.id}", source="import", ip=client_ip(request))
    imp.status = "committed"
    audit.record(db, "grades.imported", actor=user, target_type="course", target_id=course.id,
                 details={"import_id": imp.id, "rows": len(imp.rows), "changed": changed}, ip=client_ip(request))
    db.commit()
    return {"changed": changed}


class WorkflowIn(BaseModel):
    note: str = Field(default="", max_length=500)


def _approver(db: Session, user: User, course: Course) -> bool:
    return is_course_admin(user, course) and permissions.allowed(db, user, "results.approve")


def _transition(db: Session, user: User, course: Course, frm: set[str], to: str, note: str, request: Request):
    res = grades.result_for(db, course.id)
    if res.status not in frm:
        raise HTTPException(status_code=400, detail=f"لا يمكن الانتقال من حالة {res.status}")
    old = res.status
    res.status = to
    now = utcnow()
    if to == "submitted":
        res.submitted_by, res.submitted_at = user.id, now
    elif to == "approved":
        res.approved_by, res.approved_at = user.id, now
    elif to == "published":
        res.published_by, res.published_at = user.id, now
    res.note = note or res.note
    audit.record(db, f"results.{to}", actor=user, target_type="course", target_id=course.id,
                 details={"from": old, "to": to, "note": note}, ip=client_ip(request))
    return res


@router.post("/courses/{course_id}/results/submit")
def results_submit(course_id: int, body: WorkflowIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id, teach=True)
    permissions.require(db, user, "results.submit")
    res = _transition(db, user, course, {"draft"}, "submitted", body.note, request)
    admins = db.scalars(select(User.id).where(User.faculty_id == course.faculty_id, User.role == Role.FACULTY_ADMIN))
    notifications.notify_users(db, course.university_id, list(admins), f"نتائج بانتظار الاعتماد: {course.title}",
                               f"رفع {user.full_name} نتائج المقرر {course.code} للاعتماد.", link="#/results",
                               topic="results_pending")
    db.commit()
    return _result_out(res)


@router.post("/courses/{course_id}/results/approve")
def results_approve(course_id: int, body: WorkflowIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id)
    if not _approver(db, user, course):
        raise forbidden("الاعتماد من صلاحيات إدارة الكلية")
    res = _transition(db, user, course, {"submitted"}, "approved", body.note, request)
    db.commit()
    return _result_out(res)


@router.post("/courses/{course_id}/results/publish")
def results_publish(course_id: int, body: WorkflowIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    course = get_course_for(db, user, course_id)
    if not _approver(db, user, course):
        raise forbidden("النشر من صلاحيات إدارة الكلية")
    res = _transition(db, user, course, {"approved"}, "published", body.note, request)
    notifications.create(db, sender=user, university_id=course.university_id, category="announcement",
                         priority="important", title=f"نشر نتائج: {course.title}",
                         body="تم اعتماد نتائج المقرر ونشرها. يمكنك الاطلاع عليها في صفحة الدرجات.",
                         target_type="course", target_ids=[course.id], course_id=course.id, link="#/grades",
                         channels=["inapp", "push"], automatic=True, topic="grade_released")
    db.commit()
    return _result_out(res)


@router.post("/courses/{course_id}/results/return")
def results_return(course_id: int, body: WorkflowIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Send results back to draft (also used to reopen published results; a reason is required)."""
    course = get_course_for(db, user, course_id)
    if not _approver(db, user, course):
        raise forbidden()
    if len(body.note.strip()) < 3:
        raise HTTPException(status_code=400, detail="اذكر سبب الإرجاع")
    res = _transition(db, user, course, {"submitted", "approved", "published"}, "draft", body.note, request)
    db.commit()
    return _result_out(res)


@router.get("/results/pending")
def results_pending(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (Role.FACULTY_ADMIN, Role.UNIVERSITY_ADMIN) or not permissions.allowed(db, user, "results.approve"):
        raise forbidden()
    ids = visible_course_ids(db, user)
    out = []
    for c in db.scalars(select(Course).where(Course.id.in_(ids)).order_by(Course.code)) if ids else []:
        out.append({"course": {"id": c.id, "code": c.code, "title": c.title},
                    **_result_out(grades.result_for(db, c.id))})
    db.commit()
    return out


@router.get("/me/grades")
def my_grades(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.STUDENT:
        raise forbidden()
    grading = tenant_settings(db, user)["grading"]
    out = []
    for cid in visible_course_ids(db, user):
        course = db.get(Course, cid)
        res = grades.result_for(db, cid)
        item = {"course": {"id": course.id, "code": course.code, "title": course.title, "credits": course.credits},
                "published": res.status == "published"}
        if res.status == "published":  # official results are visible only after approval and publication
            comps = grades.components(db, cid)
            item["components"] = [{"id": c.id, "name": c.name, "max_score": c.max_score} for c in comps]
            item.update(grades.student_summary(db, course, user.id, grading, comps))
        out.append(item)
    db.commit()
    return out
