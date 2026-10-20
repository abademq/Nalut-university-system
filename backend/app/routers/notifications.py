from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, notifications
from ..db import as_utc, get_db, utcnow
from ..deps import client_ip, get_current_user, not_found
from ..models import Notification, NotificationDelivery, Role, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _out(n: Notification, d: NotificationDelivery | None = None, sender: str | None = None) -> dict:
    out = {"id": n.id, "category": n.category, "priority": n.priority, "title": n.title, "body": n.body,
           "link": n.link, "course_id": n.course_id, "sender": sender, "created_at": n.sent_at or n.created_at}
    if d:
        out.update({"delivery_id": d.id, "read_at": d.read_at})
    return out


@router.get("")
def inbox(category: str | None = None, unread: bool = False, limit: int = Query(default=50, le=200),
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(NotificationDelivery).join(Notification).where(NotificationDelivery.user_id == user.id)
    if category:
        stmt = stmt.where(Notification.category == category)
    if unread:
        stmt = stmt.where(NotificationDelivery.read_at.is_(None))
    rows = db.scalars(stmt.order_by(NotificationDelivery.id.desc()).limit(limit)).all()
    senders = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({d.notification.sender_id for d in rows if d.notification.sender_id})))}
    unread_count = db.scalar(select(func.count(NotificationDelivery.id)).where(
        NotificationDelivery.user_id == user.id, NotificationDelivery.read_at.is_(None)))
    return {"unread": unread_count,
            "items": [_out(d.notification, d, senders.get(d.notification.sender_id)) for d in rows]}


@router.post("/{delivery_id}/read")
def mark_read(delivery_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.get(NotificationDelivery, delivery_id)
    if not d or d.user_id != user.id:
        raise not_found()
    d.read_at = d.read_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/by-id/{nid}/read")
def mark_read_by_notification(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Used when the user opens a push notification (the phone only knows the notification id)."""
    d = db.scalar(select(NotificationDelivery).where(NotificationDelivery.notification_id == nid,
                                                     NotificationDelivery.user_id == user.id))
    if not d:
        raise not_found()
    d.read_at = d.read_at or utcnow()
    db.commit()
    return {"ok": True, "delivery_id": d.id}


@router.post("/read-all")
def mark_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for d in db.scalars(select(NotificationDelivery).where(NotificationDelivery.user_id == user.id,
                                                           NotificationDelivery.read_at.is_(None))):
        d.read_at = utcnow()
    db.commit()
    return {"ok": True}


class SendIn(BaseModel):
    category: str
    priority: str = "normal"
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2, max_length=5000)
    target_type: str
    target_ids: list = Field(default_factory=list, max_length=2000)
    audience: str = Field(default="students", pattern="^(students|staff|all)$")
    channels: list[str] = Field(default_factory=lambda: ["inapp", "push"])
    scheduled_at: datetime | None = None
    course_id: int | None = None


@router.post("")
def send(body: SendIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not set(body.channels) <= {"inapp", "push", "sms"}:
        raise HTTPException(status_code=400, detail="قناة غير معروفة")
    scheduled = as_utc(body.scheduled_at)
    if scheduled and scheduled < utcnow():
        scheduled = None
    ids = [str(i) for i in body.target_ids] if body.target_type == "cohort" else [int(i) for i in body.target_ids]
    try:
        n = notifications.create(
            db, sender=user, university_id=user.university_id, category=body.category, priority=body.priority,
            title=body.title, body=body.body, target_type=body.target_type, target_ids=ids,
            audience=body.audience, channels=body.channels, scheduled_at=scheduled,
            course_id=body.course_id if body.target_type == "course" else None,
        )
    except notifications.NotificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="بيانات المستلمين غير صحيحة") from exc
    if n.category == "official_warning":
        audit.record(db, "warning.issued", actor=user, target_type="notification", target_id=n.id,
                     details={"targets": n.target_ids, "title": n.title}, ip=client_ip(request))
    db.commit()
    return {"id": n.id, "status": n.status, "recipients": n.recipients_count, "scheduled_at": n.scheduled_at}


@router.get("/sent")
def sent(limit: int = Query(default=50, le=200), user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.university_id == user.university_id)
    if user.role == Role.UNIVERSITY_ADMIN:
        stmt = stmt.where(Notification.sender_id.is_not(None))
    elif user.role == Role.FACULTY_ADMIN:
        stmt = stmt.where(Notification.sender_id.in_(select(User.id).where(User.faculty_id == user.faculty_id)))
    else:
        stmt = stmt.where(Notification.sender_id == user.id)
    rows = db.scalars(stmt.order_by(Notification.id.desc()).limit(limit)).all()
    out = []
    for n in rows:
        read = db.scalar(select(func.count(NotificationDelivery.id)).where(
            NotificationDelivery.notification_id == n.id, NotificationDelivery.read_at.is_not(None)))
        out.append({**_out(n), "status": n.status, "target_type": n.target_type, "target_ids": n.target_ids,
                    "recipients": n.recipients_count, "read": read, "scheduled_at": n.scheduled_at,
                    "channels": n.channels})
    return out


@router.post("/{nid}/cancel")
def cancel(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.university_id != user.university_id or (n.sender_id != user.id and user.role not in Role.ADMINS):
        raise not_found()
    if n.status != "scheduled":
        raise HTTPException(status_code=400, detail="لا يمكن إلغاء إشعار تم إرساله")
    n.status = "cancelled"
    db.commit()
    return {"ok": True}
