"""Two-factor authentication policy and SMS one-time codes.

Who must use a second factor (any one reason is enough):
  * the platform administrator, always;
  * an account an administrator marked as "required" (MfaPreference.forced);
  * administrators, when the university's security.require_mfa_for_admins is on;
  * every role listed in security.mfa_required_roles;
  * everyone holding a capability listed in security.mfa_required_capabilities (see permissions.py).

Methods: "totp" (authenticator app) and "sms" (code sent to the account's phone), limited by
security.mfa_methods and by whether an SMS provider is configured.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import permissions
from .config import settings
from .db import utcnow
from .models import MfaPreference, OtpChallenge, Role, User

log = logging.getLogger("nus.mfa")

METHODS = ("totp", "sms")
CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_AFTER_SECONDS = 60


class OtpError(Exception):
    pass


def preference(db: Session, user: User) -> MfaPreference | None:
    return db.scalar(select(MfaPreference).where(MfaPreference.user_id == user.id))


def method_of(db: Session, user: User) -> str:
    pref = preference(db, user)
    return pref.method if pref and pref.method in METHODS else "totp"


def _security(db: Session, user: User) -> dict:
    if user.university_id is None:
        return {}
    from .deps import tenant_settings

    return tenant_settings(db, user).get("security", {})


def required_for(db: Session, user: User) -> bool:
    if user.role == Role.PLATFORM_ADMIN:
        return True
    pref = preference(db, user)
    if pref and pref.forced:
        return True
    sec = _security(db, user)
    if user.role in Role.ADMINS and sec.get("require_mfa_for_admins"):
        return True
    if user.role in (sec.get("mfa_required_roles") or []):
        return True
    caps = [c for c in (sec.get("mfa_required_capabilities") or []) if c in permissions.CAPABILITIES]
    return any(permissions.allowed(db, user, c) for c in caps)


def sms_available() -> bool:
    # the log provider only writes to the server log, so it counts only during development
    return settings.sms_provider in ("resala", "http") or settings.env == "development"


def allowed_methods(db: Session, user: User) -> list[str]:
    wanted = _security(db, user).get("mfa_methods") or list(METHODS)
    return [m for m in METHODS if m in wanted and (m != "sms" or sms_available())]


def phone_hint(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"{digits[:3]}•••{digits[-3:]}" if len(digits) >= 6 else "•••"


def _hash(challenge_salt: str, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{challenge_salt}:{code}".encode(), hashlib.sha256).hexdigest()


def _deliver(phone: str) -> tuple[str, str | None]:
    """Sends a code to the phone. Returns (code, provider reference)."""
    if settings.sms_provider == "resala":
        from .resala import ResalaClient, ResalaError, libyan_mobile

        number = libyan_mobile(phone) or "".join(ch for ch in phone if ch.isdigit())
        try:
            pin = ResalaClient.from_env().send_pin(number, service_name=settings.resala_service_name,
                                                   test=settings.resala_test or None, sender=settings.resala_sender)
        except ResalaError as exc:
            log.warning("Resala pin failed: %s", exc.type)
            raise OtpError("تعذر إرسال رمز التحقق الآن، حاول بعد قليل") from None
        return pin.pin, pin.id
    from .notifications import sms_provider

    code = f"{secrets.randbelow(1_000_000):06d}"
    if not sms_provider().send(phone, f"رمز التحقق: {code} - منصة الجامعة"):
        raise OtpError("تعذر إرسال رمز التحقق الآن، حاول بعد قليل")
    return code, None


def start(db: Session, user: User, purpose: str) -> dict:
    """Sends a new code by SMS. At most one per minute; never re-sends automatically."""
    if not user.phone:
        raise OtpError("لا يوجد رقم هاتف مسجل لحسابك، تواصل مع الإدارة")
    now = utcnow()
    last = db.scalar(select(OtpChallenge).where(OtpChallenge.user_id == user.id)
                     .order_by(OtpChallenge.id.desc()).limit(1))
    if last and (now - last.created_at).total_seconds() < RESEND_AFTER_SECONDS:
        wait = RESEND_AFTER_SECONDS - int((now - last.created_at).total_seconds())
        return {"sent": False, "retry_after": wait, "phone_hint": phone_hint(user.phone)}
    recent = db.scalars(select(OtpChallenge.id).where(OtpChallenge.user_id == user.id,
                                                      OtpChallenge.created_at > now - timedelta(hours=1))).all()
    if len(recent) >= 6:
        raise OtpError("طلبت رموزاً كثيرة، حاول بعد ساعة")
    code, ref = _deliver(user.phone)
    salt = secrets.token_hex(8)
    db.add(OtpChallenge(user_id=user.id, purpose=purpose, code_hash=f"{salt}${_hash(salt, code)}",
                        provider_ref=ref, expires_at=now + CODE_TTL, created_at=now))
    db.flush()
    return {"sent": True, "retry_after": RESEND_AFTER_SECONDS, "phone_hint": phone_hint(user.phone),
            "expires_in": int(CODE_TTL.total_seconds())}


def verify(db: Session, user: User, purpose: str, code: str) -> bool:
    """Checks the latest unexpired code for this purpose; each code works once."""
    now = utcnow()
    ch = db.scalar(select(OtpChallenge).where(
        OtpChallenge.user_id == user.id, OtpChallenge.purpose == purpose, OtpChallenge.consumed_at.is_(None),
        OtpChallenge.expires_at > now).order_by(OtpChallenge.id.desc()).limit(1))
    if not ch or ch.attempts >= MAX_ATTEMPTS:
        return False
    ch.attempts += 1
    salt, digest = ch.code_hash.split("$", 1)
    if not hmac.compare_digest(digest, _hash(salt, code.strip())):
        return False
    ch.consumed_at = now
    return True


def set_method(db: Session, user: User, method: str) -> None:
    pref = preference(db, user)
    if not pref:
        pref = MfaPreference(user_id=user.id)
        db.add(pref)
    pref.method = method
    pref.updated_at = utcnow()
