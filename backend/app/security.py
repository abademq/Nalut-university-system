"""Password hashing, tokens, TOTP (MFA), field encryption and rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import settings
from .db import utcnow

# --------------------------------------------------------------------------- passwords

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


# Computed once so that unknown accounts take as long as real ones (no user enumeration by timing).
DUMMY_HASH = hash_password(secrets.token_hex(8))

COMMON_PASSWORDS = {"password", "12345678", "123456789", "1234567890", "qwerty123", "password1", "11111111"}


def password_problems(password: str, *, identifiers: tuple[str | None, ...] = ()) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("كلمة المرور يجب ألا تقل عن 10 أحرف")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("كلمة المرور شائعة جداً")
    if not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        problems.append("كلمة المرور يجب أن تحتوي على حروف وأرقام")
    for ident in identifiers:
        if ident and ident.split("@")[0].lower() in password.lower():
            problems.append("كلمة المرور يجب ألا تحتوي على البريد أو رقم الهاتف")
            break
    return problems


# --------------------------------------------------------------------------- tokens


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: int, *, role: str, university_id: int | None, purpose: str = "access",
                        minutes: int | None = None) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "role": role,
        "uni": university_id,
        "typ": purpose,
        "iat": int(time.time()),
        "exp": now + timedelta(minutes=minutes or settings.access_token_minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str, *, purpose: str = "access") -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != purpose:
        return None
    return payload


# --------------------------------------------------------------------------- TOTP (RFC 6238)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(padded.upper())
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret_b32: str, at: float | None = None) -> str:
    return _hotp(secret_b32, int((at or time.time()) // 30))


def verify_totp(secret_b32: str, code: str, *, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    counter = int(time.time() // 30)
    return any(hmac.compare_digest(_hotp(secret_b32, counter + d), code) for d in range(-window, window + 1))


def totp_uri(secret_b32: str, account: str, issuer: str) -> str:
    from urllib.parse import quote

    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}"


# --------------------------------------------------------------------------- field encryption


def _fernet() -> Fernet:
    return Fernet(settings.fernet_key())


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _fernet().decrypt(data)


def encrypt_str(value: str) -> str:
    return encrypt_bytes(value.encode()).decode()


def mask_id(value: str | None) -> str | None:
    """A national id as lists and files show it: only the last four digits."""
    if not value:
        return None
    return "•" * max(len(value) - 4, 2) + value[-4:]


def decrypt_str(value: str) -> str | None:
    try:
        return decrypt_bytes(value.encode()).decode()
    except InvalidToken:
        return None


# --------------------------------------------------------------------------- rate limiting


class RateLimiter:
    """In-process sliding-window limiter.

    Good enough for a single API instance; when running several instances put the
    counters in a shared store (e.g. Redis) behind the same interface.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, per_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > per_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
