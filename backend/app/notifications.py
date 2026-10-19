"""Central multi-channel notification service.

Channels: in-app inbox (always), push (FCM/APNs via a provider), SMS (external API).
Provider credentials stay on the server; clients only register device tokens.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import settings
from .db import utcnow
from .models import (
    Course,
    CourseStaff,
    Department,
    DeviceToken,
    Enrollment,
    Faculty,
    Notification,
    NotificationDelivery,
    Role,
    University,
    User,
)
from .tenancy import effective_settings

log = logging.getLogger("nus.notifications")

CATEGORIES = ["announcement", "academic_note", "official_warning", "admin_notice", "system"]
PRIORITIES = ["normal", "important", "urgent"]
TARGET_TYPES = ["user", "users", "course", "department", "faculty", "university", "cohort"]

# Who may issue which category (the target scope is checked separately).
CATEGORY_ISSUERS = {
    "announcement": {Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.TEACHER, Role.ASSISTANT},
    "academic_note": {Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.TEACHER, Role.ASSISTANT},
    # formal academic warnings are an official act of the faculty / university administration
    "official_warning": {Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN},
    "admin_notice": {Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.STAFF},
    "system": set(),
}

# Categories a user can never mute.
UNMUTABLE = {"official_warning", "system"}


class NotificationError(ValueError):
    pass


# --------------------------------------------------------------------------- providers


class LogPushProvider:
    def send(self, token: str, title: str, body: str, data: dict) -> bool:
        log.info("PUSH -> %s… : %s", token[:12], title)
        return True


class HttpPushProvider:
    """Posts to a push gateway (e.g. a small service holding the FCM/APNs credentials)."""

    def send(self, token: str, title: str, body: str, data: dict) -> bool:
        if not settings.push_gateway_url or not settings.push_gateway_key:
            return False
        req = urllib.request.Request(
            settings.push_gateway_url,
            data=json.dumps({"token": token, "title": title, "body": body, "data": data}).encode(),
            headers={"Authorization": f"Bearer {settings.push_gateway_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - configured URL
                return 200 <= resp.status < 300
        except OSError:
            return False


class LogSmsProvider:
    sent: list = []

    def send(self, phone: str, text: str) -> bool:
        log.info("SMS -> %s : %s", phone, text[:80])
        LogSmsProvider.sent.append((phone, text))
        return True


class HttpSmsProvider:
    """Generic JSON SMS API: POST {to, message, sender} with a bearer key."""

    def send(self, phone: str, text: str) -> bool:
        if not settings.sms_api_url or not settings.sms_api_key:
            return False
        req = urllib.request.Request(
            settings.sms_api_url,
            data=json.dumps({"to": phone, "message": text, "sender": settings.sms_sender}).encode(),
            headers={"Authorization": f"Bearer {settings.sms_api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - configured URL
                return 200 <= resp.status < 300
        except OSError:
            return False


def push_provider():
    return HttpPushProvider() if settings.push_provider == "http" else LogPushProvider()


def sms_provider():
    return HttpSmsProvider() if settings.sms_provider == "http" else LogSmsProvider()


# --------------------------------------------------------------------------- authorization & targeting


def _ensure_scope(db: Session, sender: User, n: Notification) -> None:
    """Raise unless ``sender`` may address the notification's target."""
    from .deps import can_view_user, is_course_staff

    role, t, ids = sender.role, n.target_type, n.target_ids
    if role == Role.UNIVERSITY_ADMIN:
        ok = True
        if t == "faculty":
            ok = all((f := db.get(Faculty, i)) and f.university_id == sender.university_id for i in ids)
        elif t == "department":
            ok = all((d := db.get(Department, i)) and d.university_id == sender.university_id for i in ids)
        elif t == "course":
            ok = all((c := db.get(Course, i)) and c.university_id == sender.university_id for i in ids)
        elif t in ("user", "users"):
            ok = all((u := db.get(User, i)) and u.university_id == sender.university_id for i in ids)
        if not ok:
            raise NotificationError("جهة الاستلام خارج نطاق المؤسسة")
        return
    if role == Role.FACULTY_ADMIN:
        fid = sender.faculty_id
        if t == "university":
            raise NotificationError("لا يمكن لإدارة الكلية الإرسال على مستوى الجامعة")
        if t == "faculty" and ids != [fid]:
            raise NotificationError("يمكنك الإرسال إلى كليتك فقط")
        if t == "department" and not all((d := db.get(Department, i)) and d.faculty_id == fid for i in ids):
            raise NotificationError("القسم خارج نطاق كليتك")
        if t == "course" and not all((c := db.get(Course, i)) and c.faculty_id == fid for i in ids):
            raise NotificationError("المقرر خارج نطاق كليتك")
        if t in ("user", "users") and not all(
            (u := db.get(User, i)) and u.university_id == sender.university_id and u.faculty_id == fid for i in ids
        ):
            raise NotificationError("المستلم خارج نطاق كليتك")
        return
    if role in Role.INSTRUCTORS:
        if t == "course":
            if not all(is_course_staff(db, sender, i) for i in ids):
                raise NotificationError("يمكنك الإرسال لطلبة مقرراتك فقط")
            return
        if t in ("user", "users"):
            for i in ids:
                u = db.get(User, i)
                if not u or u.role != Role.STUDENT or not can_view_user(db, sender, u):
                    raise NotificationError("يمكنك الإرسال لطلبة مقرراتك فقط")
            return
        raise NotificationError("نطاق الإرسال غير مسموح لعضو هيئة التدريس")
    if role == Role.STAFF:
        if t == "faculty" and sender.faculty_id and ids == [sender.faculty_id]:
            return
        if t in ("user", "users"):
            for i in ids:
                u = db.get(User, i)
                if not u or not can_view_user(db, sender, u):
                    raise NotificationError("المستلم خارج نطاق صلاحياتك")
            return
        raise NotificationError("نطاق الإرسال غير مسموح للموظف")
    raise NotificationError("غير مصرح لك بإرسال الإشعارات")


