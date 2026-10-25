from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Timezone-aware current UTC time. All application datetimes are aware UTC."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Treat naive input as UTC and normalise aware input to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stored as naive UTC (portable across SQLite/PostgreSQL), returned as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return as_utc(value).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def make_engine(url: str):
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        path = url.replace("sqlite:///", "")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure(url: str) -> None:
    """Re-point the global engine (used by tests and CLI)."""
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind=engine)
    _adopt_university_colors()


# Colors of earlier identities (the green one, then a maroon-first one), replaced by Nalut University's
# (gold first, maroon second) wherever a university still has them stored from the demo data or from
# those versions; colors chosen by a university are kept.
_OLD_BRANDING = {("branding", "primary_color"): {"#0f5c4d", "#6e1a10"},
                 ("branding", "accent_color"): {"#c8a24a", "#c49a2c"},
                 ("launch", "background"): {"#0b3b32"}, ("launch", "accent"): {"#c8a24a", "#c49a2c"}}
_NEW_BRANDING = {("branding", "primary_color"): "#d6aa21", ("branding", "accent_color"): "#6e1a10",
                 ("launch", "background"): "#45110A", ("launch", "accent"): "#D6AA21"}


def _adopt_university_colors() -> None:
    from sqlalchemy import select

    from .models import University

    with SessionLocal() as db:
        changed = False
        for uni in db.scalars(select(University)):
            settings_ = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (uni.settings or {}).items()}
            touched = False
            for (section, key), old in _OLD_BRANDING.items():
                part = settings_.get(section)
                if isinstance(part, dict) and str(part.get(key, "")).lower() in old:
                    part[key] = _NEW_BRANDING[(section, key)]
                    touched = True
            if touched:
                uni.settings = settings_
                changed = True
        if changed:
            db.commit()
