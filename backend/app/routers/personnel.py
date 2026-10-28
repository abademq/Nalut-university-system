"""Staff and faculty members: employment files and document copies.

Two sections: "staff" (staff and faculty administrators) and "faculty" (teachers and assistants).
Access: the university administration always; others need the section's capability
(staff.view / staff.manage, faculty.view / faculty.manage) from their role or a permission group,
and stay within their faculty when they belong to one. Everyone can read their own file.
Every view, download, change and deletion is written to the audit log (field names only).
"""
from __future__ import annotations

from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, files, permissions
from ..db import get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found, tenant_settings
from ..models import (
    Course,
    CourseStaff,
    Department,
    Faculty,
    PersonnelDocument,
    PersonnelRecord,
    Role,
    StoredFile,
    Term,
    User,
)
from ..security import decrypt_str, encrypt_str, mask_id

router = APIRouter(prefix="/api/personnel", tags=["personnel"])

SECTIONS = {"staff": (Role.STAFF, Role.FACULTY_ADMIN), "faculty": (Role.TEACHER, Role.ASSISTANT)}

CHOICES = {
    "gender": {"male": "ذكر", "female": "أنثى"},
    "marital_status": {"single": "أعزب", "married": "متزوج", "other": "أخرى"},
    "employment_type": {"permanent": "قار (دائم)", "contract": "متعاقد", "cooperating": "متعاون",
                        "secondment": "منتدب", "part_time": "دوام جزئي"},
    "status": {"active": "على رأس العمل", "leave": "في إجازة", "study_leave": "إيفاد / إجازة دراسية",
               "secondment": "منتدب لجهة أخرى", "suspended": "موقوف", "retired": "متقاعد", "left": "انتهت الخدمة"},
    "qualification": {"secondary": "ثانوية", "diploma": "دبلوم", "bachelor": "بكالوريوس", "higher_diploma": "دبلوم عالٍ",
                      "master": "ماجستير", "phd": "دكتوراه"},
    "academic_rank": {"assistant_lecturer": "معيد", "lecturer_assistant": "محاضر مساعد", "lecturer": "محاضر",
                      "assistant_professor": "أستاذ مساعد", "associate_professor": "أستاذ مشارك", "professor": "أستاذ"},
}

# (key, label, type) — type: text, date, number, textarea or a key of CHOICES
COMMON = [
    ("employee_number", "الرقم الوظيفي", "text"), ("birth_date", "تاريخ الميلاد", "date"),
    ("birth_place", "مكان الميلاد", "text"), ("gender", "الجنس", "gender"), ("nationality", "الجنسية", "text"),
    ("marital_status", "الحالة الاجتماعية", "marital_status"), ("address", "العنوان", "text"),
    ("emergency_contact", "شخص للطوارئ", "text"), ("emergency_phone", "هاتف الطوارئ", "text"),
    ("hire_date", "تاريخ التعيين / المباشرة", "date"), ("employment_type", "نوع التعاقد", "employment_type"),
    ("status", "الحالة الوظيفية", "status"), ("qualification", "المؤهل العلمي", "qualification"),
    ("qualification_field", "تخصص المؤهل", "text"), ("qualification_institution", "جهة المؤهل", "text"),
    ("qualification_year", "سنة الحصول على المؤهل", "text"),
]
EXTRA = {
    "staff": [("job_title", "المسمى الوظيفي", "text"), ("unit", "الإدارة / المكتب", "text"),
              ("job_grade", "الدرجة الوظيفية", "text"), ("work_location", "مكان العمل", "text")],
    "faculty": [("academic_rank", "الدرجة العلمية", "academic_rank"),
                ("general_specialization", "التخصص العام", "text"),
                ("specific_specialization", "التخصص الدقيق", "text"),
                ("last_promotion_date", "تاريخ آخر ترقية", "date"),
                ("teaching_load_hours", "النصاب التدريسي (ساعة/أسبوع)", "number"),
                ("office_hours", "الساعات المكتبية", "text"),
                ("research_interests", "الاهتمامات البحثية", "textarea"),
                ("publications_count", "عدد البحوث المنشورة", "number")],
}
NOTES = ("notes", "ملاحظات", "textarea")