def validate_new(db: Session, sender: User, n: Notification) -> None:
    if n.category not in CATEGORIES or sender.role not in CATEGORY_ISSUERS[n.category]:
        raise NotificationError("غير مصرح لك بإصدار هذا النوع من الإشعارات")
    if n.priority not in PRIORITIES:
        raise NotificationError("أولوية غير صحيحة")
    if n.target_type not in TARGET_TYPES:
        raise NotificationError("نوع المستلمين غير صحيح")
    if n.target_type == "user" and len(n.target_ids) != 1:
        raise NotificationError("حدد مستلماً واحداً")
    if n.target_type != "university" and not n.target_ids:
        raise NotificationError("حدد جهة الاستلام")
    if n.category == "official_warning" and n.target_type not in ("user", "users", "course", "cohort"):
        raise NotificationError("التحذير الرسمي يوجه إلى طلبة محددين")
    _ensure_scope(db, sender, n)


def resolve_recipients(db: Session, n: Notification) -> list[int]:
    q = select(User.id).where(User.university_id == n.university_id, User.is_active.is_(True))
    t, ids = n.target_type, n.target_ids
    if t in ("user", "users"):
        q = q.where(User.id.in_(ids))
    elif t == "course":
        students = select(Enrollment.student_id).where(Enrollment.course_id.in_(ids), Enrollment.status == "active")
        staff = select(CourseStaff.user_id).where(CourseStaff.course_id.in_(ids))
        if n.audience == "students":
            q = q.where(User.id.in_(students))
        elif n.audience == "staff":
            q = q.where(User.id.in_(staff))
        else:
            q = q.where(User.id.in_(students) | User.id.in_(staff))
    elif t == "department":
        q = q.where(User.department_id.in_(ids))
    elif t == "faculty":
        q = q.where(User.faculty_id.in_(ids))
    elif t == "cohort":
        q = q.where(User.cohort.in_([str(i) for i in ids]))
        sender = db.get(User, n.sender_id) if n.sender_id else None
        if sender and sender.role == Role.FACULTY_ADMIN:
            q = q.where(User.faculty_id == sender.faculty_id)
    if t not in ("user", "users", "course"):
        if n.audience == "students":
            q = q.where(User.role == Role.STUDENT)
        elif n.audience == "staff":
            q = q.where(User.role != Role.STUDENT)
    if n.category == "official_warning":
        q = q.where(User.role == Role.STUDENT)
    return sorted(set(db.scalars(q)))


