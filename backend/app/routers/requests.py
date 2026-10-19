"""Administrative service requests (transactions) handled by staff offices."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, notifications
from ..db import get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found, tenant_settings
from ..models import Role, ServiceRequest, ServiceRequestEvent, StoredFile, User

router = APIRouter(prefix="/api/requests", tags=["requests"])

REQUEST_TYPES = {
    "enrollment_certificate": {"label": "إفادة قيد", "office": "registrar"},
    "transcript": {"label": "كشف درجات", "office": "registrar"},
    "absence_excuse": {"label": "عذر غياب", "office": "student_affairs"},
    "grade_appeal": {"label": "تظلم من درجة", "office": "exams"},
    "other": {"label": "طلب آخر", "office": "student_affairs"},
}
OFFICES = {"registrar": "التسجيل", "student_affairs": "شؤون الطلبة", "exams": "الامتحانات"}
STATUS_LABELS = {"submitted": "مقدم", "in_review": "قيد المراجعة", "needs_documents": "مطلوب استكمال مستندات",
                 "forwarded": "محال", "approved": "معتمد", "rejected": "مرفوض"}
STAFF_ACTIONS = {"in_review", "needs_documents", "forwarded", "approved", "rejected", "comment"}


def can_handle(user: User, r: ServiceRequest) -> bool:
    if user.university_id != r.university_id:
        return False
    if user.role == Role.UNIVERSITY_ADMIN:
        return True
    if user.role == Role.FACULTY_ADMIN:
        return r.faculty_id == user.faculty_id
    if user.role == Role.STAFF:
        return user.office == r.office and (user.faculty_id is None or user.faculty_id == r.faculty_id)
    return False


def _get(db: Session, user: User, rid: int) -> ServiceRequest:
    r = db.get(ServiceRequest, rid)
    if not r or r.university_id != user.university_id or not (r.requester_id == user.id or can_handle(user, r)):
        raise not_found()
    return r


def _out(db: Session, r: ServiceRequest, *, events: bool = False) -> dict:
    requester = db.get(User, r.requester_id)
    out = {"id": r.id, "type": r.type, "type_label": REQUEST_TYPES.get(r.type, {}).get("label", r.type),
           "office": r.office, "office_label": OFFICES.get(r.office, r.office), "subject": r.subject,
           "details": r.details, "status": r.status, "status_label": STATUS_LABELS.get(r.status, r.status),
           "requester": {"id": requester.id, "full_name": requester.full_name, "code": requester.code},
           "created_at": r.created_at, "updated_at": r.updated_at}
    if events:
        evs = db.scalars(select(ServiceRequestEvent).where(ServiceRequestEvent.request_id == r.id)
                         .order_by(ServiceRequestEvent.id)).all()
        names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({e.actor_id for e in evs} or {-1})))}
        out["events"] = [{"action": e.action, "status": e.status, "comment": e.comment, "actor": names.get(e.actor_id),
                          "file": files.file_info(db.get(StoredFile, e.file_id)) if e.file_id else None,
                          "created_at": e.created_at} for e in evs]
    return out


@router.get("/types")
def types():
    return {"types": REQUEST_TYPES, "offices": OFFICES, "statuses": STATUS_LABELS}


@router.get("")
def list_requests(scope: str = "mine", status: str | None = None, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    stmt = select(ServiceRequest).where(ServiceRequest.university_id == user.university_id)
    if scope == "mine":
        stmt = stmt.where(ServiceRequest.requester_id == user.id)
    else:
        if user.role == Role.STAFF:
            stmt = stmt.where(ServiceRequest.office == user.office)
            if user.faculty_id:
                stmt = stmt.where(ServiceRequest.faculty_id == user.faculty_id)
        elif user.role == Role.FACULTY_ADMIN:
            stmt = stmt.where(ServiceRequest.faculty_id == user.faculty_id)
        elif user.role != Role.UNIVERSITY_ADMIN:
            raise forbidden()
    if status:
        stmt = stmt.where(ServiceRequest.status == status)
    return [_out(db, r) for r in db.scalars(stmt.order_by(ServiceRequest.updated_at.desc()).limit(200))]


@router.post("")
async def create_request(type: str = Form(...), subject: str = Form(..., min_length=2, max_length=200),
                         details: str = Form("", max_length=5000), upload: UploadFile | None = File(None),
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if type not in REQUEST_TYPES:
        raise HTTPException(status_code=400, detail="نوع الطلب غير صحيح")
    r = ServiceRequest(university_id=user.university_id, faculty_id=user.faculty_id, requester_id=user.id, type=type,
                       office=REQUEST_TYPES[type]["office"], subject=subject, details=details)
    db.add(r)
    db.flush()
    file_id = await _attach(db, user, upload)
    db.add(ServiceRequestEvent(request_id=r.id, actor_id=user.id, action="submitted", status="submitted",
                               file_id=file_id))
    handlers = db.scalars(select(User.id).where(User.university_id == user.university_id, User.role == Role.STAFF,
                                                User.office == r.office))
    notifications.notify_users(db, user.university_id, list(handlers), f"طلب جديد: {REQUEST_TYPES[type]['label']}",
                               subject, link=f"#/requests/{r.id}")
    db.commit()
    return _out(db, r)


async def _attach(db: Session, user: User, upload: UploadFile | None) -> int | None:
    if upload is None:
        return None
    cfg = tenant_settings(db, user)["uploads"]
    data = await files.read_upload(upload, int(cfg["max_file_mb"]))
    return files.store(db, owner=user, purpose="request", filename=upload.filename or "file", data=data,
                       allowed_extensions=["pdf", "jpg", "jpeg", "png", "docx"]).id


@router.get("/{rid}")
def get_request(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(db, _get(db, user, rid), events=True)


class ActionIn(BaseModel):
    action: str
    comment: str = Field(default="", max_length=2000)
    office: str | None = None


@router.post("/{rid}/actions")
def act(rid: int, body: ActionIn, request: Request, user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    r = _get(db, user, rid)
    if not can_handle(user, r):
        raise forbidden()
    if body.action not in STAFF_ACTIONS:
        raise HTTPException(status_code=400, detail="إجراء غير صحيح")
    if r.status in ("approved", "rejected") and body.action != "comment":
        raise HTTPException(status_code=400, detail="الطلب مغلق")
    if body.action in ("rejected", "needs_documents") and len(body.comment.strip()) < 3:
        raise HTTPException(status_code=400, detail="اذكر السبب أو المستندات المطلوبة")
    if body.action == "forwarded":
        if body.office not in OFFICES:
            raise HTTPException(status_code=400, detail="حدد الجهة المحال إليها")
        r.office = body.office
    if body.action != "comment":
        r.status = body.action
    r.assigned_to, r.updated_at = user.id, utcnow()
    db.add(ServiceRequestEvent(request_id=r.id, actor_id=user.id, action=body.action, status=r.status,
                               comment=body.comment or None))
    if body.action in ("approved", "rejected", "needs_documents"):
        notifications.notify_users(
            db, r.university_id, [r.requester_id], f"تحديث على طلبك: {STATUS_LABELS[r.status]}",
            f"{r.subject}" + (f" — {body.comment}" if body.comment else ""), category="admin_notice",
            priority="important", link=f"#/requests/{r.id}", sender=user)
        audit.record(db, f"request.{body.action}", actor=user, target_type="service_request", target_id=r.id,
                     details={"comment": body.comment}, ip=client_ip(request))
    db.commit()
    return _out(db, r, events=True)


@router.post("/{rid}/documents")
async def add_document(rid: int, comment: str = Form("", max_length=2000), upload: UploadFile = File(...),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _get(db, user, rid)
    if r.requester_id != user.id:
        raise forbidden()
    if r.status in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="الطلب مغلق")
    file_id = await _attach(db, user, upload)
    if r.status == "needs_documents":
        r.status = "in_review"
    r.updated_at = utcnow()
    db.add(ServiceRequestEvent(request_id=r.id, actor_id=user.id, action="documents_added", status=r.status,
                               comment=comment or None, file_id=file_id))
    db.commit()
    return _out(db, r, events=True)
