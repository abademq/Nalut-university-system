"""Lecture timetables (image or PDF) and image announcements (posters) shown in the app.

Published by the university administration, faculty administrations and, if the permission
matrix allows it, staff; each item targets the whole university or a faculty / department /
cohort and an audience (students, staff or everyone), between a start and an optional end.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, notifications, permissions
from ..db import as_utc, get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found
from ..models import Department, Faculty, Publication, Role, StoredFile, User

router = APIRouter(prefix="/api/publications", tags=["publications"])

KINDS = {"schedule": "جدول محاضرات", "poster": "إعلان مصور"}
AUDIENCES = ("all", "students", "staff")
EXTENSIONS = ["jpg", "jpeg", "png", "pdf"]
MAX_MB = 10


def can_publish(db: Session, user: User) -> bool:
    if user.role == Role.UNIVERSITY_ADMIN:
        return True
    if user.role in (Role.FACULTY_ADMIN, Role.STAFF):
        return permissions.allowed(db, user, "publications.manage")
    return False


def visible(user: User, p: Publication, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if p.university_id != user.university_id or not p.is_active or p.starts_at > now:
        return False
    if p.ends_at and p.ends_at <= now:
        return False
    student = user.role == Role.STUDENT
    if p.audience != "all" and p.audience != ("students" if student else "staff"):
        return False
    if p.faculty_id and p.faculty_id != user.faculty_id:
        return False
    if p.department_id and p.department_id != user.department_id:
        return False
    return not (p.cohort and student and p.cohort != user.cohort)


def _manages(user: User, p: Publication) -> bool:
    if p.university_id != user.university_id:
        return False
    if user.role == Role.UNIVERSITY_ADMIN:
        return True
    return user.faculty_id is None or p.faculty_id == user.faculty_id


def _out(db: Session, p: Publication) -> dict:
    f = db.get(StoredFile, p.file_id)
    fac = db.get(Faculty, p.faculty_id) if p.faculty_id else None
    dep = db.get(Department, p.department_id) if p.department_id else None
    return {"id": p.id, "kind": p.kind, "kind_label": KINDS.get(p.kind, p.kind), "title": p.title, "body": p.body,
            "file": {"id": f.id, "name": f.original_name, "content_type": f.content_type, "size": f.size},
            "is_image": f.content_type.startswith("image/"), "audience": p.audience,
            "faculty_id": p.faculty_id, "faculty_name": fac.name if fac else None,
            "department_id": p.department_id, "department_name": dep.name if dep else None, "cohort": p.cohort,
            "starts_at": p.starts_at, "ends_at": p.ends_at, "is_active": p.is_active, "created_at": p.created_at}


@router.get("")
def feed(kind: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What the caller can see right now, newest first."""
    if user.university_id is None:
        return []
    stmt = select(Publication).where(Publication.university_id == user.university_id, Publication.is_active.is_(True))
    if kind:
        stmt = stmt.where(Publication.kind == kind)
    now = utcnow()
    rows = [p for p in db.scalars(stmt.order_by(Publication.starts_at.desc()).limit(300)) if visible(user, p, now)]
    return [_out(db, p) for p in rows]


@router.get("/manage")
def manage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not can_publish(db, user):
        raise forbidden()
    stmt = select(Publication).where(Publication.university_id == user.university_id)
    if user.role != Role.UNIVERSITY_ADMIN and user.faculty_id is not None:
        stmt = stmt.where(Publication.faculty_id == user.faculty_id)
    return [_out(db, p) for p in db.scalars(stmt.order_by(Publication.id.desc()).limit(300))]


def _parse_time(value: str | None, field: str) -> datetime | None:
    if not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"تاريخ غير صحيح: {field}") from None


def _check_scope(db: Session, user: User, faculty_id: int | None, department_id: int | None) -> int | None:
    if user.role != Role.UNIVERSITY_ADMIN and user.faculty_id is not None:
        faculty_id = user.faculty_id  # faculty administrations and staff publish to their own faculty
    if faculty_id is not None:
        fac = db.get(Faculty, faculty_id)
        if not fac or fac.university_id != user.university_id:
            raise HTTPException(status_code=400, detail="الكلية غير صحيحة")
    if department_id is not None:
        dep = db.get(Department, department_id)
        if not dep or dep.university_id != user.university_id or (faculty_id and dep.faculty_id != faculty_id):
            raise HTTPException(status_code=400, detail="القسم غير صحيح")
    return faculty_id