DOC_TYPES = {
    "cv": "السيرة الذاتية", "degree": "شهادة المؤهل العلمي", "appointment": "قرار التعيين",
    "contract": "عقد العمل", "national_id": "البطاقة الشخصية / الرقم الوطني", "passport": "جواز السفر",
    "photo": "صورة شخصية", "promotion": "قرار ترقية", "research": "بحوث ومنشورات", "evaluation": "تقييم الأداء",
    "leave": "إجازات وانتدابات", "training": "دورات وشهادات خبرة", "medical": "تقرير طبي", "other": "مستند آخر",
}


def fields(section: str) -> list[tuple[str, str, str]]:
    return COMMON + EXTRA[section] + [NOTES]


def section_of(user: User) -> str | None:
    return next((s for s, roles in SECTIONS.items() if user.role in roles), None)


def can(db: Session, user: User, section: str, *, manage: bool = False, target: User | None = None) -> bool:
    ok = permissions.allowed(db, user, f"{section}.manage") or (
        not manage and permissions.allowed(db, user, f"{section}.view"))
    if not ok or target is None:
        return ok
    if target.university_id != user.university_id or section_of(target) != section:
        return False
    return user.role == Role.UNIVERSITY_ADMIN or user.faculty_id is None or target.faculty_id == user.faculty_id


def _person(db: Session, user: User, uid: int, *, manage: bool = False) -> tuple[User, str]:
    target = db.get(User, uid)
    section = section_of(target) if target else None
    if not target or not section or not can(db, user, section, manage=manage, target=target):
        raise not_found("الملف غير موجود")
    return target, section


def _record_out(rec: PersonnelRecord | None, section: str) -> dict:
    data = dict(rec.data or {}) if rec else {}
    out = {k: data.get(k) for k, _, _ in fields(section)}
    # shown masked: the full number is asked for separately, and each such request is audited
    out["national_id"] = mask_id(decrypt_str(rec.national_id_enc)) if rec and rec.national_id_enc else None
    out["status"] = out.get("status") or "active"
    out["updated_at"] = rec.updated_at if rec else None
    return out


def _doc_out(d: PersonnelDocument, f: StoredFile, uploader: str | None) -> dict:
    return {"id": d.id, "doc_type": d.doc_type, "type_label": DOC_TYPES.get(d.doc_type, d.doc_type), "title": d.title,
            "notes": d.notes, "file": files.file_info(f), "uploaded_by": uploader, "created_at": d.created_at}


