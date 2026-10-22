from __future__ import annotations

import io
import logging
import re
from datetime import timedelta

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import audit, mfa, permissions
from ..config import settings
from ..db import get_db, utcnow
from ..deps import client_ip, get_current_user, tenant_settings
from ..models import AuthSession, DeviceToken, Faculty, PasswordResetToken, Role, University, User
from ..notifications import sms_provider
from ..security import (
    DUMMY_HASH,
    create_access_token,
    decode_token,
    decrypt_str,
    encrypt_str,
    hash_password,
    limiter,
    new_opaque_token,
    new_totp_secret,
    password_problems,
    sha256_hex,
    totp_uri,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/api", tags=["auth"])
log = logging.getLogger("nus.auth")

REFRESH_COOKIE = "nus_refresh"
GENERIC_LOGIN_ERROR = "بيانات الدخول غير صحيحة"


def normalize_identifier(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    if "@" in value:
        return "email", value.lower()
    digits = re.sub(r"[^\d+]", "", value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    return "phone", digits


def find_user(db: Session, identifier: str) -> User | None:
    kind, value = normalize_identifier(identifier)
    if not value:
        return None
    col = User.email if kind == "email" else User.phone
    return db.scalar(select(User).where(col == value))


def mfa_required_for(db: Session, user: User) -> bool:
    return mfa.required_for(db, user)


def _mfa_options(db: Session, user: User) -> dict:
    return {"methods": mfa.allowed_methods(db, user), "phone_hint": mfa.phone_hint(user.phone)}


def user_profile(db: Session, user: User) -> dict:
    uni = db.get(University, user.university_id) if user.university_id else None
    fac = db.get(Faculty, user.faculty_id) if user.faculty_id else None
    cfg = tenant_settings(db, user) if uni else None
    return {
        "id": user.id, "full_name": user.full_name, "role": user.role, "email": user.email, "phone": user.phone,
        "code": user.code, "cohort": user.cohort, "office": user.office,
        "university": {"id": uni.id, "name": uni.name, "code": uni.code} if uni else None,
        "faculty": {"id": fac.id, "name": fac.name} if fac else None,
        "department_id": user.department_id,
        "mfa_enabled": user.mfa_enabled, "mfa_required": mfa_required_for(db, user),
        "mfa_method": mfa.method_of(db, user) if user.mfa_enabled else None,
        "mfa_methods": mfa.allowed_methods(db, user),
        "must_change_password": user.must_change_password,
        "notification_prefs": user.notification_prefs or {},
        "branding": cfg["branding"] if cfg else None,
        # the platform administrator managing this university (see deps.ACT_HEADER)
        "acting": bool(getattr(user, "acting_platform_admin", False)),
        # configurable capabilities this account holds, so clients show only what will work
        "archive_offices": cfg["archive"]["offices"] if cfg else [],
        "can": [k for k in permissions.CAPABILITIES if permissions.allowed(db, user, k)] if uni else [],
    }


def _issue_session(db: Session, user: User, request: Request, response: Response, *,
                   include_refresh: bool = False) -> dict:
    refresh = new_opaque_token()
    db.add(AuthSession(
        user_id=user.id, token_hash=sha256_hex(refresh),
        expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        user_agent=(request.headers.get("user-agent") or "")[:300], ip=client_ip(request),
    ))
    user.last_login_at = utcnow()
    response.set_cookie(
        REFRESH_COOKIE, refresh, max_age=settings.refresh_token_days * 86400, httponly=True,
        secure=settings.cookie_secure, samesite="strict", path="/api/auth",
    )
    out = {
        "access_token": create_access_token(user.id, role=user.role, university_id=user.university_id),
        "token_type": "bearer", "expires_in": settings.access_token_minutes * 60,
        "user": user_profile(db, user),
    }
    # Native mobile clients keep the refresh token in the OS secure storage.
    if include_refresh or request.headers.get("x-client") == "mobile":
        out["refresh_token"] = refresh
    return out


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    mfa_code: str | None = Field(default=None, max_length=10)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request) or "?"
    _, ident = normalize_identifier(body.identifier)
    if not limiter.hit(f"login-ip:{ip}", 30, 300) or not limiter.hit(f"login-id:{ident}", 10, 300):
        raise HTTPException(status_code=429, detail="محاولات كثيرة، حاول لاحقاً")
    user = find_user(db, body.identifier)
    if not user:
        verify_password(body.password, DUMMY_HASH)  # equalise timing
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=423, detail="تم قفل الحساب مؤقتاً بسبب محاولات فاشلة متكررة")

    def fail(reason: str):
        user.failed_logins += 1
        if user.failed_logins >= settings.max_login_failures:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_logins = 0
            audit.record(db, "auth.locked", actor=user, ip=ip, target_type="user", target_id=user.id)
        audit.record(db, "auth.login_failed", actor=user, ip=ip, details={"reason": reason})
        db.commit()
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR if reason == "password" else "رمز التحقق غير صحيح")

    if not verify_password(body.password, user.password_hash):
        fail("password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="الحساب موقوف")

    if user.mfa_enabled:
        method = mfa.method_of(db, user)
        if method == "sms":
            if not body.mfa_code:
                # the password was right: send (or, within a minute, don't re-send) the SMS code
                try:
                    sent = mfa.start(db, user, "login")
                except mfa.OtpError as exc:
                    db.commit()
                    raise HTTPException(status_code=400, detail=str(exc)) from None
                db.commit()
                return {"mfa_required": True, "method": "sms", **sent}
            if not mfa.verify(db, user, "login", body.mfa_code):
                fail("mfa")
        else:
            if not body.mfa_code:
                return {"mfa_required": True, "method": "totp"}
            secret = decrypt_str(user.mfa_secret_enc or "")
            if not secret or not verify_totp(secret, body.mfa_code):
                fail("mfa")
    elif mfa_required_for(db, user):
        user.failed_logins = 0
        db.commit()
        return {
            "mfa_setup_required": True, **_mfa_options(db, user),
            "setup_token": create_access_token(user.id, role=user.role, university_id=user.university_id,
                                               purpose="mfa_setup", minutes=10),
        }

    user.failed_logins = 0
    user.locked_until = None
    out = _issue_session(db, user, request, response)
    audit.record(db, "auth.login", actor=user, ip=ip)
    db.commit()
    return out


def _user_from_setup_or_access(request: Request, db: Session) -> tuple[User, bool]:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    for purpose, is_setup in (("access", False), ("mfa_setup", True)):
        payload = decode_token(token, purpose=purpose)
        if payload:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active:
                return user, is_setup
    raise HTTPException(status_code=401, detail="يلزم تسجيل الدخول")


@router.post("/auth/mfa/setup")
def mfa_setup(request: Request, db: Session = Depends(get_db)):
    user, _ = _user_from_setup_or_access(request, db)
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="المصادقة الثنائية مفعلة مسبقاً")
    if "totp" not in mfa.allowed_methods(db, user):
        raise HTTPException(status_code=400, detail="تطبيق المصادقة غير متاح في مؤسستك")
    secret = new_totp_secret()
    user.mfa_secret_enc = encrypt_str(secret)
    db.commit()
    issuer = "منصة الجامعة"
    uri = totp_uri(secret, user.email or user.phone or str(user.id), issuer)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": buf.getvalue().decode()}


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


