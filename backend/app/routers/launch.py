"""The mobile app's launch screen and start-up sound.

Public, because the app shows the screen before anyone signs in: it keeps the last answer and
refreshes it in the background. Only the platform administrator (acting as a university) can
change it: settings key "launch" through PUT /api/settings, and the picture here.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, notifications
from ..config import settings
from ..db import get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found
from ..models import AppAsset, University, User
from ..tenancy import effective_settings

router = APIRouter(prefix="/api/app", tags=["app"])


def _university(db: Session, u: int | None) -> University:
    """The requested university, or the first one when the app has never signed in."""
    from ..deps import main_university

    uni = main_university(db) if settings.single_university or not u else db.get(University, u)
    if not uni:
        raise not_found()
    return uni


def _image(db: Session, university_id: int) -> AppAsset | None:
    return db.scalars(select(AppAsset).where(AppAsset.university_id == university_id,
                                             AppAsset.kind == "splash")).first()


@router.get("/launch")
def launch(u: int | None = None, db: Session = Depends(get_db)):
    uni = _university(db, u)
    cfg = dict(effective_settings(uni)["launch"])
    cfg["subtitle"] = cfg["subtitle"] or uni.name
    img = _image(db, uni.id)
    return {"university_id": uni.id, "launch": cfg, "image_version": img.version if img else None}


@router.get("/launch/image")
def launch_image(u: int | None = None, db: Session = Depends(get_db)):
    img = _image(db, _university(db, u).id)
    if not img:
        raise not_found()
    return Response(img.data, media_type=img.content_type, headers={
        "Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff", "ETag": f'"{img.version}"'})


@router.get("/sounds")
def sounds(user: User = Depends(get_current_user)):
    """Sounds the app can play when it opens: dedicated launch sounds, then the notification tones."""
    return {"launch": [{"name": k, "label": v} for k, v in notifications.LAUNCH_SOUNDS.items()],
            "tones": [{"name": k, "label": v} for k, v in notifications.TONES.items()]}


def _platform_admin(user: User = Depends(get_current_user)) -> User:
    if not getattr(user, "acting_platform_admin", False):
        raise forbidden("شاشة البداية يحددها مشرف المنصة فقط")
    return user


@router.post("/launch/image")
async def set_image(request: Request, upload: UploadFile = File(...), user: User = Depends(_platform_admin),
                    db: Session = Depends(get_db)):
    data = await files.read_upload(upload, 2)
    ext = files.extension_of(files.safe_filename(upload.filename or "image"))
    if ext not in ("png", "jpg", "jpeg"):
        raise HTTPException(status_code=400, detail="الصورة يجب أن تكون PNG أو JPG")
    try:
        files.inspect(data, ext)
    except files.FileRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    img = _image(db, user.university_id) or AppAsset(university_id=user.university_id, kind="splash")
    img.content_type = "image/png" if ext == "png" else "image/jpeg"
    img.data = data
    img.version = hashlib.sha256(data).hexdigest()[:16]
    img.updated_by = user.id
    img.updated_at = utcnow()
    db.add(img)
    audit.record(db, "launch.image_set", actor=user, target_type="university", target_id=user.university_id,
                 details={"bytes": len(data)}, ip=client_ip(request))
    db.commit()
    return {"image_version": img.version}


@router.delete("/launch/image")
def delete_image(request: Request, user: User = Depends(_platform_admin), db: Session = Depends(get_db)):
    img = _image(db, user.university_id)
    if img:
        db.delete(img)
        audit.record(db, "launch.image_removed", actor=user, target_type="university",
                     target_id=user.university_id, ip=client_ip(request))
        db.commit()
    return {"image_version": None}
