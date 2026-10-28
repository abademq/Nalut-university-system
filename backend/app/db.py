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
    _adopt_open_permissions()


# Colors of earlier identities (the green one, a maroon-first one, then bright gold with maroon), replaced
# by the current one (soft gold on charcoal) wherever a university still has them stored from the demo data or from
# those versions; colors chosen by a university are kept.
_OLD_BRANDING = {("branding", "primary_color"): {"#0f5c4d", "#6e1a10", "#d6aa21"},
                 ("branding", "accent_color"): {"#c8a24a", "#c49a2c", "#6e1a10"},
                 ("launch", "background"): {"#0b3b32", "#45110a"}, ("launch", "accent"): {"#c8a24a", "#c49a2c", "#d6aa21"}}
_NEW_BRANDING = {("branding", "primary_color"): "#c9a646", ("branding", "accent_color"): "#c9a646",
                 ("launch", "background"): "#2B2622", ("launch", "accent"): "#C9A646"}


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


def _adopt_open_permissions() -> None:
    """Permissions version 2: every capability is open to every role, the university administration
    included. Saved matrices gain the rights that used to be fixed (permissions.IMPLICIT_BEFORE), once."""
    from sqlalchemy import select

    from .models import University
    from .permissions import IMPLICIT_BEFORE

    with SessionLocal() as db:
        changed = False
        for uni in db.scalars(select(University)):
            st = dict(uni.settings or {})
            if st.get("_permissions_v", 1) >= 2:
                continue
            matrix = {k: list(v) for k, v in (st.get("permissions") or {}).items() if isinstance(v, list)}
            for key, roles in matrix.items():
                for r in IMPLICIT_BEFORE.get(key, []):
                    if r not in roles:
                        roles.append(r)
            if matrix:
                st["permissions"] = matrix
            st["_permissions_v"] = 2
            uni.settings = st
            changed = True
        if changed:
            db.commit()