@router.post("/auth/mfa/enable")
def mfa_enable(body: CodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user, is_setup = _user_from_setup_or_access(request, db)
    if not limiter.hit(f"mfa:{user.id}", 10, 300):
        raise HTTPException(status_code=429, detail="محاولات كثيرة")
    secret = decrypt_str(user.mfa_secret_enc or "")
    if not secret or not verify_totp(secret, body.code):
        raise HTTPException(status_code=400, detail="رمز التحقق غير صحيح")
    user.mfa_enabled = True
    mfa.set_method(db, user, "totp")
    audit.record(db, "auth.mfa_enabled", actor=user, ip=client_ip(request), details={"method": "totp"})
    out = _issue_session(db, user, request, response) if is_setup else {"ok": True}
    db.commit()
    return out


class PasswordConfirm(BaseModel):
    password: str
    code: str


@router.post("/auth/mfa/disable")
def mfa_disable(body: PasswordConfirm, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    if mfa_required_for(db, user):
        raise HTTPException(status_code=400, detail="المصادقة الثنائية إلزامية لحسابك")
    if mfa.method_of(db, user) == "sms":
        second = mfa.verify(db, user, "verify", body.code)
    else:
        secret = decrypt_str(user.mfa_secret_enc or "")
        second = bool(secret) and verify_totp(secret, body.code)
    if not verify_password(body.password, user.password_hash) or not second:
        db.commit()  # keep the attempt count
        raise HTTPException(status_code=400, detail="بيانات التحقق غير صحيحة")
    user.mfa_enabled, user.mfa_secret_enc = False, None
    audit.record(db, "auth.mfa_disabled", actor=user, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/auth/mfa/options")
def mfa_options(request: Request, db: Session = Depends(get_db)):
    user, _ = _user_from_setup_or_access(request, db)
    return {**_mfa_options(db, user), "enabled": user.mfa_enabled,
            "method": mfa.method_of(db, user) if user.mfa_enabled else None}


@router.post("/auth/mfa/sms/start")
def mfa_sms_start(request: Request, db: Session = Depends(get_db)):
    """Sends a code to confirm the phone (enrolment) or to confirm turning SMS verification off."""
    user, _ = _user_from_setup_or_access(request, db)
    if not user.mfa_enabled and "sms" not in mfa.allowed_methods(db, user):
        raise HTTPException(status_code=400, detail="التحقق برسالة نصية غير متاح في مؤسستك")
    try:
        out = mfa.start(db, user, "verify")
    except mfa.OtpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    return out


@router.post("/auth/mfa/sms/enable")
def mfa_sms_enable(body: CodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user, is_setup = _user_from_setup_or_access(request, db)
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="المصادقة الثنائية مفعلة مسبقاً")
    if "sms" not in mfa.allowed_methods(db, user):
        raise HTTPException(status_code=400, detail="التحقق برسالة نصية غير متاح في مؤسستك")
    if not limiter.hit(f"mfa:{user.id}", 10, 300):
        raise HTTPException(status_code=429, detail="محاولات كثيرة")
    if not mfa.verify(db, user, "verify", body.code):
        db.commit()
        raise HTTPException(status_code=400, detail="رمز التحقق غير صحيح أو منتهي")
    user.mfa_enabled, user.mfa_secret_enc = True, None
    mfa.set_method(db, user, "sms")
    audit.record(db, "auth.mfa_enabled", actor=user, ip=client_ip(request), details={"method": "sms"})
    out = _issue_session(db, user, request, response) if is_setup else {"ok": True}
    db.commit()
    return out


class RefreshIn(BaseModel):
    refresh_token: str | None = None


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="لا توجد جلسة")
    if body is None or not body.refresh_token:
        # cookie-based refresh from the browser: require a custom header (CSRF defence in depth)
        if request.headers.get("x-requested-with") != "nus-web":
            raise HTTPException(status_code=403, detail="طلب غير مسموح")
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256_hex(token)))
    now = utcnow()
    if not sess or sess.expires_at < now:
        raise HTTPException(status_code=401, detail="انتهت الجلسة")
    if sess.revoked_at is not None:
        # a rotated token was reused: assume theft and revoke every session of that user
        db.execute(update(AuthSession).where(AuthSession.user_id == sess.user_id, AuthSession.revoked_at.is_(None))
                   .values(revoked_at=now))
        audit.record(db, "auth.refresh_reuse", university_id=None, target_type="user", target_id=sess.user_id,
                     ip=client_ip(request))
        db.commit()
        raise HTTPException(status_code=401, detail="انتهت الجلسة")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="الحساب غير مفعل")
    sess.revoked_at = now
    out = _issue_session(db, user, request, response, include_refresh=bool(body and body.refresh_token))
    db.commit()
    return out


