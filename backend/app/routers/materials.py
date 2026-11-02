"""Course materials repository («مستودع المواد»): files kept by course and term.

Who adds what:
* the course's teachers and assistants, and holders of «materials.manage»: published at once;
* students who study (or studied) the course: summaries and the like, held for review by the
  course's teachers or the administration, a few at a time, then credited to them when published.
Everyone in the faculty reads the published files, so a good summary helps the next class too."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, files, notifications, permissions
from ..db import get_db, utcnow
from ..deps import client_ip, get_current_user, not_found, tenant_settings
from ..models import Course, CourseStaff, Enrollment, Material, Role, StoredFile, Term, User

router = APIRouter(prefix="/api/materials", tags=["materials"])
KEY = "materials.manage"
CATEGORIES = {"lecture": "محاضرات وشرائح", "summary": "ملخصات", "exam": "امتحانات سابقة", "exercise": "تمارين وحلول",
              "reference": "مراجع وكتب", "other": "أخرى"}
EXTENSIONS = ["pdf", "docx", "doc", "pptx", "ppt", "xlsx", "txt", "png", "jpg", "jpeg", "zip"]


def _faculty_of(user: User) -> int | None:
    return user.faculty_id


def _teaches(db: Session, user: User, faculty_id: int, code: str) -> bool:
    return db.scalar(select(CourseStaff.id).join(Course, Course.id == CourseStaff.course_id).where(
        CourseStaff.user_id == user.id, Course.faculty_id == faculty_id, Course.code == code).limit(1)) is not None


def _studies(db: Session, user: User, faculty_id: int, code: str) -> bool:
    return db.scalar(select(Enrollment.id).join(Course, Course.id == Enrollment.course_id).where(
        Enrollment.student_id == user.id, Course.faculty_id == faculty_id, Course.code == code).limit(1)) is not None


def reviews(db: Session, user: User, faculty_id: int, code: str) -> bool:
    """Publishes directly and reviews students' files of this course."""
    return permissions.in_scope(permissions.scope(db, user, KEY), faculty_id) or _teaches(db, user, faculty_id, code)


def can_read(db: Session, user: User, m: Material) -> bool:
    if user.university_id != m.university_id:
        return False
    if m.uploader_id == user.id or reviews(db, user, m.faculty_id, m.course_code):
        return True
    in_faculty = user.faculty_id == m.faculty_id or (user.role in Role.EMPLOYEES and user.faculty_id is None)
    return m.status == "published" and in_faculty


def _out(db: Session, user: User, m: Material, names: dict | None = None) -> dict:
    f = db.get(StoredFile, m.file_id)
    up = (names or {}).get(m.uploader_id) or (db.get(User, m.uploader_id).full_name if db.get(User, m.uploader_id) else "—")
    term = db.get(Term, m.term_id) if m.term_id else None
    return {"id": m.id, "course_code": m.course_code, "course_title": m.course_title, "term": term.name if term else None,
            "term_id": m.term_id, "category": m.category, "category_label": CATEGORIES.get(m.category, m.category),
            "title": m.title, "description": m.description, "status": m.status, "reject_reason": m.reject_reason,
            "by_student": m.by_student, "uploader": up, "mine": m.uploader_id == user.id, "downloads": m.downloads,
            "file": files.file_info(f) if f else None, "created_at": m.created_at,
            "can_review": reviews(db, user, m.faculty_id, m.course_code)}


def _faculty_param(db: Session, user: User, faculty_id: int | None) -> int:
    fid = faculty_id or user.faculty_id
    if not fid:
        raise HTTPException(status_code=400, detail="حدد الكلية")
    if fid != user.faculty_id and permissions.scope(db, user, KEY) != permissions.ALL:
        raise HTTPException(status_code=403, detail="هذه الكلية خارج نطاقك")
    return fid


@router.get("/categories")
def categories(user: User = Depends(get_current_user)):
    return CATEGORIES


@router.get("/courses")
def courses(faculty_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The faculty's courses by code, with how many published files each has; mine first."""
    fid = _faculty_param(db, user, faculty_id)
    rows = db.execute(select(Course.code, func.max(Course.title)).where(
        Course.university_id == user.university_id, Course.faculty_id == fid).group_by(Course.code)).all()
    counts = dict(db.execute(select(Material.course_code, func.count()).where(
        Material.faculty_id == fid, Material.status == "published").group_by(Material.course_code)).all())
    pending = dict(db.execute(select(Material.course_code, func.count()).where(
        Material.faculty_id == fid, Material.status == "pending").group_by(Material.course_code)).all())
    if user.role == Role.STUDENT:
        mine = set(db.scalars(select(Course.code).join(Enrollment, Enrollment.course_id == Course.id).where(
            Enrollment.student_id == user.id, Course.faculty_id == fid)))
    else:
        mine = set(db.scalars(select(Course.code).join(CourseStaff, CourseStaff.course_id == Course.id).where(
            CourseStaff.user_id == user.id, Course.faculty_id == fid)))
    manage = permissions.in_scope(permissions.scope(db, user, KEY), fid)
    out = [{"code": c, "title": t, "files": counts.get(c, 0), "mine": c in mine,
            "pending": pending.get(c, 0) if (manage or (c in mine and user.role != Role.STUDENT)) else None}
           for c, t in rows]
    return sorted(out, key=lambda x: (not x["mine"], x["code"]))


@router.get("")
def list_materials(code: str, faculty_id: int | None = None, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    fid = _faculty_param(db, user, faculty_id)
    q = select(Material).where(Material.university_id == user.university_id, Material.faculty_id == fid,
                               Material.course_code == code)
    if not reviews(db, user, fid, code):
        q = q.where((Material.status == "published") | (Material.uploader_id == user.id))
    rows = db.scalars(q.order_by(Material.term_id.desc().nulls_last(), Material.category, Material.id.desc())).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({m.uploader_id for m in rows} or {-1})))}
    return [_out(db, user, m, names) for m in rows]