@router.get("/meta")
def meta(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sections = {s: {"view": can(db, user, s), "manage": can(db, user, s, manage=True),
                    "fields": [{"key": k, "label": label, "type": t} for k, label, t in fields(s)]}
                for s in SECTIONS}
    return {"sections": sections, "choices": CHOICES, "doc_types": DOC_TYPES,
            "max_file_mb": tenant_settings(db, user)["archive"]["max_file_mb"]}


@router.get("")
def list_people(section: str = Query(pattern="^(staff|faculty)$"), q: str | None = Query(default=None, max_length=100),
                faculty_id: int | None = None, status: str | None = None, limit: int = Query(default=100, le=500),
                offset: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not can(db, user, section):
        raise forbidden()
    stmt = select(User).where(User.university_id == user.university_id, User.role.in_(SECTIONS[section]))
    if user.role != Role.UNIVERSITY_ADMIN and user.faculty_id is not None:
        stmt = stmt.where(User.faculty_id == user.faculty_id)
    if faculty_id:
        stmt = stmt.where(User.faculty_id == faculty_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.code.ilike(like), User.email.ilike(like),
                              User.phone.ilike(like)))
    people = db.scalars(stmt.order_by(User.full_name)).all()
    ids = [p.id for p in people] or [-1]
    records = {r.user_id: r for r in db.scalars(select(PersonnelRecord).where(PersonnelRecord.user_id.in_(ids)))}
    if status:
        people = [p for p in people if ((records.get(p.id).data or {}).get("status") if p.id in records else None)
                  in ((status,) if status != "active" else ("active", None))]
    total = len(people)
    people = people[offset:offset + limit]
    counts = dict(db.execute(select(PersonnelDocument.user_id, func.count()).where(
        PersonnelDocument.user_id.in_(ids), PersonnelDocument.deleted_at.is_(None)).group_by(PersonnelDocument.user_id)).all())
    facs = {f.id: f.name for f in db.scalars(select(Faculty).where(Faculty.university_id == user.university_id))}
    out = []
    for p in people:
        data = (records[p.id].data or {}) if p.id in records else {}
        title = (CHOICES["academic_rank"].get(data.get("academic_rank")) if section == "faculty"
                 else data.get("job_title"))
        out.append({"id": p.id, "full_name": p.full_name, "role": p.role, "code": p.code, "email": p.email,
                    "phone": p.phone, "faculty": facs.get(p.faculty_id), "title": title,
                    "status": data.get("status") or "active", "documents": counts.get(p.id, 0),
                    "has_record": p.id in records, "is_active": p.is_active})
    return {"total": total, "items": out}


def _teaching(db: Session, person: User) -> list[dict]:
    rows = db.execute(select(Course, CourseStaff.role, Term.name, Term.is_current).join(
        CourseStaff, CourseStaff.course_id == Course.id).outerjoin(Term, Term.id == Course.term_id).where(
        CourseStaff.user_id == person.id).order_by(Term.is_current.desc(), Course.code)).all()
    return [{"id": c.id, "code": c.code, "title": c.title, "credits": c.credits, "role": role, "term": term,
             "current": bool(current)} for c, role, term, current in rows]


def _file(db: Session, viewer: User, person: User, section: str) -> dict:
    rec = db.scalar(select(PersonnelRecord).where(PersonnelRecord.user_id == person.id))
    docs = db.execute(select(PersonnelDocument, StoredFile).join(StoredFile, StoredFile.id == PersonnelDocument.file_id)
                      .where(PersonnelDocument.user_id == person.id, PersonnelDocument.deleted_at.is_(None))
                      .order_by(PersonnelDocument.id.desc())).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({d.uploaded_by for d, _ in docs} | ({rec.updated_by} if rec and rec.updated_by else set()) or {-1})))}
    fac = db.get(Faculty, person.faculty_id) if person.faculty_id else None
    dep = db.get(Department, person.department_id) if person.department_id else None
    return {
        "section": section,
        "person": {"id": person.id, "full_name": person.full_name, "role": person.role, "code": person.code,
                   "email": person.email, "phone": person.phone, "office": person.office,
                   "faculty": fac.name if fac else None, "department": dep.name if dep else None,
                   "is_active": person.is_active, "last_login_at": person.last_login_at},
        "record": _record_out(rec, section) | {"updated_by": names.get(rec.updated_by) if rec else None},
        "documents": [_doc_out(d, f, names.get(d.uploaded_by)) for d, f in docs],
        "teaching": _teaching(db, person) if section == "faculty" else [],
        "can_manage": viewer.id != person.id and can(db, viewer, section, manage=True, target=person),
    }


