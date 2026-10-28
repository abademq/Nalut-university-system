"""Pinned announcements shown at the top of the app and dashboard for a time window."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, permissions
from ..db import as_utc, get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found, require_roles
from ..models import Banner, Faculty, Role, User

router = APIRouter(prefix="/api/banners", tags=["banners"])

MANAGERS = (Role.PLATFORM_ADMIN, Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.STAFF, Role.TEACHER, Role.ASSISTANT)


def _manager(user: User = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)) -> User:
    if not permissions.allowed(db, user, "banners.manage"):
        raise forbidden("نشر الإعلانات المثبتة غير مفعل لحسابك في هذه الجامعة")
    return user


def _faculty_scoped(user: User) -> bool:
    """Faculty administrators, and staff attached to a faculty, manage their faculty's banners only."""
    return user.role != Role.UNIVERSITY_ADMIN and user.faculty_id is not None


def _out(b: Banner, faculty_name: str | None = None) -> dict:
    return {"id": b.id, "title": b.title, "body": b.body, "link": b.link, "level": b.level, "audience": b.audience,
            "faculty_id": b.faculty_id, "faculty_name": faculty_name, "starts_at": b.starts_at, "ends_at": b.ends_at,
            "is_active": b.is_active, "created_at": b.created_at}


@router.get("")
def current(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Banners visible to the caller right now."""
    if user.university_id is None:
        return []
    now = utcnow()
    audiences = ["all", "students" if user.role == Role.STUDENT else "staff"]
    stmt = select(Banner).where(
        Banner.university_id == user.university_id, Banner.is_active.is_(True), Banner.starts_at <= now,
        or_(Banner.ends_at.is_(None), Banner.ends_at > now), Banner.audience.in_(audiences),
        or_(Banner.faculty_id.is_(None), Banner.faculty_id == user.faculty_id))
    rank = {"urgent": 0, "important": 1, "info": 2}
    rows = sorted(db.scalars(stmt), key=lambda b: (rank.get(b.level, 3), -b.id))
    return [_out(b) for b in rows]


def _scoped(db: Session, user: User, bid: int) -> Banner:
    b = db.get(Banner, bid)
    if not b or b.university_id != user.university_id:
        raise not_found()
    if _faculty_scoped(user) and b.faculty_id != user.faculty_id:
        raise forbidden()
    return b


@router.get("/manage")
def manage(user: User = Depends(_manager), db: Session = Depends(get_db)):
    stmt = select(Banner).where(Banner.university_id == user.university_id)
    if _faculty_scoped(user):
        stmt = stmt.where(Banner.faculty_id == user.faculty_id)
    names = {f.id: f.name for f in db.scalars(select(Faculty).where(Faculty.university_id == user.university_id))}
    return [_out(b, names.get(b.faculty_id)) for b in db.scalars(stmt.order_by(Banner.id.desc()).limit(200))]


class BannerIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(default="", max_length=2000)
    link: str | None = Field(default=None, max_length=300)
    level: str = Field(default="info", pattern="^(info|important|urgent)$")
    audience: str = Field(default="all", pattern="^(all|students|staff)$")
    faculty_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True


def _validate(db: Session, user: User, data: dict) -> dict:
    if _faculty_scoped(user):
        data["faculty_id"] = user.faculty_id  # faculty administrations and faculty staff publish to their faculty
    elif data.get("faculty_id") is not None:
        fac = db.get(Faculty, data["faculty_id"])
        if not fac or fac.university_id != user.university_id:
            raise HTTPException(status_code=400, detail="الكلية غير صحيحة")
    for key in ("starts_at", "ends_at"):
        if key in data:
            data[key] = as_utc(data[key])
    if data.get("link") and not data["link"].startswith(("#/", "https://")):
        raise HTTPException(status_code=400, detail="الرابط يجب أن يبدأ بـ #/ أو https://")
    return data


@router.post("")
def create(body: BannerIn, request: Request, user: User = Depends(_manager),
           db: Session = Depends(get_db)):
    data = _validate(db, user, body.model_dump())
    data["starts_at"] = data.get("starts_at") or utcnow()
    if data.get("ends_at") and data["ends_at"] <= data["starts_at"]:
        raise HTTPException(status_code=400, detail="وقت الاختفاء يجب أن يكون بعد وقت الظهور")
    b = Banner(university_id=user.university_id, created_by=user.id, **data)
    db.add(b)
    db.flush()
    audit.record(db, "banner.created", actor=user, target_type="banner", target_id=b.id,
                 details={"title": b.title, "faculty_id": b.faculty_id}, ip=client_ip(request))
    db.commit()
    return _out(b)


class BannerPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=300)
    level: str | None = Field(default=None, pattern="^(info|important|urgent)$")
    audience: str | None = Field(default=None, pattern="^(all|students|staff)$")
    faculty_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None


@router.patch("/{bid}")
def patch(bid: int, body: BannerPatch, request: Request, user: User = Depends(_manager),
          db: Session = Depends(get_db)):
    b = _scoped(db, user, bid)
    data = _validate(db, user, body.model_dump(exclude_unset=True))
    for k, v in data.items():
        setattr(b, k, v)
    if b.ends_at and b.ends_at <= b.starts_at:
        raise HTTPException(status_code=400, detail="وقت الاختفاء يجب أن يكون بعد وقت الظهور")
    audit.record(db, "banner.updated", actor=user, target_type="banner", target_id=b.id,
                 details={"fields": sorted(data)}, ip=client_ip(request))
    db.commit()
    return _out(b)


@router.delete("/{bid}")
def delete(bid: int, request: Request, user: User = Depends(_manager), db: Session = Depends(get_db)):
    b = _scoped(db, user, bid)
    audit.record(db, "banner.deleted", actor=user, target_type="banner", target_id=b.id,
                 details={"title": b.title}, ip=client_ip(request))
    db.delete(b)
    db.commit()
    return {"ok": True}