@router.get("/pending")
def pending(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Students' files waiting for review that this user may decide."""
    q = select(Material).where(Material.university_id == user.university_id, Material.status == "pending")
    rows = [m for m in db.scalars(q.order_by(Material.id)) if reviews(db, user, m.faculty_id, m.course_code)]
    return [_out(db, user, m) for m in rows]


@router.post("")
async def upload(request: Request, code: str = Form(..., max_length=40), category: str = Form(...),
                 title: str = Form(..., min_length=3, max_length=200), description: str = Form("", max_length=1000),
                 faculty_id: int | None = Form(None), file: UploadFile = File(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="تصنيف الملف غير صحيح")
    fid = _faculty_param(db, user, faculty_id)
    course = db.scalar(select(Course).where(Course.university_id == user.university_id, Course.faculty_id == fid,
                                            Course.code == code).order_by(Course.id.desc()).limit(1))
    if not course:
        raise not_found("المقرر غير موجود")
    cfg = tenant_settings(db, user)
    staff = reviews(db, user, fid, code)
    if not staff:
        mc = cfg["materials"]
        if user.role != Role.STUDENT or not _studies(db, user, fid, code):
            raise HTTPException(status_code=403, detail="يرفع الملفات أساتذة المقرر وطلبته")
        if not mc.get("student_uploads", True):
            raise HTTPException(status_code=403, detail="رفع الطلبة للملفات غير مفعل في الكلية")
        waiting = db.scalar(select(func.count(Material.id)).where(Material.uploader_id == user.id,
                                                                  Material.status == "pending"))
        if waiting >= int(mc.get("max_pending_per_student", 5)):
            raise HTTPException(status_code=400, detail="لديك ملفات كثيرة قيد المراجعة؛ انتظر البت فيها")
    data = await files.read_upload(file, int(cfg["uploads"]["max_file_mb"]))
    f = files.store(db, owner=user, purpose="material", filename=file.filename or "file", data=data,
                    allowed_extensions=EXTENSIONS)
    term = db.scalar(select(Term.id).where(Term.university_id == user.university_id, Term.is_current.is_(True)))
    m = Material(university_id=user.university_id, faculty_id=fid, course_code=code, course_title=course.title,
                 term_id=course.term_id or term, category=category, title=title.strip(), description=description.strip(),
                 file_id=f.id, uploader_id=user.id, by_student=user.role == Role.STUDENT,
                 status="published" if staff else "pending")
    db.add(m)
    db.flush()
    audit.record(db, "material.uploaded", actor=user, target_type="material", target_id=m.id,
                 details={"code": code, "status": m.status}, ip=client_ip(request))
    if m.status == "pending":
        teachers = set(db.scalars(select(CourseStaff.user_id).join(Course, Course.id == CourseStaff.course_id).where(
            Course.faculty_id == fid, Course.code == code, Course.term_id == course.term_id)))
        notifications.notify_users(db, user.university_id, teachers or permissions.holders(db, user.university_id, KEY, fid),
                                   f"ملف للمراجعة في مستودع {course.title}", m.title, link="#/materials?review=1",
                                   topic="request_new")
    db.commit()
    return _out(db, user, m)


class ReviewIn(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=300)


@router.post("/{mid}/review")
def review(mid: int, body: ReviewIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """Publish a student's file, or decline it (or withdraw a published one) with a reason."""
    m = db.get(Material, mid)
    if not m or m.university_id != user.university_id or not reviews(db, user, m.faculty_id, m.course_code):
        raise not_found("الملف غير موجود")
    if not body.approve and not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="اذكر سبب الرفض ليعرفه صاحب الملف")
    m.status = "published" if body.approve else "rejected"
    m.reject_reason = None if body.approve else body.reason.strip()
    m.reviewed_by, m.reviewed_at = user.id, utcnow()
    audit.record(db, "material.reviewed", actor=user, target_type="material", target_id=m.id,
                 details={"status": m.status, "reason": m.reject_reason}, ip=client_ip(request))
    if m.uploader_id != user.id:
        notifications.notify_users(db, m.university_id, [m.uploader_id],
                                   "نُشر ملفك في مستودع المواد" if body.approve else "لم يُنشر ملفك في مستودع المواد",
                                   m.title if body.approve else f"{m.title}: {m.reject_reason}",
                                   link="#/materials", topic="request_update")
    db.commit()
    return _out(db, user, m)


@router.delete("/{mid}")
def delete(mid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(Material, mid)
    if not m or m.university_id != user.university_id:
        raise not_found("الملف غير موجود")
    mine_pending = m.uploader_id == user.id and (m.status != "published" or not m.by_student)
    if not (mine_pending or reviews(db, user, m.faculty_id, m.course_code)):
        raise HTTPException(status_code=403, detail="لا يمكنك حذف هذا الملف")
    audit.record(db, "material.deleted", actor=user, target_type="material", target_id=m.id,
                 details={"code": m.course_code, "title": m.title}, ip=client_ip(request))
    f = db.get(StoredFile, m.file_id)
    db.delete(m)
    if f and f.deleted_at is None:
        f.deleted_at = utcnow()
    db.commit()
    return {"ok": True}


@router.get("/{mid}/download")
def download(mid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(Material, mid)
    if not m or not can_read(db, user, m):
        raise not_found("الملف غير موجود")
    if m.uploader_id != user.id:
        m.downloads += 1
        db.commit()
    return files.download_response(db.get(StoredFile, m.file_id))
