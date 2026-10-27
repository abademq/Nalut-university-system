"""Application settings, read from environment variables.

Secrets (JWT key, encryption key, SMS/push credentials) live only on the server.
They are never shipped to the mobile app or the web client.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_DEV_SECRET = "dev-only-insecure-secret-change-me"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'nus.db'}")
    )
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", _DEV_SECRET))
    # 32 url-safe base64 bytes (Fernet key). Derived from SECRET_KEY in development only.
    data_encryption_key: str | None = field(default_factory=lambda: _env("DATA_ENCRYPTION_KEY"))
    storage_dir: Path = field(
        default_factory=lambda: Path(_env("STORAGE_DIR", str(BASE_DIR / "data" / "files")))
    )
    web_dir: Path = field(
        default_factory=lambda: Path(_env("WEB_DIR", str(BASE_DIR.parent / "web")))
    )
    access_token_minutes: int = field(default_factory=lambda: int(_env("ACCESS_TOKEN_MINUTES", "15")))
    refresh_token_days: int = field(default_factory=lambda: int(_env("REFRESH_TOKEN_DAYS", "14")))
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", False))
    cors_origins: list[str] = field(
        default_factory=lambda: [o for o in (_env("CORS_ORIGINS", "") or "").split(",") if o]
    )
    max_login_failures: int = 5
    lockout_minutes: int = 15
    run_worker: bool = field(default_factory=lambda: _bool("RUN_WORKER", True))
    worker_interval_seconds: int = field(default_factory=lambda: int(_env("WORKER_INTERVAL", "30")))
    # Optional ClamAV daemon for scanning uploads (host:port).
    clamd_address: str | None = field(default_factory=lambda: _env("CLAMD_ADDRESS"))
    # Notification providers. "log" providers print to the server log (development).
    # "auto": Firebase Cloud Messaging when the service-account file exists, otherwise "log".
    push_provider: str = field(default_factory=lambda: _env("PUSH_PROVIDER", "auto"))
    # Firebase service-account key (secret, server only). Never commit it.
    fcm_credentials_file: str = field(
        default_factory=lambda: _env("FCM_CREDENTIALS_FILE", "/etc/nus/firebase.json")
    )
    # "http": post to a push gateway that holds the FCM/APNs credentials.
    push_gateway_url: str | None = field(default_factory=lambda: _env("PUSH_GATEWAY_URL"))
    push_gateway_key: str | None = field(default_factory=lambda: _env("PUSH_GATEWAY_KEY"))
    sms_provider: str = field(default_factory=lambda: _env("SMS_PROVIDER", "log"))
    sms_api_url: str | None = field(default_factory=lambda: _env("SMS_API_URL"))
    sms_api_key: str | None = field(default_factory=lambda: _env("SMS_API_KEY"))
    sms_sender: str = field(default_factory=lambda: _env("SMS_SENDER", "UNIV"))
    # SMS_PROVIDER=resala: Resala (resala.ly). The key itself is read from RESALA_API_KEY by app/resala.py.
    # Notifications go through an approved template. RESALA_TEMPLATE_VARS is how many variables it has:
    # 2: $1 = title, $2 = text; 1: $1 = "title: text"; 0: the template's fixed text only.
    resala_sms_template_id: str | None = field(default_factory=lambda: _env("RESALA_SMS_TEMPLATE_ID"))
    resala_template_vars: int = field(default_factory=lambda: int(_env("RESALA_TEMPLATE_VARS", "1") or 1))
    resala_sender: str | None = field(default_factory=lambda: _env("RESALA_SENDER"))
    resala_service_name: str = field(default_factory=lambda: _env("RESALA_SERVICE_NAME", "منصة الجامعة"))
    # test mode: Resala accepts the request without sending or charging
    resala_test: bool = field(default_factory=lambda: _env("RESALA_TEST", "false").lower() == "true")

    # One university per installation: the platform administrator works directly in it and accounts
    # of any other university cannot sign in. MAIN_UNIVERSITY is its code (default: the first one).
    single_university: bool = field(default_factory=lambda: _bool("SINGLE_UNIVERSITY", True))
    main_university: str | None = field(default_factory=lambda: _env("MAIN_UNIVERSITY"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def fernet_key(self) -> bytes:
        if self.data_encryption_key:
            return self.data_encryption_key.encode()
        digest = hashlib.sha256(("enc:" + self.secret_key).encode()).digest()
        return base64.urlsafe_b64encode(digest)

    def validate(self) -> None:
        if self.is_production:
            problems = []
            if self.secret_key == _DEV_SECRET or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set to a random value of 32+ characters")
            if not self.data_encryption_key:
                problems.append("DATA_ENCRYPTION_KEY must be set (Fernet key)")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true (HTTPS only)")
            if self.database_url.startswith("sqlite"):
                problems.append("Use PostgreSQL in production (DATABASE_URL)")
            if problems:
                raise RuntimeError("Insecure production configuration: " + "; ".join(problems))


settings = Settings()