@router.post("")
async def create(request: Request, kind: str = Form(...), title: str = Form(..., min_length=2, max_length=200),
                 body: str = Form("", max_length=2000), audience: str = Form("all"),
                 faculty_id: int | None = Form(None), department_id: int | None = Form(None),
                 cohort: str | None = Form(None, max_length=40), starts_at: str | None = Form(None),
                 ends_at: str | None = Form(None), notify: bool = Form(False), upload: UploadFile = File(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not can_publish(db, user):
        raise forbidden("نشر الجداول والإعلانات المصورة غير متاح لحسابك")
    if kind not in KINDS or audience not in AUDIENCES:
        raise HTTPException(status_code=400, detail="نوع أو جمهور غير صحيح")
    faculty_id = _check_scope(db, user, faculty_id, department_id)
    start = _parse_time(starts_at, "starts_at") or utcnow()
    end = _parse_time(ends_at, "ends_at")
    if end and end <= start:
        raise HTTPException(status_code=400, detail="وقت الاختفاء يجب أن يكون بعد وقت الظهور")
    data = await files.read_upload(upload, MAX_MB)
    stored = files.store(db, owner=user, purpose="publication", filename=upload.filename or "file", data=data,
                         allowed_extensions=EXTENSIONS)
    p = Publication(university_id=user.university_id, kind=kind, title=title.strip(), body=body.strip(),
                    file_id=stored.id, audience=audience, faculty_id=faculty_id, department_id=department_id,
                    cohort=(cohort or "").strip() or None, starts_at=start, ends_at=end, created_by=user.id)
    db.add(p)
    db.flush()
    audit.record(db, "publication.created", actor=user, target_type="publication", target_id=p.id,
                 details={"kind": kind, "title": p.title}, ip=client_ip(request))
    out = _out(db, p)
    if notify and start <= utcnow():
        out["notified"] = _notify(db, user, p)
    db.commit()
    return out


def _notify(db: Session, user: User, p: Publication) -> bool:
    if p.cohort:
        target, ids = "cohort", [p.cohort]
    elif p.department_id:
        target, ids = "department", [p.department_id]
    elif p.faculty_id:
        target, ids = "faculty", [p.faculty_id]
    else:
        target, ids = "university", []
    try:
        notifications.create(
            db, sender=user, university_id=p.university_id, category="announcement", priority="normal",
            title=f"{KINDS[p.kind]}: {p.title}", body=p.body or "اضغط للعرض", target_type=target, target_ids=ids,
            audience=p.audience, channels=["inapp", "push"], link=f"#/publications/{p.id}", automatic=True,
            topic="publication")
        return True
    except notifications.NotificationError:
        return False  # the publication stays; only the announcement is outside the sender's scope


class PublicationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
    audience: str | None = Field(default=None, pattern="^(all|students|staff)$")
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None


def _owned(db: Session, user: User, pid: int) -> Publication:
    p = db.get(Publication, pid)
    if not p or not can_publish(db, user) or not _manages(user, p):
        raise not_found()
    return p


@router.patch("/{pid}")
def patch(pid: int, body: PublicationPatch, request: Request, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    p = _owned(db, user, pid)
    data = body.model_dump(exclude_unset=True)
    for key in ("starts_at", "ends_at"):
        if data.get(key) is not None:
            data[key] = as_utc(data[key])
    if data.get("starts_at") is None:
        data.pop("starts_at", None)
    for k, v in data.items():
        setattr(p, k, v)
    if p.ends_at and p.ends_at <= p.starts_at:
        raise HTTPException(status_code=400, detail="وقت الاختفاء يجب أن يكون بعد وقت الظهور")
    audit.record(db, "publication.updated", actor=user, target_type="publication", target_id=p.id,
                 details={k: str(v) for k, v in data.items()}, ip=client_ip(request))
    db.commit()
    return _out(db, p)


@router.delete("/{pid}")
def delete(pid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _owned(db, user, pid)
    audit.record(db, "publication.deleted", actor=user, target_type="publication", target_id=p.id,
                 details={"title": p.title}, ip=client_ip(request))
    db.delete(p)
    db.commit()
    return {"ok": True}