# --------------------------------------------------------------------------- dispatch


def _wants(user: User, n: Notification, channel: str) -> bool:
    prefs = user.notification_prefs or {}
    if n.category in UNMUTABLE or n.priority == "urgent":
        return True
    if n.category in prefs.get("muted_categories", []):
        return channel == "inapp"  # muted categories still land in the inbox, silently
    return prefs.get(channel, True)


def dispatch(db: Session, n: Notification) -> int:
    """Deliver a notification now. Returns the number of recipients."""
    uni = db.get(University, n.university_id)
    cfg = effective_settings(uni)["notifications"]
    recipients = resolve_recipients(db, n)
    push = push_provider() if "push" in n.channels else None
    sms_allowed = (
        "sms" in n.channels
        and cfg.get("sms_enabled")
        and (n.priority == "urgent" or n.category in cfg.get("sms_categories", []))
    )
    sms = sms_provider() if sms_allowed else None
    existing = set(db.scalars(select(NotificationDelivery.user_id).where(NotificationDelivery.notification_id == n.id)))
    for uid in recipients:
        if uid in existing:
            continue
        user = db.get(User, uid)
        d = NotificationDelivery(notification_id=n.id, user_id=uid)
        if push:
            if _wants(user, n, "push"):
                tokens = list(db.scalars(select(DeviceToken.token).where(DeviceToken.user_id == uid)))
                ok = [push.send(tok, n.title, n.body[:200], {"notification_id": n.id, "link": n.link}) for tok in tokens]
                d.push_status = "sent" if ok and all(ok) else ("failed" if ok else "no_device")
            else:
                d.push_status = "skipped"
        if sms:
            if user.phone and _wants(user, n, "sms"):
                d.sms_status = "sent" if sms.send(user.phone, f"{n.title}: {n.body}"[:300]) else "failed"
            else:
                d.sms_status = "skipped"
        db.add(d)
    n.status = "sent"
    n.sent_at = utcnow()
    n.recipients_count = len(recipients)
    if n.priority in ("important", "urgent") or n.category in ("official_warning", "admin_notice"):
        audit.record(
            db, "notification.sent", university_id=n.university_id,
            actor=db.get(User, n.sender_id) if n.sender_id else None,
            target_type="notification", target_id=n.id,
            details={"category": n.category, "priority": n.priority, "target": n.target_type,
                     "target_ids": n.target_ids, "recipients": len(recipients), "title": n.title},
        )
    db.flush()
    return len(recipients)


def create(db: Session, *, sender: User | None, university_id: int, category: str, title: str, body: str,
           target_type: str, target_ids: Iterable, priority: str = "normal", audience: str = "students",
           channels: Iterable[str] = ("inapp", "push"), course_id: int | None = None, link: str | None = None,
           scheduled_at=None, validate: bool = True) -> Notification:
    n = Notification(
        university_id=university_id, sender_id=sender.id if sender else None, category=category,
        priority=priority, title=title.strip(), body=body.strip(), target_type=target_type,
        target_ids=list(target_ids), audience=audience, channels=sorted(set(channels) | {"inapp"}),
        course_id=course_id, link=link, scheduled_at=scheduled_at, status="scheduled",
    )
    if validate:
        if sender is None:
            raise NotificationError("sender required")
        validate_new(db, sender, n)
    db.add(n)
    db.flush()
    if scheduled_at is None or scheduled_at <= utcnow():
        dispatch(db, n)
    return n


def notify_users(db: Session, university_id: int, user_ids: Iterable[int], title: str, body: str, *,
                 category: str = "system", priority: str = "normal", link: str | None = None,
                 course_id: int | None = None, sender: User | None = None) -> Notification | None:
    """Automated notification raised by the platform itself (no authority check)."""
    ids = sorted(set(user_ids))
    if not ids:
        return None
    return create(
        db, sender=sender, university_id=university_id, category=category, title=title, body=body,
        target_type="users", target_ids=ids, priority=priority, course_id=course_id, link=link,
        validate=False,
    )


def dispatch_due(db: Session) -> int:
    count = 0
    due = db.scalars(
        select(Notification).where(Notification.status == "scheduled", Notification.scheduled_at <= utcnow())
    ).all()
    for n in due:
        dispatch(db, n)
        count += 1
    return count
