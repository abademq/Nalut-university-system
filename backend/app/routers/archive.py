"""Student archive: personal file and document copies.

Access: university administration, the student's faculty administration, and staff of
the offices configured in settings["archive"]["offices"] (default: registrar) within
their faculty. Every view, download, change and deletion is written to the audit log.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, files, permissions
from ..db import get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found, tenant_settings
from ..models import Department, Role, StoredFile, StudentDocument, StudentRecord, User
from ..security import decrypt_str, encrypt_str

router = APIRouter(prefix="/api/archive", tags=["archive"])

DOC_TYPES = {
    "national_id": "صورة البطاقة الشخصية / الرقم الوطني",
    "passport": "صورة جواز السفر",
    "birth_certificate": "شهادة الميلاد",
    "high_school": "شهادة الثانوية العامة",
    "photo": "صورة شخصية",
    "family_record": "كتيب العائلة",
    "medical": "تقرير طبي",
    "transfer": "مستندات انتقال / معادلة",
    "other": "مستند آخر",
}
STATUSES = {"active": "مستمر", "suspended": "موقوف قيده", "graduated": "متخرج", "withdrawn": "منسحب"}
RECORD_FIELDS = ["birth_date", "birth_place", "nationality", "gender", "address", "guardian_name",
                 "guardian_relation", "guardian_phone", "high_school", "high_school_year", "high_school_score",
                 "admission_date", "status", "notes"]


def can_manage(db: Session, user: User, student: User | None = None) -> bool:
    if user.role == Role.UNIVERSITY_ADMIN:
        ok = True
    elif user.role == Role.FACULTY_ADMIN:
        ok = permissions.allowed(db, user, "archive.access")
    elif user.role == Role.STAFF:
        ok = (permissions.allowed(db, user, "archive.access")
              and user.office in tenant_settings(db, user)["archive"]["offices"])
    else:
        ok = False
    if not ok or student is None:
        return ok
    if student.university_id != user.university_id or student.role != Role.STUDENT:
        return False
    if user.role == Role.UNIVERSITY_ADMIN:
        return True
    return user.faculty_id is None or student.faculty_id == user.faculty_id


def _student(db: Session, user: User, sid: int) -> User:
    st = db.get(User, sid)
    if not st or not can_manage(db, user, st):
        raise not_found("الطالب غير موجود")
    return st


def _record_out(r: StudentRecord | None) -> dict:
    if r is None:
        return {f: None for f in RECORD_FIELDS} | {"national_id": None, "status": "active", "updated_at": None}
    out = {f: getattr(r, f) for f in RECORD_FIELDS}
    out["national_id"] = decrypt_str(r.national_id_enc) if r.national_id_enc else None
    out["updated_at"] = r.updated_at
    return out


def _doc_out(d: StudentDocument, f: StoredFile, uploader: str | None) -> dict:
    return {"id": d.id, "doc_type": d.doc_type, "type_label": DOC_TYPES.get(d.doc_type, d.doc_type), "title": d.title,
            "notes": d.notes, "file": files.file_info(f), "uploaded_by": uploader, "created_at": d.created_at}


@router.get("/meta")
def meta(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not can_manage(db, user):
        raise forbidden()
    return {"doc_types": DOC_TYPES, "statuses": STATUSES,
            "max_file_mb": tenant_settings(db, user)["archive"]["max_file_mb"]}


@router.get("/students")
def list_students(q: str | None = Query(default=None, max_length=100), department_id: int | None = None,
                  cohort: str | None = None, limit: int = Query(default=50, le=200), offset: int = 0,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not can_manage(db, user):
        raise forbidden()
    stmt = select(User).where(User.university_id == user.university_id, User.role == Role.STUDENT)
    if user.role != Role.UNIVERSITY_ADMIN and user.faculty_id is not None:
        stmt = stmt.where(User.faculty_id == user.faculty_id)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if cohort:
        stmt = stmt.where(User.cohort == cohort)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.code.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    students = db.scalars(stmt.order_by(User.code).limit(limit).offset(offset)).all()
    ids = [s.id for s in students] or [-1]
    counts = dict(db.execute(select(StudentDocument.student_id, func.count()).where(
        StudentDocument.student_id.in_(ids), StudentDocument.deleted_at.is_(None)).group_by(StudentDocument.student_id)).all())
    records = {r.student_id: r for r in db.scalars(select(StudentRecord).where(StudentRecord.student_id.in_(ids)))}
    deps = {d.id: d.name for d in db.scalars(select(Department).where(Department.university_id == user.university_id))}
    return {"total": total, "items": [{
        "id": s.id, "full_name": s.full_name, "code": s.code, "cohort": s.cohort,
        "department": deps.get(s.department_id), "documents": counts.get(s.id, 0),
        "status": records[s.id].status if s.id in records else "active", "has_record": s.id in records,
    } for s in students]}


@router.get("/students/{sid}")
def get_student(sid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    st = _student(db, user, sid)
    rec = db.scalar(select(StudentRecord).where(StudentRecord.student_id == st.id))
    docs = db.execute(select(StudentDocument, StoredFile).join(StoredFile, StoredFile.id == StudentDocument.file_id)
                      .where(StudentDocument.student_id == st.id, StudentDocument.deleted_at.is_(None))
                      .order_by(StudentDocument.id.desc())).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({d.uploaded_by for d, _ in docs} | ({rec.updated_by} if rec and rec.updated_by else set()) or {-1})))}
    audit.record(db, "archive.viewed", actor=user, target_type="student", target_id=st.id, ip=client_ip(request))
    db.commit()
    dep = db.get(Department, st.department_id) if st.department_id else None
    return {
        "student": {"id": st.id, "full_name": st.full_name, "code": st.code, "cohort": st.cohort, "email": st.email,
                    "phone": st.phone, "department": dep.name if dep else None, "is_active": st.is_active},
        "record": _record_out(rec) | {"updated_by": names.get(rec.updated_by) if rec else None},
        "documents": [_doc_out(d, f, names.get(d.uploaded_by)) for d, f in docs],
    }


class RecordIn(BaseModel):
    national_id: str | None = Field(default=None, max_length=30)
    birth_date: date | None = None
    birth_place: str | None = Field(default=None, max_length=100)
    nationality: str | None = Field(default=None, max_length=60)
    gender: str | None = Field(default=None, pattern="^(male|female)$")
    address: str | None = Field(default=None, max_length=300)
    guardian_name: str | None = Field(default=None, max_length=200)
    guardian_relation: str | None = Field(default=None, max_length=50)
    guardian_phone: str | None = Field(default=None, max_length=30)
    high_school: str | None = Field(default=None, max_length=200)
    high_school_year: str | None = Field(default=None, max_length=10)
    high_school_score: float | None = Field(default=None, ge=0, le=100)
    admission_date: date | None = None
    status: str | None = Field(default=None, pattern="^(active|suspended|graduated|withdrawn)$")
    notes: str | None = Field(default=None, max_length=5000)


@router.put("/students/{sid}/record")
def save_record(sid: int, body: RecordIn, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    st = _student(db, user, sid)
    rec = db.scalar(select(StudentRecord).where(StudentRecord.student_id == st.id))
    if rec is None:
        rec = StudentRecord(university_id=st.university_id, student_id=st.id, status="active")
        db.add(rec)
    data = body.model_dump(exclude_unset=True)
    changed = []
    if "national_id" in data:
        nid = (data.pop("national_id") or "").strip()
        old = decrypt_str(rec.national_id_enc) if rec.national_id_enc else ""
        if nid != old:
            rec.national_id_enc = encrypt_str(nid) if nid else None
            changed.append("national_id")
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip() or None
        if getattr(rec, k) != v:
            setattr(rec, k, v if not (k == "status" and v is None) else "active")
            changed.append(k)
    rec.updated_by, rec.updated_at = user.id, utcnow()
    # only field names are audited, never the personal values themselves
    audit.record(db, "archive.record_updated", actor=user, target_type="student", target_id=st.id,
                 details={"fields": changed}, ip=client_ip(request))
    db.commit()
    return _record_out(rec)


@router.post("/students/{sid}/documents")
async def upload_document(sid: int, request: Request, doc_type: str = Form(...),
                          title: str = Form("", max_length=200), notes: str = Form("", max_length=500),
                          upload: UploadFile = File(...), user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    st = _student(db, user, sid)
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="نوع المستند غير صحيح")
    data = await files.read_upload(upload, int(tenant_settings(db, user)["archive"]["max_file_mb"]))
    f = files.store(db, owner=user, purpose="archive", filename=upload.filename or "document", data=data,
                    allowed_extensions=["pdf", "jpg", "jpeg", "png"], encrypt=True)
    d = StudentDocument(university_id=st.university_id, student_id=st.id, doc_type=doc_type,
                        title=title.strip() or DOC_TYPES[doc_type], notes=notes.strip() or None, file_id=f.id,
                        uploaded_by=user.id)
    db.add(d)
    db.flush()
    audit.record(db, "archive.document_added", actor=user, target_type="student", target_id=st.id,
                 details={"document_id": d.id, "doc_type": doc_type, "sha256": f.sha256}, ip=client_ip(request))
    db.commit()
    return _doc_out(d, f, user.full_name)


def _document(db: Session, user: User, did: int) -> StudentDocument:
    d = db.get(StudentDocument, did)
    if not d or d.deleted_at is not None:
        raise not_found("المستند غير موجود")
    _student(db, user, d.student_id)
    return d


@router.get("/documents/{did}/file")
def download_document(did: int, request: Request, inline: bool = False, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    d = _document(db, user, did)
    audit.record(db, "archive.document_downloaded", actor=user, target_type="student", target_id=d.student_id,
                 details={"document_id": d.id}, ip=client_ip(request))
    db.commit()
    return files.download_response(db.get(StoredFile, d.file_id), inline=inline)


class DeleteIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/documents/{did}/delete")
def delete_document(did: int, body: DeleteIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Soft delete: hidden from the file but kept for the retention period, with the reason."""
    d = _document(db, user, did)
    d.deleted_at, d.deleted_by, d.delete_reason = utcnow(), user.id, body.reason.strip()
    audit.record(db, "archive.document_deleted", actor=user, target_type="student", target_id=d.student_id,
                 details={"document_id": d.id, "reason": d.delete_reason}, ip=client_ip(request))
    db.commit()
    return {"ok": True}
