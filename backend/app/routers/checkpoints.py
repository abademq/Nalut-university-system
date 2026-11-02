"""Fixed QR checkpoints for staff: printed at an entrance, scanned on arrival and on leaving.

No screen and no electricity are needed at the entrance; the employee's phone does the work and
the location shows the scan was made there (a photo of the poster sent elsewhere is outside it)."""
from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta, timezone
from html import escape

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import attendance as svc
from .. import audit, permissions
from ..db import get_db
from ..deps import client_ip, get_current_user, not_found
from ..models import AttendanceRecord, Faculty, StaffCheckpoint, StaffScan, User

router = APIRouter(prefix="/api/attendance/checkpoints", tags=["attendance"])


def _out(db: Session, cp: StaffCheckpoint) -> dict:
    fac = db.get(Faculty, cp.faculty_id) if cp.faculty_id else None
    return {"id": cp.id, "name": cp.name, "faculty_id": cp.faculty_id, "faculty": fac.name if fac else None,
            "latitude": cp.latitude, "longitude": cp.longitude, "radius_m": cp.radius_m,
            "require_selfie": cp.require_selfie, "active": cp.active, "created_at": cp.created_at}


def _get(db: Session, user: User, cid: int) -> StaffCheckpoint:
    cp = db.get(StaffCheckpoint, cid)
    if not cp or cp.university_id != user.university_id:
        raise not_found("نقطة الدوام غير موجودة")
    sc = permissions.require_scope(db, user, "attendance.staff")
    if sc != permissions.ALL and cp.faculty_id != sc:
        raise HTTPException(status_code=403, detail="هذه النقطة خارج نطاق كليتك")
    return cp


class CheckpointIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    faculty_id: int | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=150, ge=20, le=5000)
    require_selfie: bool = False
    active: bool = True


