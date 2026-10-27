"""Central multi-channel notification service.

Channels: in-app inbox (always), push (FCM/APNs via a provider), SMS (external API).
Provider credentials stay on the server; clients only register device tokens.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

import jwt

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, permissions
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

# Who may issue which category: permissions.CAPABILITIES ("notify.*"), configurable per university.


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


# Tones bundled in the app (res/raw/tone_<name>.wav, one Android channel "nus_tone_<name>" each).
# The platform administrator picks which tone each kind of notification plays in each
# university (settings.notifications.tones); nobody else can change it.
TONES = {
    "chime": "جرس هادئ",
    "bell": "جرس",
    "rising": "ثلاث نغمات صاعدة",
    "pulse": "نبضتان",
    "alarm": "إنذار متكرر",
    "siren": "تنبيه حاد",
}
# Sounds the app may play once when it opens (res/raw/tone_<name>.wav as well).
LAUNCH_SOUNDS = {
    "welcome": "ترحيب",
    "sparkle": "لمعة",
    "harp": "قيثارة",
}
TONE_SLOTS = {"normal": "عادي", "important": "مهم", "urgent": "عاجل", "official_warning": "إنذار رسمي"}
DEFAULT_TONES = {"normal": "chime", "important": "rising", "urgent": "alarm", "official_warning": "siren"}


def tone_for(priority: str | None, category: str | None) -> str:
    """Which slot a notification belongs to: official_warning, urgent, important or normal."""
    if category == "official_warning":
        return "official_warning"
    if priority == "urgent":
        return "urgent"
    return "important" if priority == "important" else "normal"


def tone_name(slot: str, tones: dict | None) -> str:
    name = (tones or {}).get(slot) or DEFAULT_TONES[slot]
    return name if name in TONES else DEFAULT_TONES[slot]


class FcmProvider:
    """Firebase Cloud Messaging HTTP v1, authenticated with a service-account key.

    Returns "sent", "invalid" (token no longer registered: caller deletes it) or "failed".
    """

    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self, credentials_file: str) -> None:
        info = json.loads(Path(credentials_file).read_text())
        self.project_id = info["project_id"]
        self.client_email = info["client_email"]
        self.private_key = info["private_key"]
        self.token_uri = info.get("token_uri", "https://oauth2.googleapis.com/token")
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires - 60:
                return self._token
            now = int(time.time())
            assertion = jwt.encode(
                {"iss": self.client_email, "scope": self.SCOPE, "aud": self.token_uri, "iat": now, "exp": now + 3600},
                self.private_key, algorithm="RS256",
            )
            body = urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion,
            }).encode()
            with urllib.request.urlopen(urllib.request.Request(self.token_uri, data=body), timeout=15) as resp:  # noqa: S310
                data = json.loads(resp.read())
            self._token = data["access_token"]
            self._expires = time.time() + int(data.get("expires_in", 3600))
            return self._token

    # last outcome, shown in /api/notifications/health to diagnose delivery problems
    last_error: str | None = None
    last_error_at: float | None = None
    last_sent_at: float | None = None

    def send(self, token: str, title: str, body: str, data: dict) -> str:
        tone = data.get("tone") if data.get("tone") in TONES else \
            DEFAULT_TONES[tone_for(data.get("priority"), data.get("category"))]
        message = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": {k: "" if v is None else str(v) for k, v in data.items()},
                # the channel decides the tone (Android 8+); "sound" covers older phones
                "android": {"priority": "high",
                            "notification": {"channel_id": f"nus_tone_{tone}", "sound": f"tone_{tone}"}},
                "apns": {"payload": {"aps": {"sound": "default"}}},
            }
        }
        req = urllib.request.Request(
            f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send",
            data=json.dumps(message).encode(),
            headers={"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed Google endpoint
                ok = 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            if exc.code == 404 or "UNREGISTERED" in detail or (exc.code == 400 and "registration token" in detail):
                return "invalid"
            log.warning("FCM error %s: %s", exc.code, detail[:300])
            self._failed(f"HTTP {exc.code}: {detail[:300]}")
            return "failed"
        except Exception as exc:  # noqa: BLE001 - network, TLS or OAuth token errors
            log.warning("FCM unreachable: %s", exc)
            self._failed(f"{type(exc).__name__}: {str(exc)[:300]}")
            return "failed"
        if ok:
            FcmProvider.last_sent_at = time.time()
        return "sent" if ok else "failed"

    @staticmethod
    def _failed(message: str) -> None:
        FcmProvider.last_error, FcmProvider.last_error_at = message, time.time()


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


# last SMS failure, shown to administrators in /api/notifications/health
LAST_SMS_ERROR: dict | None = None


def record_sms_error(kind: str, exc) -> None:
    global LAST_SMS_ERROR
    from .resala import ResalaError, explain

    summary = explain(exc, sent_vars=template_var_count() if kind == "template" else None) \
        if isinstance(exc, ResalaError) else str(exc)
    LAST_SMS_ERROR = {"kind": kind, "summary": summary, "type": getattr(exc, "type", type(exc).__name__),
                      "status": getattr(exc, "status", None), "message": getattr(exc, "message", str(exc))[:300],
                      "errors": getattr(exc, "errors", {}), "at": time.time()}


TEMPLATE_FIELDS = ("message", "title", "text", "signature")


def template_fields() -> list[str]:
    return [f.strip() for f in settings.resala_template_fields.split(",") if f.strip()]


def template_var_count() -> int:
    return len(template_fields()) if settings.resala_template_fields.strip() else settings.resala_template_vars


def template_params(title: str, body: str, signature: str = "") -> list[str]:
    """The template's $1, $2… for a notification: RESALA_TEMPLATE_FIELDS, else RESALA_TEMPLATE_VARS."""
    names = template_fields()
    if names:
        values = {"message": (f"{title}: {body}" if body else title)[:300], "title": title[:120],
                  "text": body[:300], "signature": signature[:120]}
        return [values.get(name, "") for name in names]
    n = settings.resala_template_vars
    if n <= 0:
        return []
    if n == 1:
        return [f"{title}: {body}"[:300] if body else title[:300]]
    return [title[:120], body[:300]] + [""] * (n - 2)