@router.post("/auth/logout")
def logout(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if token:
        sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256_hex(token)))
        if sess and not sess.revoked_at:
            sess.revoked_at = utcnow()
            db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


class ForgotIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)


@router.post("/auth/password/forgot")
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    if not limiter.hit(f"forgot:{client_ip(request)}", 5, 900):
        raise HTTPException(status_code=429, detail="محاولات كثيرة، حاول لاحقاً")
    user = find_user(db, body.identifier)
    if user and user.is_active and user.phone and mfa.sms_available():
        # a 6-digit code by SMS (easy to type on a phone), used with the identifier
        try:
            mfa.start(db, user, "reset")
            audit.record(db, "auth.reset_requested", actor=user, ip=client_ip(request), details={"via": "sms"})
        except mfa.OtpError:
            pass  # same answer either way; the user can ask again after a minute
        db.commit()
    elif user and user.is_active:
        token = new_opaque_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=sha256_hex(token),
                                  expires_at=utcnow() + timedelta(minutes=30)))
        audit.record(db, "auth.reset_requested", actor=user, ip=client_ip(request))
        db.commit()
        # E-mail delivery plugs in here; during development the token is written to the server log.
        if settings.env == "development":
            log.info("password reset token for user %s: %s", user.id, token)
    # identical answer whether or not the account exists
    return {"ok": True, "message": "إذا كان الحساب موجوداً فسيصلك رمز الاستعادة"}


class ResetIn(BaseModel):
    # either the long token, or the identifier with the 6-digit SMS code
    token: str | None = Field(default=None, min_length=10, max_length=200)
    identifier: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=10)
    new_password: str = Field(min_length=1, max_length=200)


