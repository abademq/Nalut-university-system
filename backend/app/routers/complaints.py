"""The complaints and suggestions box.

A complaint goes to its author's faculty, or to the university administration when the author
chooses so or the subject is sensitive (harassment, a complaint about the faculty administration).
Anonymous: the name is hidden from those who handle it and kept out of the audit log; the author
still follows the replies from their own account."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, files, notifications, permissions
from ..db import get_db, utcnow
from ..deps import client_ip, get_current_user, not_found, tenant_settings
from ..models import Complaint, ComplaintReply, Faculty, Role, StoredFile, User

router = APIRouter(prefix="/api/complaints", tags=["complaints"])

CATEGORIES = {
    "academic": "تعليمي (مقرر، تدريس، امتحان)",
    "administrative": "إداري (معاملات، تسجيل)",
    "services": "خدمات ومرافق (قاعات، نظافة، إنترنت)",
    "conduct": "سلوك أو سوء معاملة",
    "harassment": "تحرش أو إساءة",
    "suggestion": "اقتراح",
    "other": "أخرى",
}
# sensitive: straight to the university administration, whatever the author picks
UNIVERSITY_ONLY = {"harassment"}
STATUS = {"new": "جديدة", "in_review": "قيد المعالجة", "resolved": "تمت المعالجة", "rejected": "مرفوضة"}


def handles(db: Session, user: User, c: Complaint) -> bool:
    if user.university_id != c.university_id:
        return False
    sc = permissions.scope(db, user, "complaints.manage")
    if c.faculty_id is None:
        return sc == permissions.ALL
    return permissions.in_scope(sc, c.faculty_id)


def _get(db: Session, user: User, cid: int) -> Complaint:
    c = db.get(Complaint, cid)
    if not c or c.university_id != user.university_id or not (c.author_id == user.id or handles(db, user, c)):
        raise not_found("الشكوى غير موجودة")
    return c


def _out(db: Session, user: User, c: Complaint, *, thread: bool = False) -> dict:
    mine = c.author_id == user.id
    author = db.get(User, c.author_id)
    fac = db.get(Faculty, c.faculty_id) if c.faculty_id else None
    out = {"id": c.id, "ref": f"C-{c.id:05d}", "category": c.category, "category_label": CATEGORIES.get(c.category, c.category),
           "subject": c.subject, "status": c.status, "status_label": STATUS.get(c.status, c.status),
           "anonymous": c.anonymous, "mine": mine, "to": fac.name if fac else "إدارة الجامعة",
           "author": None if (c.anonymous and not mine) else {
               "id": author.id, "full_name": author.full_name, "code": author.code, "role": author.role} if author else None,
           "created_at": c.created_at, "updated_at": c.updated_at}
    if thread:
        out["body"] = c.body
        out["file"] = files.file_info(db.get(StoredFile, c.file_id)) if c.file_id else None
        rows = db.scalars(select(ComplaintReply).where(ComplaintReply.complaint_id == c.id).order_by(ComplaintReply.id))
        out["replies"] = [{"id": r.id, "body": r.body, "from_handler": r.from_handler, "status": r.status,
                           "author": "الإدارة" if r.from_handler else ("أنت" if mine else (
                               "صاحب الشكوى" if c.anonymous else (author.full_name if author else "—"))),
                           "created_at": r.created_at} for r in rows]
        out["can_handle"] = handles(db, user, c)
    return out


@router.get("/categories")
def categories(user: User = Depends(get_current_user)):
    return {"categories": CATEGORIES, "status": STATUS, "university_only": sorted(UNIVERSITY_ONLY)}


@router.get("")
def list_complaints(box: str = "mine", status: str | None = None, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """box=mine: what I sent; box=inbox: what I handle (complaints.manage, in my scope)."""
    q = select(Complaint).where(Complaint.university_id == user.university_id)
    if box == "inbox":
        sc = permissions.require_scope(db, user, "complaints.manage")
        if sc != permissions.ALL:
            q = q.where(Complaint.faculty_id == sc)
    else:
        q = q.where(Complaint.author_id == user.id)
    if status:
        q = q.where(Complaint.status == status)
    return [_out(db, user, c) for c in db.scalars(q.order_by(Complaint.id.desc()).limit(300))]


@router.get("/stats")
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sc = permissions.require_scope(db, user, "complaints.manage")
    q = select(Complaint.status, func.count()).where(Complaint.university_id == user.university_id)
    if sc != permissions.ALL:
        q = q.where(Complaint.faculty_id == sc)
    return dict(db.execute(q.group_by(Complaint.status)).all())


@router.post("")
async def submit(request: Request, category: str = Form(...), subject: str = Form(..., min_length=3, max_length=200),
                 body: str = Form(..., min_length=10, max_length=5000), anonymous: bool = Form(False),
                 to_university: bool = Form(False), upload: UploadFile | None = File(None),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.PLATFORM_ADMIN:
        raise HTTPException(status_code=403, detail="صندوق الشكاوى لمنتسبي الجامعة")
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="نوع الشكوى غير صحيح")
    from ..security import limiter

    if not limiter.hit(f"complaint:{user.id}", 5, 3600):
        raise HTTPException(status_code=429, detail="أرسلت شكاوى كثيرة خلال ساعة، حاول لاحقاً")
    faculty_id = None if (to_university or category in UNIVERSITY_ONLY or not user.faculty_id) else user.faculty_id
    file_id = None
    if upload is not None and upload.filename:
        cfg = tenant_settings(db, user)["uploads"]
        data = await files.read_upload(upload, int(cfg["max_file_mb"]))
        file_id = files.store(db, owner=user, purpose="complaint", filename=upload.filename, data=data,
                              allowed_extensions=["pdf", "jpg", "jpeg", "png", "docx", "mp3", "m4a"]).id
    c = Complaint(university_id=user.university_id, faculty_id=faculty_id, author_id=user.id, anonymous=anonymous,
                  category=category, subject=subject.strip(), body=body.strip(), file_id=file_id)
    db.add(c)
    db.flush()
    # an anonymous complaint leaves no name in the audit log either
    audit.record(db, "complaint.submitted", actor=None if anonymous else user, university_id=user.university_id,
                 target_type="complaint", target_id=c.id, details={"category": category, "anonymous": anonymous},
                 ip=None if anonymous else client_ip(request))
    handlers = [h for h in permissions.holders(db, user.university_id, "complaints.manage", faculty_id) if h != user.id]
    if faculty_id is None:  # to the university: its administration, not every faculty's
        handlers = [h for h in handlers if permissions.scope(db, db.get(User, h), "complaints.manage") == permissions.ALL]
    notifications.notify_users(db, user.university_id, handlers, f"شكوى جديدة: {CATEGORIES[category].split(' (')[0]}",
                               c.subject, link=f"#/complaints/{c.id}", topic="request_new")
    db.commit()
    return _out(db, user, c, thread=True)


@router.get("/{cid}")
def get(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(db, user, _get(db, user, cid), thread=True)


class ReplyIn(BaseModel):
    body: str = Field(min_length=2, max_length=5000)
    status: str | None = Field(default=None, pattern="^(in_review|resolved|rejected)$")


@router.post("/{cid}/replies")
def reply(cid: int, body: ReplyIn, request: Request, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    c = _get(db, user, cid)
    handler = handles(db, user, c) and c.author_id != user.id
    if body.status and not handler:
        raise HTTPException(status_code=403, detail="تغيير الحالة لمن يعالج الشكوى")
    if not handler and c.status in ("resolved", "rejected"):
        raise HTTPException(status_code=400, detail="أُغلقت الشكوى؛ قدّم شكوى جديدة إن لزم")
    db.add(ComplaintReply(complaint_id=c.id, author_id=user.id, from_handler=handler, body=body.body.strip(),
                          status=body.status))
    if handler and (body.status or c.status == "new"):
        c.status = body.status or "in_review"
    c.updated_at = utcnow()
    if handler:
        audit.record(db, "complaint.replied", actor=user, target_type="complaint", target_id=c.id,
                     details={"status": c.status}, ip=client_ip(request))
        notifications.notify_users(db, c.university_id, [c.author_id], f"رد على شكواك C-{c.id:05d}",
                                   f"{STATUS[c.status]}: {body.body[:150]}", link=f"#/complaints/{c.id}",
                                   topic="request_update")
    else:
        handlers = [h for h in permissions.holders(db, c.university_id, "complaints.manage", c.faculty_id)
                    if h != user.id]
        notifications.notify_users(db, c.university_id, handlers, f"إضافة على الشكوى C-{c.id:05d}", body.body[:150],
                                   link=f"#/complaints/{c.id}", topic="request_new")
    db.commit()
    return _out(db, user, c, thread=True)
