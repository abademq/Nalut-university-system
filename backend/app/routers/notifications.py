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


# --------------------------------------------------------------------------- diagnostics


class TestPushIn(BaseModel):
    priority: str = Field(default="normal", pattern="^(normal|important|urgent)$")


TEST_TEXT = {
    "normal": ("تجربة: إشعار عادي", "هكذا تصلك الإعلانات العادية"),
    "important": ("تجربة: إشعار مهم", "هكذا تصلك الإشعارات المهمة"),
    "urgent": ("تجربة: تنبيه عاجل", "هكذا تصلك التنبيهات العاجلة والإنذارات الرسمية"),
}


@router.post("/test-push")
def test_push(body: TestPushIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sends a test push to the caller's own phones right away and reports what happened."""
    from ..models import DeviceToken
    from ..security import limiter

    if not limiter.hit(f"test-push:{user.id}", 6, 300):
        raise HTTPException(status_code=429, detail="محاولات كثيرة، حاول بعد دقائق")
    provider = notifications.push_provider()
    devices = db.scalars(select(DeviceToken).where(DeviceToken.user_id == user.id)).all()
    title, text = TEST_TEXT[body.priority]
    slot = notifications.tone_for(body.priority, None)
    tone = notifications.tone_name(slot, _tones(db, user))
    sent = removed = 0
    for dev in devices:
        result = provider.send(dev.token, title, text,
                               {"category": "system", "priority": body.priority, "tone": tone, "link": ""})
        if result == "invalid":
            db.delete(dev)
            removed += 1
        elif result in (True, "sent"):
            sent += 1
    db.commit()
    out = {"provider": type(provider).__name__.replace("Provider", "").lower(), "devices": len(devices),
           "sent": sent, "invalid_removed": removed, "tone": tone}
    if devices and not sent and isinstance(provider, notifications.FcmProvider):
        out["error"] = notifications.FcmProvider.last_error
    return out


def _tones(db: Session, user: User) -> dict:
    from ..deps import tenant_settings

    return tenant_settings(db, user)["notifications"].get("tones", {}) if user.university_id else {}


@router.get("/tones")
def tones(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The tone library and which tone each kind of notification plays in this university."""
    current = _tones(db, user)
    return {"library": [{"name": k, "label": v} for k, v in notifications.TONES.items()],
            "slots": [{"slot": k, "label": v, "tone": notifications.tone_name(k, current)}
                      for k, v in notifications.TONE_SLOTS.items()]}


@router.get("/health")
def health(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delivery overview for administrators: provider in use and the last 24 hours' results."""
    from datetime import timedelta

    from ..config import settings
    from ..models import DeviceToken

    if user.role not in (Role.UNIVERSITY_ADMIN, Role.PLATFORM_ADMIN):
        raise HTTPException(status_code=403, detail="غير مصرح لك بهذا الإجراء")
    since = utcnow() - timedelta(hours=24)
    scope = select(Notification.id).where(Notification.sent_at >= since)
    if user.university_id is not None:
        scope = scope.where(Notification.university_id == user.university_id)

    def counts(col):
        rows = db.execute(select(col, func.count()).where(NotificationDelivery.notification_id.in_(scope))
                          .group_by(col)).all()
        return {str(k): v for k, v in rows if k is not None}

    dev_q = select(func.count(func.distinct(DeviceToken.user_id)))
    if user.university_id is not None:
        dev_q = dev_q.join(User, User.id == DeviceToken.user_id).where(User.university_id == user.university_id)
    provider = notifications.push_provider()
    return {
        "push_provider": type(provider).__name__.replace("Provider", "").lower(),
        "push_ready": not isinstance(provider, notifications.LogPushProvider),
        "sms_provider": settings.sms_provider,
        "sms_ready": settings.sms_provider in ("resala", "http"),
        "users_with_devices": db.scalar(dev_q) or 0,
        "last_sms_error": notifications.LAST_SMS_ERROR,
        "last_push_error": notifications.FcmProvider.last_error,
        "last_push_error_at": notifications.FcmProvider.last_error_at,
        "last_push_sent_at": notifications.FcmProvider.last_sent_at,
        "last_24h": {"push": counts(NotificationDelivery.push_status), "sms": counts(NotificationDelivery.sms_status)},
    }


class TestSmsIn(BaseModel):
    kind: str = Field(default="otp", pattern="^(otp|template)$")


@router.post("/test-sms")
def test_sms(body: TestSmsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sends one SMS to the administrator's own phone and returns the provider's exact answer."""
    from ..config import settings
    from ..resala import ResalaClient, ResalaError, TemplateRecord, libyan_mobile
    from ..security import limiter

    if user.role not in (Role.UNIVERSITY_ADMIN, Role.PLATFORM_ADMIN):
        raise HTTPException(status_code=403, detail="غير مصرح لك بهذا الإجراء")
    if not user.phone:
        raise HTTPException(status_code=400, detail="أضف رقم هاتف لحسابك أولاً")
    if not limiter.hit(f"test-sms:{user.id}", 5, 600):
        raise HTTPException(status_code=429, detail="محاولات كثيرة، حاول بعد دقائق")
    out = {"provider": settings.sms_provider, "test_mode": settings.resala_test, "phone": user.phone,
           "normalized": libyan_mobile(user.phone)}
    if settings.sms_provider != "resala":
        sent = notifications.sms_provider().send(user.phone, "تجربة: رسالة من منصة الجامعة")
        return {**out, "ok": bool(sent), "note": "مزود الرسائل ليس Resala (SMS_PROVIDER)"}
    try:
        client = ResalaClient.from_env()
        if body.kind == "otp":
            pin = client.send_pin(out["normalized"] or user.phone, service_name=settings.resala_service_name,
                                  test=settings.resala_test or None, sender=settings.resala_sender)
            return {**out, "ok": True, "sender_name": pin.sender_name, "content": pin.content}
        if not settings.resala_sms_template_id:
            return {**out, "ok": False, "error_type": "Config",
                    "error_message": "RESALA_SMS_TEMPLATE_ID غير مضبوط في /etc/nus/nus.env"}
        res = client.send_template(settings.resala_sms_template_id,
                                   [TemplateRecord(out["normalized"] or user.phone, ["تجربة", "رسالة من منصة الجامعة"])],
                                   test=settings.resala_test or None, sender=settings.resala_sender)
        return {**out, "ok": res.succeeded > 0 or (settings.resala_test and not res.invalid_numbers),
                "succeeded": res.succeeded, "failed_numbers": res.failed_numbers,
                "invalid_numbers": res.invalid_numbers, "sender_names": res.sender_names, "is_prod": res.is_prod}
    except ValueError as exc:  # missing key
        return {**out, "ok": False, "error_type": "Config", "error_message": str(exc)}
    except ResalaError as exc:
        notifications.record_sms_error(body.kind, exc)
        return {**out, "ok": False, "error_type": exc.type, "error_status": exc.status,
                "error_message": exc.message, "errors": exc.errors}