@router.post("/auth/password/reset")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    if not limiter.hit(f"reset:{client_ip(request)}", 10, 900):
        raise HTTPException(status_code=429, detail="محاولات كثيرة، حاول لاحقاً")
    rt = None
    if body.token:
        rt = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256_hex(body.token)))
        if not rt or rt.used_at or rt.expires_at < utcnow():
            raise HTTPException(status_code=400, detail="رمز الاستعادة غير صالح أو منتهي")
        user = db.get(User, rt.user_id)
    else:
        user = find_user(db, body.identifier or "") if body.code else None
        # check the password rules first so a weak password does not use up the code
        if user and password_problems(body.new_password, identifiers=(user.email, user.phone)):
            raise HTTPException(status_code=400, detail="؛ ".join(
                password_problems(body.new_password, identifiers=(user.email, user.phone))))
        if not user or not mfa.verify(db, user, "reset", body.code or ""):
            db.commit()  # keep the attempt count
            raise HTTPException(status_code=400, detail="رمز الاستعادة غير صالح أو منتهي")
    problems = password_problems(body.new_password, identifiers=(user.email, user.phone))
    if problems:
        raise HTTPException(status_code=400, detail="؛ ".join(problems))
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.failed_logins, user.locked_until = 0, None
    if rt:
        rt.used_at = utcnow()
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit.record(db, "auth.password_reset", actor=user, ip=client_ip(request))
    db.commit()
    return {"ok": True}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=200)


@router.post("/auth/password/change")
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="كلمة المرور الحالية غير صحيحة")
    problems = password_problems(body.new_password, identifiers=(user.email, user.phone))
    if problems:
        raise HTTPException(status_code=400, detail="؛ ".join(problems))
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit.record(db, "auth.password_changed", actor=user, ip=client_ip(request))
    # every other session was signed out above; this device gets a fresh one
    out = _issue_session(db, user, request, response)
    db.commit()
    return {"ok": True, **out}


@router.post("/auth/handoff/start")
def handoff_start(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One-time link (60 s) that opens the web dashboard already signed in, e.g. from the mobile app."""
    if getattr(user, "acting_platform_admin", False):
        raise HTTPException(status_code=400, detail="غير متاح أثناء إدارة جامعة")
    if not limiter.hit(f"handoff:{user.id}", 10, 300):
        raise HTTPException(status_code=429, detail="محاولات كثيرة")
    code = mfa.new_handoff(db, user)
    audit.record(db, "auth.handoff_started", actor=user, ip=client_ip(request))
    db.commit()
    return {"path": f"/#/handoff/{code}", "expires_in": 60}


class HandoffIn(BaseModel):
    code: str = Field(min_length=10, max_length=200)


@router.post("/auth/handoff")
def handoff(body: HandoffIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request) or "?"
    if not limiter.hit(f"handoff-ip:{ip}", 20, 300):
        raise HTTPException(status_code=429, detail="محاولات كثيرة")
    user = mfa.redeem_handoff(db, body.code)
    if not user or not user.is_active:
        db.commit()
        raise HTTPException(status_code=401, detail="الرابط منتهي أو مستخدم، افتحه من التطبيق مرة أخرى")
    out = _issue_session(db, user, request, response)
    audit.record(db, "auth.login", actor=user, ip=ip, details={"via": "app_handoff"})
    db.commit()
    return out


# --------------------------------------------------------------------------- profile


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_profile(db, user)


class PrefsIn(BaseModel):
    push: bool = True
    sms: bool = True
    muted_categories: list[str] = Field(default_factory=list, max_length=10)


@router.put("/me/notification-prefs")
def set_prefs(body: PrefsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    allowed = {"announcement", "academic_note", "admin_notice"}  # warnings and system alerts can't be muted
    user.notification_prefs = {"push": body.push, "sms": body.sms,
                               "muted_categories": [c for c in body.muted_categories if c in allowed]}
    db.commit()
    return user.notification_prefs


class DeviceIn(BaseModel):
    platform: str = Field(pattern="^(android|ios|web)$")
    token: str = Field(min_length=10, max_length=500)


@router.post("/me/devices")
def register_device(body: DeviceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.scalar(select(DeviceToken).where(DeviceToken.token == body.token))
    if existing:
        existing.user_id, existing.platform = user.id, body.platform
    else:
        db.add(DeviceToken(user_id=user.id, platform=body.platform, token=body.token))
    db.commit()
    return {"ok": True}


class DeviceRemoveIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)


@router.post("/me/devices/remove")
def remove_device(body: DeviceRemoveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Called on logout so a shared phone stops receiving this user's notifications."""
    existing = db.scalar(select(DeviceToken).where(DeviceToken.token == body.token, DeviceToken.user_id == user.id))
    if existing:
        db.delete(existing)
        db.commit()
    return {"ok": True}


@router.get("/me/sessions")
def my_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
                                                AuthSession.expires_at > utcnow())
                      .order_by(AuthSession.created_at.desc())).all()
    return [{"id": s.id, "created_at": s.created_at, "user_agent": s.user_agent, "ip": s.ip} for s in rows]


@router.post("/me/sessions/revoke-all")
def revoke_all(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit.record(db, "auth.sessions_revoked", actor=user, ip=client_ip(request))
    db.commit()
    return {"ok": True}