@router.get("/me")
def my_file(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    section = section_of(user)
    if not section:
        raise not_found("لا يوجد ملف وظيفي لهذا الحساب")
    return _file(db, user, user, section)


@router.get("/{uid}")
def get_file(uid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    person, section = _person(db, user, uid)
    audit.record(db, "personnel.viewed", actor=user, target_type="user", target_id=person.id,
                 details={"section": section}, ip=client_ip(request))
    db.commit()
    return _file(db, user, person, section)


@router.get("/{uid}/national-id")
def reveal_national_id(uid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if uid == user.id and section_of(user):
        person = user  # one's own number
    else:
        person, _ = _person(db, user, uid)
    rec = db.scalar(select(PersonnelRecord).where(PersonnelRecord.user_id == person.id))
    audit.record(db, "personnel.national_id_viewed", actor=user, target_type="user", target_id=person.id,
                 ip=client_ip(request))
    db.commit()
    return {"national_id": decrypt_str(rec.national_id_enc) if rec and rec.national_id_enc else None}


class RecordIn(BaseModel):
    national_id: str | None = Field(default=None, max_length=30)
    data: dict = Field(default_factory=dict)


def _clean(section: str, data: dict) -> dict:
    spec = {k: t for k, _, t in fields(section)}
    unknown = set(data) - set(spec)
    if unknown:
        raise HTTPException(status_code=400, detail=f"حقول غير معروفة: {', '.join(sorted(unknown))}")
    out = {}
    for k, v in data.items():
        t = spec[k]
        if v in (None, ""):
            out[k] = None
        elif t == "date":
            try:
                out[k] = date.fromisoformat(str(v)).isoformat()
            except ValueError:
                raise HTTPException(status_code=400, detail=f"تاريخ غير صحيح: {k}") from None
        elif t == "number":
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"رقم غير صحيح: {k}") from None
            if not 0 <= out[k] <= 10000:
                raise HTTPException(status_code=400, detail=f"رقم غير صحيح: {k}")
        elif t in CHOICES:
            if v not in CHOICES[t]:
                raise HTTPException(status_code=400, detail=f"قيمة غير صحيحة: {k}")
            out[k] = v
        else:
            out[k] = str(v).strip()[: 5000 if t == "textarea" else 300] or None
    return out


@router.put("/{uid}/record")
def save_record(uid: int, body: RecordIn, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    person, section = _person(db, user, uid, manage=True)
    if person.id == user.id and user.role != Role.UNIVERSITY_ADMIN:
        raise forbidden("لا يعدّل الشخص ملفه الوظيفي بنفسه")
    rec = db.scalar(select(PersonnelRecord).where(PersonnelRecord.user_id == person.id))
    if rec is None:
        rec = PersonnelRecord(university_id=person.university_id, user_id=person.id, data={})
        db.add(rec)
    data = _clean(section, body.data)
    old = dict(rec.data or {})
    changed = sorted(k for k, v in data.items() if old.get(k) != v)
    rec.data = {**old, **data}
    if "national_id" in body.model_fields_set and "•" not in (body.national_id or ""):  # a masked copy: unchanged
        nid = (body.national_id or "").strip()
        if nid != (decrypt_str(rec.national_id_enc) if rec.national_id_enc else ""):
            rec.national_id_enc = encrypt_str(nid) if nid else None
            changed.append("national_id")
    rec.updated_by, rec.updated_at = user.id, utcnow()
    audit.record(db, "personnel.record_updated", actor=user, target_type="user", target_id=person.id,
                 details={"section": section, "fields": changed}, ip=client_ip(request))
    db.commit()
    return _record_out(rec, section)


@router.post("/{uid}/documents")
async def upload_document(uid: int, request: Request, doc_type: str = Form(...),
                          title: str = Form("", max_length=200), notes: str = Form("", max_length=500),
                          upload: UploadFile = File(...), user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    person, section = _person(db, user, uid, manage=True)
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="نوع المستند غير صحيح")
    data = await files.read_upload(upload, int(tenant_settings(db, user)["archive"]["max_file_mb"]))
    f = files.store(db, owner=user, purpose="personnel", filename=upload.filename or "document", data=data,
                    allowed_extensions=["pdf", "jpg", "jpeg", "png", "docx"], encrypt=True)
    d = PersonnelDocument(university_id=person.university_id, user_id=person.id, doc_type=doc_type,
                          title=title.strip() or DOC_TYPES[doc_type], notes=notes.strip() or None, file_id=f.id,
                          uploaded_by=user.id)
    db.add(d)
    db.flush()
    audit.record(db, "personnel.document_added", actor=user, target_type="user", target_id=person.id,
                 details={"section": section, "document_id": d.id, "doc_type": doc_type, "sha256": f.sha256},
                 ip=client_ip(request))
    db.commit()
    return _doc_out(d, f, user.full_name)


def _document(db: Session, user: User, did: int, *, manage: bool = False) -> PersonnelDocument:
    d = db.get(PersonnelDocument, did)
    if not d or d.deleted_at is not None or d.university_id != user.university_id:
        raise not_found("المستند غير موجود")
    if d.user_id != user.id or manage:  # one's own documents can always be read
        _person(db, user, d.user_id, manage=manage)
    return d


@router.get("/documents/{did}/file")
def download_document(did: int, request: Request, inline: bool = False, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    d = _document(db, user, did)
    audit.record(db, "personnel.document_downloaded", actor=user, target_type="user", target_id=d.user_id,
                 details={"document_id": d.id}, ip=client_ip(request))
    db.commit()
    return files.download_response(db.get(StoredFile, d.file_id), inline=inline)


class DeleteIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/documents/{did}/delete")
def delete_document(did: int, body: DeleteIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Soft delete: hidden from the file but kept, with the reason."""
    d = _document(db, user, did, manage=True)
    d.deleted_at, d.deleted_by, d.delete_reason = utcnow(), user.id, body.reason.strip()
    audit.record(db, "personnel.document_deleted", actor=user, target_type="user", target_id=d.user_id,
                 details={"document_id": d.id, "reason": d.delete_reason}, ip=client_ip(request))
    db.commit()
    return {"ok": True}