class ResalaSmsProvider:
    """Resala (resala.ly): one template request for the whole batch (variables: see template_params).

    Never retried: a failed request may already have delivered some messages.
    """

    def __init__(self, client=None) -> None:
        from .resala import ResalaClient

        self.client = client or ResalaClient.from_env()

    def send_many(self, items: list[tuple[str, str, str]], signature: str = "") -> dict[str, bool]:
        from .resala import ResalaError, TemplateRecord, libyan_mobile

        result = {phone: False for phone, _, _ in items}
        records, by_number = [], {}
        for phone, title, body in items:
            number = libyan_mobile(phone)
            if number:  # the API only delivers notifications to Libyan mobiles
                records.append(TemplateRecord(number, template_params(title, body, signature)))
                by_number[number[-9:]] = phone
        if not records:
            return result
        if not settings.resala_sms_template_id:
            record_sms_error("template", Exception("RESALA_SMS_TEMPLATE_ID غير مضبوط في /etc/nus/nus.env"))
            return result
        try:
            res = self.client.send_template(settings.resala_sms_template_id, records, test=settings.resala_test or None,
                                            sender=settings.resala_sender)
        except ResalaError as exc:
            log.warning("Resala send-template failed: %s %s", exc.type, exc.message)
            record_sms_error("template", exc)
            return result
        bad = {str(n)[-9:] for n in res.failed_numbers + res.invalid_numbers}
        for tail, phone in by_number.items():
            result[phone] = tail not in bad
        return result

    def send(self, phone: str, text: str) -> bool:
        return self.send_many([(phone, text, "")]).get(phone, False)


def sms_signature(db: Session, sender: User | None, university_id: int | None, faculty_id: int | None = None) -> str:
    """Who the message is from: "كلية تقنية المعلومات بجامعة نالوت", or the university alone."""
    uni = db.get(University, university_id) if university_id else None
    uni_name = (uni.name if uni else "").strip()
    fid = faculty_id or (sender.faculty_id if sender else None)
    fac = db.get(Faculty, fid) if fid else None
    if not fac:
        return uni_name
    return f"{fac.name} ب{uni_name}" if uni_name.startswith("جامعة") else f"{fac.name} - {uni_name}".strip(" -")


def send_sms_batch(provider, items: list[tuple[str, str, str]], signature: str = "") -> dict[str, bool]:
    """(phone, title, body) -> delivered?  One request when the provider supports batches."""
    if hasattr(provider, "send_many"):
        return provider.send_many(items, signature=signature)
    return {phone: provider.send(phone, f"{title}: {body}"[:300]) for phone, title, body in items}


_fcm: FcmProvider | None = None


def push_provider():
    global _fcm
    mode = settings.push_provider
    if mode == "http":
        return HttpPushProvider()
    if mode == "fcm" or (mode == "auto" and Path(settings.fcm_credentials_file).is_file()):
        if _fcm is None:
            _fcm = FcmProvider(settings.fcm_credentials_file)
        return _fcm
    return LogPushProvider()


def sms_provider():
    if settings.sms_provider == "resala":
        return ResalaSmsProvider()
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