@router.get("")
def list_checkpoints(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sc = permissions.require_scope(db, user, "attendance.staff")
    q = select(StaffCheckpoint).where(StaffCheckpoint.university_id == user.university_id)
    if sc != permissions.ALL:
        q = q.where(StaffCheckpoint.faculty_id == sc)
    return [_out(db, c) for c in db.scalars(q.order_by(StaffCheckpoint.id))]


@router.post("")
def create(body: CheckpointIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sc = permissions.require_scope(db, user, "attendance.staff")
    faculty_id = body.faculty_id if sc == permissions.ALL else sc
    if faculty_id is not None:
        fac = db.get(Faculty, faculty_id)
        if not fac or fac.university_id != user.university_id:
            raise not_found("الكلية غير موجودة")
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(status_code=400, detail="أدخل خط العرض والطول معاً")
    cp = StaffCheckpoint(university_id=user.university_id, faculty_id=faculty_id, name=body.name.strip(),
                         secret=svc.new_secret(), latitude=body.latitude, longitude=body.longitude,
                         radius_m=body.radius_m, require_selfie=body.require_selfie, active=body.active,
                         created_by=user.id)
    db.add(cp)
    db.flush()
    audit.record(db, "attendance.checkpoint_created", actor=user, target_type="staff_checkpoint", target_id=cp.id,
                 details={"name": cp.name, "faculty_id": faculty_id}, ip=client_ip(request))
    db.commit()
    return _out(db, cp)


@router.put("/{cid}")
def update(cid: int, body: CheckpointIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    cp = _get(db, user, cid)
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(status_code=400, detail="أدخل خط العرض والطول معاً")
    cp.name, cp.latitude, cp.longitude = body.name.strip(), body.latitude, body.longitude
    cp.radius_m, cp.require_selfie, cp.active = body.radius_m, body.require_selfie, body.active
    audit.record(db, "attendance.checkpoint_updated", actor=user, target_type="staff_checkpoint", target_id=cp.id,
                 details={"name": cp.name, "active": cp.active}, ip=client_ip(request))
    db.commit()
    return _out(db, cp)


@router.post("/{cid}/rotate")
def rotate(cid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A new code: the printed poster stops working and a new one must be printed (a leaked photo)."""
    cp = _get(db, user, cid)
    cp.secret = svc.new_secret()
    audit.record(db, "attendance.checkpoint_rotated", actor=user, target_type="staff_checkpoint", target_id=cp.id,
                 details={"name": cp.name}, ip=client_ip(request))
    db.commit()
    return _out(db, cp)


def _qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=14, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


@router.get("/{cid}/qr")
def qr(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cp = _get(db, user, cid)
    return {"payload": svc.checkpoint_payload(cp), "image": _qr_svg(svc.checkpoint_payload(cp))}


@router.get("/{cid}/poster", response_class=HTMLResponse)
def poster(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A page to print and fix at the entrance."""
    from ..printlinks import PRINT_CSP

    return HTMLResponse(render_poster(db, _get(db, user, cid)), headers={"Content-Security-Policy": PRINT_CSP})


@router.post("/{cid}/link")
def poster_link(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..printlinks import make

    return {"url": make("poster", _get(db, user, cid).id)}


print_router = APIRouter(include_in_schema=False)


@print_router.get("/print/poster/{token}", response_class=HTMLResponse)
def poster_print(token: str, db: Session = Depends(get_db)):
    from ..printlinks import PRINT_CSP, check

    cid = check("poster", token)
    cp = db.get(StaffCheckpoint, cid) if cid else None
    if not cp:
        return HTMLResponse("<p dir='rtl'>انتهت صلاحية الرابط، افتحه من المنصة مرة أخرى.</p>", status_code=410,
                            headers={"Content-Security-Policy": PRINT_CSP})
    return HTMLResponse(render_poster(db, cp), headers={"Content-Security-Policy": PRINT_CSP})


def render_poster(db: Session, cp: StaffCheckpoint) -> str:
    from ..models import University
    from ..tenancy import effective_settings

    uni = db.get(University, cp.university_id)
    name = effective_settings(uni)["branding"].get("display_name") or uni.name
    fac = db.get(Faculty, cp.faculty_id) if cp.faculty_id else None
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{escape(cp.name)}</title>
<style>body{{font-family:system-ui,'Noto Sans Arabic',sans-serif;text-align:center;margin:2cm}}
img{{width:12cm;height:12cm}}h1{{margin:.2em 0;font-size:28pt}}h2{{margin:.2em 0;color:#444}}
p{{font-size:14pt;color:#333}}@media print{{button{{display:none}}}}</style></head><body>
<h2>{escape(name)}{" — " + escape(fac.name) if fac else ""}</h2><h1>تسجيل الدوام</h1><h2>{escape(cp.name)}</h2>
<img src="{_qr_svg(svc.checkpoint_payload(cp))}" alt="QR">
<p>امسح الرمز من تطبيق الجامعة عند الدخول وعند الخروج.<br>يُسجَّل الوقت والموقع تلقائياً.</p>
<p style="font-size:10pt;color:#888">للطباعة: قائمة المتصفح ← طباعة (Ctrl+P)</p></body></html>"""


@router.get("/{cid}/scans")
def scans(cid: int, day: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The day's movements at a checkpoint (local day, YYYY-MM-DD; today by default)."""
    from zoneinfo import ZoneInfo

    cp = _get(db, user, cid)
    tz = ZoneInfo(svc.LOCAL_TZ)
    try:
        d = datetime.strptime(day, "%Y-%m-%d") if day else datetime.now(tz).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="صيغة التاريخ YYYY-MM-DD") from exc
    start = d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz).astimezone(timezone.utc)
    rows = db.scalars(select(StaffScan).where(StaffScan.checkpoint_id == cp.id, StaffScan.at >= start,
                                              StaffScan.at < start + timedelta(days=1)).order_by(StaffScan.at)).all()
    people: dict[int, dict] = {}
    for s in rows:
        u = db.get(User, s.user_id)
        p = people.setdefault(s.user_id, {"user_id": s.user_id, "name": u.full_name if u else "—", "scans": [],
                                          "first_in": None, "last_out": None, "status": None, "flags": []})
        p["scans"].append({"kind": s.kind, "at": s.at})
        if s.kind == "in" and not p["first_in"]:
            p["first_in"] = s.at
        if s.kind == "out":
            p["last_out"] = s.at
        if s.record_id and p["status"] is None:
            rec = db.get(AttendanceRecord, s.record_id)
            p["status"], p["flags"] = (rec.status, rec.risk_flags) if rec else (None, [])
    return {"checkpoint": _out(db, cp), "day": d.strftime("%Y-%m-%d"), "people": list(people.values())}


me_router = APIRouter(prefix="/api/attendance", tags=["attendance"])


@me_router.get("/my-scans")
def my_scans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(StaffScan).where(StaffScan.user_id == user.id).order_by(StaffScan.at.desc()).limit(60))
    names = {}
    out = []
    for s in rows:
        if s.checkpoint_id not in names:
            cp = db.get(StaffCheckpoint, s.checkpoint_id)
            names[s.checkpoint_id] = cp.name if cp else "—"
        out.append({"kind": s.kind, "at": s.at, "checkpoint": names[s.checkpoint_id]})
    return out
