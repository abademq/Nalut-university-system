"""Regulations and rules: what the university and each faculty publish (text and an optional
official file), plus the rules the platform applies right now, read from the institution settings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, permissions
from ..db import get_db
from ..deps import client_ip, get_current_user, not_found, tenant_settings
from ..models import Faculty, Regulation, StoredFile, User

router = APIRouter(prefix="/api/regulations", tags=["regulations"])
KEY = "regulations.manage"
CATEGORIES = {"general": "عامة", "study": "الدراسة والتسجيل", "exams": "الامتحانات والدرجات",
              "attendance": "الحضور والغياب", "conduct": "السلوك والانضباط", "graduation": "التخرج"}
DAYS_NOTE = "تُطبَّق هذه القيم تلقائياً في المنصة، وتعدّلها الإدارة من إعدادات المؤسسة."


def applied_rules(cfg: dict) -> list[dict]:
    """The rules the platform enforces, in plain words, from the current settings."""
    att, gr, reg = cfg["attendance"], cfg["grading"], cfg.get("registration") or {}
    scale = "، ".join(f"{label} ({letter}) من {m}%" for m, letter, label in gr["scale"])
    out = [
        {"category": "attendance", "title": "الحضور والغياب", "items": [
            f"يُعدّ الطالب متأخراً إذا سجّل حضوره بعد {att['late_after_minutes']} دقيقة من بداية المحاضرة.",
            f"يصل الطالب تنبيه عند بلوغ غيابه {att['warning_absence_percent']}% من محاضرات المقرر.",
            f"الحد الأقصى للغياب {att['limit_absence_percent']}% من محاضرات المقرر؛ عند تجاوزه يُبلَّغ الطالب "
            "وأستاذ المقرر وإدارة الكلية، والقرار وفق اللوائح.",
            "عذر الغياب يُقدَّم من «الطلبات والمعاملات» مع ما يثبته."]},
        {"category": "exams", "title": "الدرجات والنتائج", "items": [
            f"درجة النجاح في المقرر {gr['pass_mark']}%.", f"التقديرات: {scale}.",
            "النتيجة الرسمية تظهر بعد رفعها من أستاذ المقرر واعتمادها ونشرها من إدارة الكلية.",
            "المعدل متوسط الدرجات موزوناً بوحدات المقررات."]},
    ]
    study = []
    if reg.get("enforce_prerequisites", True):
        study.append("لا يُسجَّل الطالب في مقرر قبل النجاح في متطلبه السابق.")
    if reg.get("block_passed_repeat", True):
        study.append("لا يُعاد تسجيل مقرر نجح فيه الطالب.")
    if reg.get("block_schedule_clash", True):
        study.append("لا يُسجَّل الطالب في مقررين يتعارض موعداهما في الفصل نفسه.")
    if reg.get("max_credits_per_term"):
        study.append(f"الحد الأعلى لوحدات الفصل {reg['max_credits_per_term']} وحدة"
                     + (f"، والحد الأدنى المستحسن {reg['min_credits_per_term']} وحدة." if reg.get("min_credits_per_term") else "."))
    study.append("الاستثناء من قواعد التسجيل بقرار من إدارة الكلية بسبب مكتوب.")
    out.append({"category": "study", "title": "التسجيل في المقررات", "items": study})
    return out


def _visible(user: User, r: Regulation) -> bool:
    return r.university_id == user.university_id and (r.faculty_id is None or r.faculty_id == user.faculty_id
                                                       or permissions.is_platform(user) or user.faculty_id is None)


def _out(db: Session, r: Regulation, names: dict) -> dict:
    f = db.get(StoredFile, r.file_id) if r.file_id else None
    return {"id": r.id, "title": r.title, "body": r.body, "category": r.category,
            "category_label": CATEGORIES.get(r.category, r.category), "faculty_id": r.faculty_id,
            "faculty": names.get(r.faculty_id), "file": files.file_info(f) if f else None,
            "position": r.position, "updated_at": r.updated_at}


@router.get("")
def list_regulations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.university_id is None:
        return {"applied": [], "items": [], "categories": CATEGORIES, "can_manage": False}
    rows = [r for r in db.scalars(select(Regulation).where(Regulation.university_id == user.university_id)
                                  .order_by(Regulation.position, Regulation.id)) if _visible(user, r)]
    names = {f.id: f.name for f in db.scalars(select(Faculty).where(Faculty.university_id == user.university_id))}
    return {"applied": applied_rules(tenant_settings(db, user)), "note": DAYS_NOTE,
            "items": [_out(db, r, names) for r in rows], "categories": CATEGORIES,
            "can_manage": permissions.allowed(db, user, KEY)}


async def _save(db: Session, user: User, r: Regulation, title: str, body: str, category: str,
                faculty_id: int | None, position: int, upload: UploadFile | None, remove_file: bool):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="تصنيف غير صحيح")
    if len(title.strip()) < 2 or (not body.strip() and not upload and not r.file_id):
        raise HTTPException(status_code=400, detail="اكتب العنوان والنص أو أرفق ملف اللائحة")
    sc = permissions.require_scope(db, user, KEY)
    if sc != permissions.ALL:
        faculty_id = sc  # a faculty publishes its own regulations
    elif faculty_id:
        fac = db.get(Faculty, faculty_id)
        if not fac or fac.university_id != user.university_id:
            raise HTTPException(status_code=400, detail="الكلية غير صحيحة")
    r.title, r.body, r.category, r.faculty_id, r.position = title.strip(), body.strip(), category, faculty_id or None, position
    if remove_file:
        r.file_id = None
    if upload is not None and (upload.filename or upload.size):
        cfg = tenant_settings(db, user)
        data = await files.read_upload(upload, 20)
        f = files.store(db, owner=user, purpose="regulation", filename=upload.filename or "regulation.pdf", data=data,
                        allowed_extensions=["pdf", "doc", "docx"] if "pdf" in cfg["uploads"]["allowed_extensions"]
                        else cfg["uploads"]["allowed_extensions"])
        r.file_id = f.id


@router.post("")
async def create_regulation(request: Request, title: str = Form(..., max_length=200), body: str = Form("", max_length=50000),
                            category: str = Form("general"), faculty_id: int | None = Form(None), position: int = Form(0),
                            upload: UploadFile | None = File(None), user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    r = Regulation(university_id=user.university_id, created_by=user.id)
    await _save(db, user, r, title, body, category, faculty_id, position, upload, False)
    db.add(r)
    db.flush()
    audit.record(db, "regulation.published", actor=user, target_type="regulation", target_id=r.id,
                 details={"title": r.title}, ip=client_ip(request))
    db.commit()
    return {"id": r.id}


def _own(db: Session, user: User, rid: int) -> Regulation:
    r = db.get(Regulation, rid)
    if not r or r.university_id != user.university_id:
        raise not_found()
    sc = permissions.require_scope(db, user, KEY)
    if sc != permissions.ALL and r.faculty_id != sc:
        raise not_found()
    return r


@router.post("/{rid}")
async def update_regulation(rid: int, request: Request, title: str = Form(..., max_length=200),
                            body: str = Form("", max_length=50000), category: str = Form("general"),
                            faculty_id: int | None = Form(None), position: int = Form(0), remove_file: bool = Form(False),
                            upload: UploadFile | None = File(None), user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    r = _own(db, user, rid)
    await _save(db, user, r, title, body, category, faculty_id, position, upload, remove_file)
    audit.record(db, "regulation.updated", actor=user, target_type="regulation", target_id=r.id,
                 details={"title": r.title}, ip=client_ip(request))
    db.commit()
    return {"id": r.id}


@router.delete("/{rid}")
def delete_regulation(rid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _own(db, user, rid)
    audit.record(db, "regulation.deleted", actor=user, target_type="regulation", target_id=r.id,
                 details={"title": r.title}, ip=client_ip(request))
    db.delete(r)
    db.commit()
    return {"ok": True}


def knowledge(db: Session, user: User, limit: int = 12000) -> str:
    """The published regulations as text, for the AI assistant."""
    out, size = [], 0
    for r in db.scalars(select(Regulation).where(Regulation.university_id == user.university_id)
                        .order_by(Regulation.position, Regulation.id)):
        if not _visible(user, r) or not r.body:
            continue
        part = f"## {r.title}\n{r.body}\n"
        if size + len(part) > limit:
            break
        out.append(part)
        size += len(part)
    return "\n".join(out)