def may_issue(db: Session, sender: User, category: str) -> bool:
    """Category rights come from the university's permission matrix (see permissions.py)."""
    if category not in CATEGORIES or category == "system":
        return False
    return permissions.allowed(db, sender, f"notify.{category}")


def validate_new(db: Session, sender: User, n: Notification, *, automatic: bool = False) -> None:
    # automatic notices (an assignment published, results released) follow from an action the
    # sender is already allowed to take, so they skip the category rights check
    if n.category not in CATEGORIES or (not automatic and not may_issue(db, sender, n.category)):
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


def dispatch(db: Session, n: Notification) -> int:
    """Deliver a notification now. Returns the number of recipients."""
    uni = db.get(University, n.university_id)
    cfg = effective_settings(uni)["notifications"]
    recipients = resolve_recipients(db, n)
    push = "push" in n.channels
    sms_allowed = (
        "sms" in n.channels
        and cfg.get("sms_enabled")
        and (n.priority == "urgent" or n.category in cfg.get("sms_categories", []))
    )
    sms = sms_provider() if sms_allowed else None
    existing = set(db.scalars(select(NotificationDelivery.user_id).where(NotificationDelivery.notification_id == n.id)))
    sms_queue: list[tuple[NotificationDelivery, str]] = []
    for uid in recipients:
        if uid in existing:
            continue
        user = db.get(User, uid)
        d = NotificationDelivery(notification_id=n.id, user_id=uid)
        if push:
            # what reaches users is set by the administration only; personal preferences are not applied
            if db.scalar(select(DeviceToken.id).where(DeviceToken.user_id == uid).limit(1)):
                d.push_status = "pending"  # sent by the background worker, outside the request
            else:
                d.push_status = "no_device"
        if sms:
            if user.phone:
                sms_queue.append((d, user.phone))
            else:
                d.sms_status = "skipped"
        db.add(d)
    if sms_queue:
        try:
            sender = db.get(User, n.sender_id) if n.sender_id else None
            # a faculty-wide notice from the university administration is signed by that faculty
            target_faculty = n.target_ids[0] if n.target_type == "faculty" and len(n.target_ids) == 1 else None
            signature = sms_signature(db, sender, n.university_id, target_faculty)
            delivered = send_sms_batch(sms, [(phone, n.title, n.body) for _, phone in sms_queue], signature=signature)
        except Exception:  # noqa: BLE001 - an SMS outage must not fail the notification
            log.exception("SMS batch failed")
            delivered = {}
        for d, phone in sms_queue:
            d.sms_status = "sent" if delivered.get(phone) else "failed"
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
    if push:
        from . import worker

        worker.kick()
    return len(recipients)


def send_pending_pushes(db: Session, provider=None, limit: int = 500) -> int:
    """Deliver queued push notifications. Tokens the provider reports as invalid are deleted."""
    provider = provider or push_provider()
    rows = db.scalars(select(NotificationDelivery).where(NotificationDelivery.push_status == "pending")
                      .order_by(NotificationDelivery.id).limit(limit)).all()
    tones_by_uni: dict[int, dict] = {}
    for d in rows:
        n = d.notification
        if n.university_id not in tones_by_uni:
            tones_by_uni[n.university_id] = effective_settings(db.get(University, n.university_id))["notifications"].get("tones", {})
        tone = tone_name(tone_for(n.priority, n.category), tones_by_uni[n.university_id])
        results = []
        for dev in db.scalars(select(DeviceToken).where(DeviceToken.user_id == d.user_id)).all():
            result = provider.send(dev.token, n.title, n.body[:200],
                                   {"notification_id": n.id, "category": n.category, "priority": n.priority,
                                    "tone": tone, "link": n.link})
            if result == "invalid":
                db.delete(dev)
                continue
            results.append(result in (True, "sent"))
        d.push_status = "sent" if results and any(results) else ("failed" if results else "no_device")
    db.flush()
    return len(rows)


def create(db: Session, *, sender: User | None, university_id: int, category: str, title: str, body: str,
           target_type: str, target_ids: Iterable, priority: str = "normal", audience: str = "students",
           channels: Iterable[str] = ("inapp", "push"), course_id: int | None = None, link: str | None = None,
           scheduled_at=None, validate: bool = True, automatic: bool = False) -> Notification:
    n = Notification(
        university_id=university_id, sender_id=sender.id if sender else None, category=category,
        priority=priority, title=title.strip(), body=body.strip(), target_type=target_type,
        target_ids=list(target_ids), audience=audience, channels=sorted(set(channels) | {"inapp"}),
        course_id=course_id, link=link, scheduled_at=scheduled_at, status="scheduled",
    )
    if validate:
        if sender is None:
            raise NotificationError("sender required")
        validate_new(db, sender, n, automatic=automatic)
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
