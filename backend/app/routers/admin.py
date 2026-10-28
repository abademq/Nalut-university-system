"""Organisation structure, users, settings and audit log."""
from __future__ import annotations

import re
import secrets
import string
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, mfa, permissions
from ..config import settings
from ..db import get_db
from ..deps import (
    can_manage_user,
    can_view_user,
    client_ip,
    forbidden,
    get_current_user,
    manageable_roles,
    not_found,
    require_roles,
)
from ..models import (
    AuditLog,
    CourseStaff,
    Department,
    Enrollment,
    Faculty,
    MfaPreference,
    PermissionGroup,
    PermissionGroupMember,
    Role,
    Term,
    University,
    User,
)
from ..routers.auth import normalize_identifier
from ..security import hash_password
from ..tenancy import (
    DEFAULT_SETTINGS,
    effective_settings,
    validate_launch,
    validate_policies,
)

# any account but a student: what each may do is then decided by the permission matrix
STAFF_MEMBERS = require_roles(Role.PLATFORM_ADMIN, Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.STAFF,
                              Role.TEACHER, Role.ASSISTANT)

router = APIRouter(prefix="/api", tags=["admin"])


def temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def user_out(u: User) -> dict:
    return {"id": u.id, "full_name": u.full_name, "role": u.role, "email": u.email, "phone": u.phone,
            "code": u.code, "cohort": u.cohort, "office": u.office, "faculty_id": u.faculty_id,
            "department_id": u.department_id, "is_active": u.is_active, "mfa_enabled": u.mfa_enabled,
            "last_login_at": u.last_login_at, "university_id": u.university_id}


class MfaAdminIn(BaseModel):
    required: bool | None = None  # make a second factor mandatory for this one account
    reset: bool = False  # forget the enrolled factor (lost phone): the user enrols again at next login


@router.post("/users/{uid}/mfa")
def admin_mfa(uid: int, body: MfaAdminIn, request: Request,
              actor: User = Depends(STAFF_MEMBERS),
              db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not can_manage_user(actor, u):
        raise not_found("المستخدم غير موجود")
    _require_user_admin(db, actor)
    if body.required is not None:
        pref = mfa.preference(db, u)
        if not pref:
            pref = MfaPreference(user_id=u.id)
            db.add(pref)
        pref.forced, pref.forced_by = body.required, actor.id
    if body.reset:
        u.mfa_enabled, u.mfa_secret_enc = False, None
    audit.record(db, "user.mfa_changed", actor=actor, target_type="user", target_id=u.id,
                 details={"required": body.required, "reset": body.reset}, ip=client_ip(request))
    db.commit()
    return {"mfa_enabled": u.mfa_enabled, "mfa_required": mfa.required_for(db, u),
            "mfa_forced": bool((p := mfa.preference(db, u)) and p.forced),
            "mfa_method": mfa.method_of(db, u) if u.mfa_enabled else None}


# --------------------------------------------------------------------------- universities (platform)


class UniversityIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=200)
    admin_name: str = Field(min_length=2, max_length=200)
    admin_email: str = Field(min_length=5, max_length=200)


@router.get("/universities")
def list_universities(user: User = Depends(require_roles(Role.PLATFORM_ADMIN)), db: Session = Depends(get_db)):
    out = []
    for u in db.scalars(select(University).order_by(University.id)):
        users = db.scalar(select(func.count(User.id)).where(User.university_id == u.id))
        out.append({"id": u.id, "code": u.code, "name": u.name, "is_active": u.is_active, "users": users,
                    "created_at": u.created_at})
    return out


@router.post("/universities")
def create_university(body: UniversityIn, request: Request,
                      user: User = Depends(require_roles(Role.PLATFORM_ADMIN)), db: Session = Depends(get_db)):
    if settings.single_university:
        raise HTTPException(status_code=400, detail="المنصة مخصصة لجامعة واحدة (SINGLE_UNIVERSITY)")
    if db.scalar(select(University.id).where(University.code == body.code)):
        raise HTTPException(status_code=400, detail="رمز الجامعة مستخدم")
    email = body.admin_email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=400, detail="البريد مستخدم")
    uni = University(code=body.code, name=body.name, settings={})
    db.add(uni)
    db.flush()
    pw = temp_password()
    admin = User(university_id=uni.id, role=Role.UNIVERSITY_ADMIN, full_name=body.admin_name, email=email,
                 password_hash=hash_password(pw), must_change_password=True)
    db.add(admin)
    audit.record(db, "university.created", actor=user, university_id=uni.id, target_type="university",
                 target_id=uni.id, ip=client_ip(request))
    db.commit()
    return {"id": uni.id, "admin_id": admin.id, "temporary_password": pw}


class UniversityPatch(BaseModel):
    name: str | None = None
    is_active: bool | None = None


@router.patch("/universities/{uid}")
def patch_university(uid: int, body: UniversityPatch, request: Request,
                     user: User = Depends(require_roles(Role.PLATFORM_ADMIN)), db: Session = Depends(get_db)):
    uni = db.get(University, uid)
    if not uni:
        raise not_found()
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(uni, k, v)
    audit.record(db, "university.updated", actor=user, university_id=uid, target_type="university", target_id=uid,
                 details=body.model_dump(exclude_none=True), ip=client_ip(request))
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- structure


@router.get("/org/structure")
def structure(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.university_id is None:
        return {"faculties": [], "terms": []}
    fq = select(Faculty).where(Faculty.university_id == user.university_id)
    # only university-level users (university admin, or staff not attached to a faculty) see every faculty
    if user.role != Role.UNIVERSITY_ADMIN and user.faculty_id is not None:
        fq = fq.where(Faculty.id == user.faculty_id)
    facs = db.scalars(fq.order_by(Faculty.id)).all()
    deps = db.scalars(select(Department).where(Department.university_id == user.university_id)).all()
    terms = db.scalars(select(Term).where(Term.university_id == user.university_id).order_by(Term.start_date)).all()
    return {
        "faculties": [{"id": f.id, "name": f.name, "code": f.code,
                       "departments": [{"id": d.id, "name": d.name, "code": d.code}
                                       for d in deps if d.faculty_id == f.id]} for f in facs],
        "terms": [{"id": t.id, "name": t.name, "start_date": t.start_date, "end_date": t.end_date,
                   "is_current": t.is_current} for t in terms],
    }


class FacultyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=40)


@router.post("/org/faculties")
def create_faculty(body: FacultyIn, request: Request, user: User = Depends(STAFF_MEMBERS),
                   db: Session = Depends(get_db)):
    permissions.require_scope(db, user, "structure.faculties", whole=True)
    f = Faculty(university_id=user.university_id, name=body.name, code=body.code, settings={})
    db.add(f)
    db.flush()
    audit.record(db, "faculty.created", actor=user, target_type="faculty", target_id=f.id, ip=client_ip(request))
    db.commit()
    return {"id": f.id}


class DepartmentIn(BaseModel):
    faculty_id: int
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=40)


@router.post("/org/departments")
def create_department(body: DepartmentIn, request: Request,
                      user: User = Depends(STAFF_MEMBERS),
                      db: Session = Depends(get_db)):
    fac = db.get(Faculty, body.faculty_id)
    if not fac or fac.university_id != user.university_id:
        raise not_found("الكلية غير موجودة")
    permissions.require_scope(db, user, "structure.departments", fac.id)
    d = Department(university_id=user.university_id, faculty_id=fac.id, name=body.name, code=body.code)
    db.add(d)
    db.flush()
    audit.record(db, "department.created", actor=user, target_type="department", target_id=d.id,
                 ip=client_ip(request))
    db.commit()
    return {"id": d.id}


class FacultyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=40)


def _faculty(db: Session, user: User, fid: int) -> Faculty:
    f = db.get(Faculty, fid)
    if not f or f.university_id != user.university_id:
        raise not_found("الكلية غير موجودة")
    return f


@router.patch("/org/faculties/{fid}")
def patch_faculty(fid: int, body: FacultyPatch, request: Request,
                  user: User = Depends(STAFF_MEMBERS), db: Session = Depends(get_db)):
    f = _faculty(db, user, fid)
    permissions.require_scope(db, user, "structure.faculties", f.id)
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(f, k, v.strip())
    audit.record(db, "faculty.updated", actor=user, target_type="faculty", target_id=f.id, details=data,
                 ip=client_ip(request))
    db.commit()
    return {"ok": True}


def _ensure_empty(db: Session, column, value, what: str) -> None:
    from ..models import Course

    if db.scalar(select(func.count(User.id)).where(getattr(User, column) == value)) or \
            db.scalar(select(func.count(Course.id)).where(getattr(Course, column) == value)):
        raise HTTPException(status_code=400, detail=f"لا يمكن حذف {what} لوجود مستخدمين أو مقررات مرتبطة به")


@router.delete("/org/faculties/{fid}")
def delete_faculty(fid: int, request: Request, user: User = Depends(STAFF_MEMBERS),
                   db: Session = Depends(get_db)):
    f = _faculty(db, user, fid)
    permissions.require_scope(db, user, "structure.faculties", whole=True)
    _ensure_empty(db, "faculty_id", f.id, "الكلية")
    if db.scalar(select(func.count(Department.id)).where(Department.faculty_id == f.id)):
        raise HTTPException(status_code=400, detail="احذف أقسام الكلية أولاً")
    audit.record(db, "faculty.deleted", actor=user, target_type="faculty", target_id=f.id, details={"name": f.name},
                 ip=client_ip(request))
    db.delete(f)
    db.commit()
    return {"ok": True}


def _department(db: Session, user: User, did: int) -> Department:
    d = db.get(Department, did)
    if not d or d.university_id != user.university_id:
        raise not_found("القسم غير موجود")
    permissions.require_scope(db, user, "structure.departments", d.faculty_id)
    return d


@router.patch("/org/departments/{did}")
def patch_department(did: int, body: FacultyPatch, request: Request,
                     user: User = Depends(STAFF_MEMBERS),
                     db: Session = Depends(get_db)):
    d = _department(db, user, did)
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(d, k, v.strip())
    audit.record(db, "department.updated", actor=user, target_type="department", target_id=d.id, details=data,
                 ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.delete("/org/departments/{did}")
def delete_department(did: int, request: Request,
                      user: User = Depends(STAFF_MEMBERS),
                      db: Session = Depends(get_db)):
    d = _department(db, user, did)
    _ensure_empty(db, "department_id", d.id, "القسم")
    audit.record(db, "department.deleted", actor=user, target_type="department", target_id=d.id,
                 details={"name": d.name}, ip=client_ip(request))
    db.delete(d)
    db.commit()
    return {"ok": True}


class TermIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    is_current: bool = False


@router.post("/org/terms")
def create_term(body: TermIn, user: User = Depends(STAFF_MEMBERS),
                db: Session = Depends(get_db)):
    permissions.require_scope(db, user, "structure.terms", whole=True)
    if body.is_current:
        for t in db.scalars(select(Term).where(Term.university_id == user.university_id)):
            t.is_current = False
    if body.end_date <= body.start_date:
        raise HTTPException(status_code=400, detail="تاريخ النهاية يجب أن يكون بعد البداية")
    t = Term(university_id=user.university_id, **body.model_dump())
    db.add(t)
    db.commit()
    return {"id": t.id}


class TermPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


def _term(db: Session, user: User, tid: int) -> Term:
    permissions.require_scope(db, user, "structure.terms", whole=True)
    t = db.get(Term, tid)
    if not t or t.university_id != user.university_id:
        raise not_found("الفصل غير موجود")
    return t


@router.patch("/org/terms/{tid}")
def patch_term(tid: int, body: TermPatch, request: Request,
               user: User = Depends(STAFF_MEMBERS), db: Session = Depends(get_db)):
    t = _term(db, user, tid)
    data = body.model_dump(exclude_none=True)
    if data.get("is_current"):
        for other in db.scalars(select(Term).where(Term.university_id == user.university_id, Term.id != t.id)):
            other.is_current = False
    for k, v in data.items():
        setattr(t, k, v)
    if t.end_date <= t.start_date:
        raise HTTPException(status_code=400, detail="تاريخ النهاية يجب أن يكون بعد البداية")
    audit.record(db, "term.updated", actor=user, target_type="term", target_id=t.id,
                 details={k: str(v) for k, v in data.items()}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.delete("/org/terms/{tid}")
def delete_term(tid: int, request: Request, user: User = Depends(STAFF_MEMBERS),
                db: Session = Depends(get_db)):
    from ..models import Course

    t = _term(db, user, tid)
    if db.scalar(select(func.count(Course.id)).where(Course.term_id == t.id)):
        raise HTTPException(status_code=400, detail="لا يمكن حذف فصل مرتبط بمقررات")
    audit.record(db, "term.deleted", actor=user, target_type="term", target_id=t.id, details={"name": t.name},
                 ip=client_ip(request))
    db.delete(t)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- users


@router.get("/users")
def list_users(role: str | None = None, q: str | None = Query(default=None, max_length=100),
               faculty_id: int | None = None, department_id: int | None = None,
               limit: int = Query(default=50, le=200), offset: int = 0,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.PLATFORM_ADMIN:
        # the platform view lists university administrators; a search looks through every account
        stmt = select(User) if q else select(User).where(User.role == Role.UNIVERSITY_ADMIN)
    else:
        stmt = select(User).where(User.university_id == user.university_id)
        if user.role == Role.UNIVERSITY_ADMIN:
            pass
        elif user.role in (Role.FACULTY_ADMIN, Role.STAFF):
            if user.faculty_id is not None:
                stmt = stmt.where(User.faculty_id == user.faculty_id)
        elif user.role in Role.INSTRUCTORS:
            my_courses = select(CourseStaff.course_id).where(CourseStaff.user_id == user.id)
            stmt = stmt.where(User.id.in_(select(Enrollment.student_id).where(Enrollment.course_id.in_(my_courses))))
        else:
            raise forbidden()
    if role:
        stmt = stmt.where(User.role == role)
    if faculty_id:
        stmt = stmt.where(User.faculty_id == faculty_id)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if q:
        like = f"%{q.strip()}%"
        match = [User.full_name.ilike(like), User.code.ilike(like), User.email.ilike(like)]
        tail = _phone_tail(q)
        digits = re.sub(r"\D", "", q.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
        if tail or len(digits) >= 4:
            match.append(User.phone.like(f"%{tail or digits}%"))
        stmt = stmt.where(or_(*match))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.role, User.full_name).limit(limit).offset(offset)).all()
    full = user.role in Role.ADMINS
    if user.role == Role.PLATFORM_ADMIN:
        names = {x.id: x.name for x in db.scalars(select(University))}
        return {"total": total, "items": [{**user_out(u), "university": names.get(u.university_id)} for u in rows]}
    return {"total": total, "items": [user_out(u) if full else
                                      {"id": u.id, "full_name": u.full_name, "role": u.role, "code": u.code}
                                      for u in rows]}


class UserIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    role: str
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    code: str | None = Field(default=None, max_length=40)
    cohort: str | None = Field(default=None, max_length=20)
    office: str | None = Field(default=None, max_length=40)
    faculty_id: int | None = None
    department_id: int | None = None


def _check_placement(db: Session, actor: User, faculty_id: int | None, department_id: int | None) -> None:
    if faculty_id is not None:
        fac = db.get(Faculty, faculty_id)
        if not fac or fac.university_id != actor.university_id:
            raise HTTPException(status_code=400, detail="الكلية غير صحيحة")
    if actor.role != Role.UNIVERSITY_ADMIN and not permissions.is_platform(actor) \
            and actor.faculty_id is not None and faculty_id != actor.faculty_id:
        raise forbidden("يمكنك إدارة مستخدمي كليتك فقط")
    if department_id is not None:
        dep = db.get(Department, department_id)
        if not dep or dep.faculty_id != faculty_id:
            raise HTTPException(status_code=400, detail="القسم لا يتبع الكلية المحددة")


def _phone_tail(phone: str | None) -> str | None:
    """The last 9 digits, so 0916166288, 916166288, 218916166288 and +218 91 616 6288 match."""
    digits = re.sub(r"\D", "", (phone or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    return digits[-9:] if len(digits) >= 9 else None


def _owner_label(actor: User, other: User) -> str:
    """Who holds a contact already, told only as far as the actor may see that account."""
    if other.role == Role.PLATFORM_ADMIN:
        return "حساب مشرف المنصة"
    if actor.role == Role.PLATFORM_ADMIN or getattr(actor, "acting_platform_admin", False) \
            or other.university_id == actor.university_id:
        state = "" if other.is_active else "، موقوف"
        where = "" if other.university_id == actor.university_id else " في جامعة أخرى"
        return f"حساب «{other.full_name}» ({ROLE_LABELS.get(other.role, other.role)}{state}){where}"
    return "حساب في جامعة أخرى"


ROLE_LABELS = {Role.PLATFORM_ADMIN: "مشرف المنصة", Role.UNIVERSITY_ADMIN: "إدارة الجامعة",
               Role.FACULTY_ADMIN: "إدارة الكلية", Role.STAFF: "موظف", Role.TEACHER: "عضو هيئة تدريس",
               Role.ASSISTANT: "معيد", Role.STUDENT: "طالب"}


def _normalize_contacts(db: Session, email: str | None, phone: str | None, exclude_id: int | None = None,
                        actor: User | None = None):
    email = email.strip().lower() if email else None
    phone = normalize_identifier(phone)[1] if phone else None
    if not email and not phone:
        raise HTTPException(status_code=400, detail="يجب إدخال البريد أو رقم الهاتف")
    if email:
        other = db.scalar(select(User).where(User.email == email, User.id != (exclude_id or 0)))
        if other:
            who = _owner_label(actor, other) if actor else "حساب آخر"
            raise HTTPException(status_code=400, detail=f"البريد مستخدم مسبقاً في {who}")
    tail = _phone_tail(phone)
    if phone:
        # the same number written differently (0 / 218 / +218) is the same phone
        same = User.phone == phone if not tail else User.phone.like(f"%{tail}")
        other = db.scalar(select(User).where(same, User.id != (exclude_id or 0)))
        if other:
            who = _owner_label(actor, other) if actor else "حساب آخر"
            raise HTTPException(status_code=400, detail=f"رقم الهاتف مستخدم مسبقاً في {who}")
    return email, phone


def _require_user_admin(db: Session, actor: User) -> None:
    if actor.role == Role.PLATFORM_ADMIN:
        return  # the platform manages university administrators (no university of its own)
    if not permissions.allowed(db, actor, "users.manage"):
        raise forbidden("صلاحية «إنشاء وتعديل حسابات المستخدمين» غير مفعلة لحسابك")


@router.post("/users")
def create_user(body: UserIn, request: Request,
                actor: User = Depends(STAFF_MEMBERS),
                db: Session = Depends(get_db)):
    if actor.role == Role.PLATFORM_ADMIN:
        raise forbidden()
    _require_user_admin(db, actor)
    if body.role not in manageable_roles(actor):
        raise forbidden("لا يمكنك إنشاء حساب بهذا الدور")
    sc = permissions.scope(db, actor, "users.manage")
    faculty_id = body.faculty_id if sc == permissions.ALL else sc
    _check_placement(db, actor, faculty_id, body.department_id)
    email, phone = _normalize_contacts(db, body.email, body.phone, actor=actor)
    if body.code and db.scalar(select(User.id).where(User.university_id == actor.university_id, User.code == body.code)):
        raise HTTPException(status_code=400, detail="الرقم الجامعي مستخدم")
    pw = temp_password()
    u = User(university_id=actor.university_id, faculty_id=faculty_id, department_id=body.department_id,
             role=body.role, full_name=body.full_name.strip(), email=email, phone=phone, code=body.code,
             cohort=body.cohort, office=body.office, password_hash=hash_password(pw), must_change_password=True)
    db.add(u)
    db.flush()
    audit.record(db, "user.created", actor=actor, target_type="user", target_id=u.id,
                 details={"role": u.role, "faculty_id": faculty_id}, ip=client_ip(request))
    db.commit()
    # the temporary password is shown once to the administrator and never stored in clear
    return {"user": user_out(u), "temporary_password": pw}


@router.get("/users/{uid}")
def get_user(uid: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not can_view_user(db, actor, u):
        raise not_found("المستخدم غير موجود")
    if actor.role in Role.ADMINS and actor.id != uid:
        pref = mfa.preference(db, u)
        return {**user_out(u), "mfa_required": mfa.required_for(db, u), "mfa_forced": bool(pref and pref.forced),
                "mfa_method": mfa.method_of(db, u) if u.mfa_enabled else None}
    return user_out(u) if actor.role in Role.ADMINS or actor.id == uid else \
        {"id": u.id, "full_name": u.full_name, "role": u.role, "code": u.code}


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    code: str | None = None
    cohort: str | None = None
    office: str | None = None
    faculty_id: int | None = None
    department_id: int | None = None
    is_active: bool | None = None


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, request: Request,
               actor: User = Depends(STAFF_MEMBERS),
               db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or (actor.role != Role.PLATFORM_ADMIN and u.university_id != actor.university_id):
        raise not_found("المستخدم غير موجود")
    if not can_manage_user(actor, u):
        raise forbidden("لا تملك صلاحية تعديل هذا الحساب")
    _require_user_admin(db, actor)
    changes = body.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] not in manageable_roles(actor):
        raise forbidden("لا يمكنك منح هذا الدور")
    if "email" in changes or "phone" in changes:
        changes["email"], changes["phone"] = _normalize_contacts(
            db, changes.get("email", u.email), changes.get("phone", u.phone), exclude_id=u.id, actor=actor)
    if "faculty_id" in changes or "department_id" in changes:
        fid = changes.get("faculty_id", u.faculty_id)
        _check_placement(db, actor, fid, changes.get("department_id", u.department_id))
    for k, v in changes.items():
        setattr(u, k, v)
    audit.record(db, "user.updated", actor=actor, target_type="user", target_id=u.id,
                 details={k: v for k, v in changes.items() if k not in ("email", "phone")}, ip=client_ip(request))
    db.commit()
    return user_out(u)


@router.post("/users/{uid}/reset-password")
def admin_reset_password(uid: int, request: Request,
                         actor: User = Depends(STAFF_MEMBERS),
                         db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not can_manage_user(actor, u):
        raise not_found("المستخدم غير موجود")
    _require_user_admin(db, actor)
    pw = temp_password()
    u.password_hash, u.must_change_password = hash_password(pw), True
    u.failed_logins, u.locked_until = 0, None
    audit.record(db, "user.password_reset_by_admin", actor=actor, target_type="user", target_id=u.id,
                 ip=client_ip(request))
    db.commit()
    return {"temporary_password": pw}


# --------------------------------------------------------------------------- settings


class SettingsIn(BaseModel):
    settings: dict


ALLOWED_SETTING_KEYS = set(DEFAULT_SETTINGS)


@router.get("/settings")
def get_settings(user: User = Depends(STAFF_MEMBERS), db: Session = Depends(get_db)):
    if user.role != Role.FACULTY_ADMIN:  # faculty administrations read the settings they work under
        permissions.require(db, user, "settings.manage")
    uni = db.get(University, user.university_id)
    return {"university": {"id": uni.id, "name": uni.name, "code": uni.code},
            "effective": effective_settings(uni), "overrides": uni.settings or {}}


@router.get("/permissions")
def permission_catalog(user: User = Depends(require_roles(Role.UNIVERSITY_ADMIN)), db: Session = Depends(get_db)):
    uni = db.get(University, user.university_id)
    return {"capabilities": permissions.catalog(), "current": effective_settings(uni)["permissions"],
            "editable": bool(getattr(user, "acting_platform_admin", False))}


# --------------------------------------------------------------------------- permission groups


def _platform_actor(user: User = Depends(require_roles(Role.UNIVERSITY_ADMIN))) -> User:
    if not getattr(user, "acting_platform_admin", False):
        raise forbidden("مجموعات الصلاحيات يعدّلها مشرف المنصة فقط")
    return user


class GroupIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=300)
    capabilities: list[str] = Field(default_factory=list, max_length=100)


def _group_out(db: Session, g: PermissionGroup) -> dict:
    members = db.execute(select(User.id, User.full_name, User.role, User.code).join(
        PermissionGroupMember, PermissionGroupMember.user_id == User.id).where(
        PermissionGroupMember.group_id == g.id).order_by(User.full_name)).all()
    return {"id": g.id, "name": g.name, "description": g.description, "capabilities": g.capabilities or [],
            "members": [{"id": m.id, "full_name": m.full_name, "role": m.role, "code": m.code} for m in members]}


def _valid_caps(caps: list[str]) -> list[str]:
    unknown = sorted(set(caps) - set(permissions.CAPABILITIES))
    if unknown:
        raise HTTPException(status_code=400, detail=f"صلاحيات غير معروفة: {', '.join(unknown)}")
    return sorted(set(caps))


def _own_group(db: Session, user: User, gid: int) -> PermissionGroup:
    g = db.get(PermissionGroup, gid)
    if not g or g.university_id != user.university_id:
        raise not_found()
    return g


@router.get("/permission-groups")
def list_groups(user: User = Depends(require_roles(Role.UNIVERSITY_ADMIN)), db: Session = Depends(get_db)):
    rows = db.scalars(select(PermissionGroup).where(PermissionGroup.university_id == user.university_id)
                      .order_by(PermissionGroup.name))
    return [_group_out(db, g) for g in rows]


@router.post("/permission-groups")
def create_group(body: GroupIn, request: Request, user: User = Depends(_platform_actor), db: Session = Depends(get_db)):
    g = PermissionGroup(university_id=user.university_id, name=body.name.strip(), description=body.description.strip(),
                        capabilities=_valid_caps(body.capabilities))
    db.add(g)
    db.flush()
    audit.record(db, "permissions.group_created", actor=user, target_type="permission_group", target_id=g.id,
                 details={"name": g.name, "capabilities": g.capabilities}, ip=client_ip(request))
    db.commit()
    return _group_out(db, g)


@router.patch("/permission-groups/{gid}")
def patch_group(gid: int, body: GroupIn, request: Request, user: User = Depends(_platform_actor),
                db: Session = Depends(get_db)):
    g = _own_group(db, user, gid)
    g.name, g.description, g.capabilities = body.name.strip(), body.description.strip(), _valid_caps(body.capabilities)
    audit.record(db, "permissions.group_updated", actor=user, target_type="permission_group", target_id=g.id,
                 details={"name": g.name, "capabilities": g.capabilities}, ip=client_ip(request))
    db.commit()
    return _group_out(db, g)


@router.delete("/permission-groups/{gid}")
def delete_group(gid: int, request: Request, user: User = Depends(_platform_actor), db: Session = Depends(get_db)):
    g = _own_group(db, user, gid)
    for m in db.scalars(select(PermissionGroupMember).where(PermissionGroupMember.group_id == g.id)):
        db.delete(m)
    audit.record(db, "permissions.group_deleted", actor=user, target_type="permission_group", target_id=g.id,
                 details={"name": g.name}, ip=client_ip(request))
    db.delete(g)
    db.commit()
    return {"ok": True}


class MembersIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=1000)


@router.put("/permission-groups/{gid}/members")
def set_members(gid: int, body: MembersIn, request: Request, user: User = Depends(_platform_actor),
                db: Session = Depends(get_db)):
    """Replaces the group's members (staff, teachers, assistants and faculty administrators only)."""
    g = _own_group(db, user, gid)
    wanted = set(body.user_ids)
    people = db.scalars(select(User).where(User.id.in_(wanted or [-1]))).all()
    bad = [u.full_name for u in people if u.university_id != user.university_id or u.role not in permissions.GROUP_ROLES]
    if bad or len(people) != len(wanted):
        raise HTTPException(status_code=400, detail="يمكن إضافة الموظفين وأعضاء هيئة التدريس وإدارات الكليات فقط"
                            + (f": {', '.join(bad[:3])}" if bad else ""))
    current = {m.user_id: m for m in db.scalars(select(PermissionGroupMember).where(PermissionGroupMember.group_id == g.id))}
    for uid in wanted - set(current):
        db.add(PermissionGroupMember(group_id=g.id, user_id=uid))
    for uid in set(current) - wanted:
        db.delete(current[uid])
    audit.record(db, "permissions.group_members", actor=user, target_type="permission_group", target_id=g.id,
                 details={"added": sorted(wanted - set(current)), "removed": sorted(set(current) - wanted)},
                 ip=client_ip(request))
    db.commit()
    return _group_out(db, g)


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, user: User = Depends(STAFF_MEMBERS),
                 db: Session = Depends(get_db)):
    permissions.require_scope(db, user, "settings.manage", whole=True)
    unknown = set(body.settings) - ALLOWED_SETTING_KEYS
    if unknown:
        raise HTTPException(status_code=400, detail=f"مفاتيح غير معروفة: {', '.join(sorted(unknown))}")
    if "permissions" in body.settings:
        if not getattr(user, "acting_platform_admin", False):
            raise forbidden("الصلاحيات يعدّلها مشرف المنصة فقط")
        try:
            body.settings["permissions"] = permissions.validate(body.settings["permissions"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    sec = body.settings.get("security", {})
    if not isinstance(sec, dict):
        raise HTTPException(status_code=400, detail="إعدادات الأمان غير صحيحة")
    if "mfa_methods" in sec and (not sec["mfa_methods"] or not set(sec["mfa_methods"]) <= set(mfa.METHODS)):
        raise HTTPException(status_code=400, detail="اختر طريقة تحقق واحدة على الأقل")
    if not set(sec.get("mfa_required_roles") or []) <= set(Role.ALL) - {Role.PLATFORM_ADMIN}:
        raise HTTPException(status_code=400, detail="دور غير معروف في إلزام التحقق")
    if not set(sec.get("mfa_required_capabilities") or []) <= set(permissions.CAPABILITIES):
        raise HTTPException(status_code=400, detail="صلاحية غير معروفة في إلزام التحقق")
    acting = getattr(user, "acting_platform_admin", False)
    current = effective_settings(db.get(University, user.university_id))
    tones = (body.settings.get("notifications") or {}).get("tones")
    if tones is not None:
        from ..notifications import TONE_SLOTS, TONES

        if not isinstance(tones, dict) or not set(tones) <= set(TONE_SLOTS) or not set(tones.values()) <= set(TONES):
            raise HTTPException(status_code=400, detail="نغمة غير معروفة")
        if not acting and {**current["notifications"]["tones"], **tones} != current["notifications"]["tones"]:
            raise forbidden("نغمات الإشعارات يحددها مشرف المنصة فقط")
    if "launch" in body.settings:
        if not acting:
            raise forbidden("شاشة البداية ونغمة التشغيل يحددها مشرف المنصة فقط")
        body.settings["launch"] = validate_launch({**current["launch"], **(body.settings["launch"] or {})})
    validate_policies(body.settings)
    uni = db.get(University, user.university_id)
    merged = dict(uni.settings or {})
    merged.update(body.settings)
    if "permissions" in body.settings:
        merged["_permissions_v"] = 2  # saved by the platform: never re-adjusted at start-up (db.py)
    uni.settings = merged
    audit.record(db, "settings.updated", actor=user, target_type="university", target_id=uni.id,
                 details={"keys": sorted(body.settings)}, ip=client_ip(request))
    db.commit()
    return effective_settings(uni)


# --------------------------------------------------------------------------- audit


@router.get("/audit/meta")
def audit_meta(user: User = Depends(STAFF_MEMBERS), db: Session = Depends(get_db)):
    from .. import audit_labels as L

    if user.role != Role.PLATFORM_ADMIN:
        permissions.require(db, user, "audit.view")
    return {"categories": L.CATEGORIES}


def _target_names(db: Session, rows: list) -> dict[tuple[str, str], str]:
    """Readable names of the records the operations touched (people, courses, units)."""
    from ..models import Course, Term

    wanted: dict[str, set[int]] = {}
    for r in rows:
        # target_id is stored as text; PostgreSQL will not compare it with integer ids
        if r.target_type and r.target_id and str(r.target_id).isdigit():
            wanted.setdefault(r.target_type, set()).add(int(r.target_id))
    out: dict[tuple[str, str], str] = {}
    people = wanted.get("user", set()) | wanted.get("student", set())
    for u in db.scalars(select(User).where(User.id.in_(people or {-1}))):
        for t in ("user", "student"):
            out[(t, str(u.id))] = u.full_name
    for c in db.scalars(select(Course).where(Course.id.in_(wanted.get("course", set()) or {-1}))):
        out[("course", str(c.id))] = f"{c.code} — {c.title}"
    for model, t in ((Faculty, "faculty"), (Department, "department"), (Term, "term"), (University, "university")):
        for x in db.scalars(select(model).where(model.id.in_(wanted.get(t, set()) or {-1}))):
            out[(t, str(x.id))] = x.name
    return out


@router.get("/audit")
def audit_log(action: str | None = None, category: str | None = None, limit: int = Query(default=100, le=500),
              offset: int = 0,
              user: User = Depends(STAFF_MEMBERS), db: Session = Depends(get_db)):
    from .. import audit_labels as L

    sc = permissions.ALL if user.role == Role.PLATFORM_ADMIN else permissions.require_scope(db, user, "audit.view")
    stmt = select(AuditLog)
    if user.role != Role.PLATFORM_ADMIN:
        stmt = stmt.where(AuditLog.university_id == user.university_id)
    if sc != permissions.ALL:  # a faculty-wide holder sees the operations of their faculty's people
        faculty_users = select(User.id).where(User.faculty_id == sc)
        stmt = stmt.where(AuditLog.actor_id.in_(faculty_users))
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if category:
        names = [a for a, (_, c) in L.ACTIONS.items() if c == category]
        stmt = stmt.where(or_(AuditLog.action.in_(names or ["-"]), AuditLog.action.like(f"{category}.%")))
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    actors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.actor_id for r in rows if r.actor_id})))}
    targets = _target_names(db, rows)
    out = []
    for r in rows:
        cat = L.category(r.action)
        target_name = targets.get((r.target_type, str(r.target_id)))
        out.append({
            "id": r.id, "action": r.action, "label": L.label(r.action), "category": cat,
            "category_label": L.CATEGORIES.get(cat, ""), "actor": actors[r.actor_id].full_name if r.actor_id in actors else None,
            "actor_role": actors[r.actor_id].role if r.actor_id in actors else None, "actor_id": r.actor_id,
            "target_type": r.target_type, "target_id": r.target_id,
            "target": (f"{L.TARGETS.get(r.target_type, r.target_type)}: {target_name}" if target_name
                       else (L.TARGETS.get(r.target_type, "") + (f" رقم {r.target_id}" if r.target_id else "")
                             if r.target_type else None)),
            "summary": L.details_line(r.details), "by_platform_admin": bool((r.details or {}).get("by_platform_admin")),
            "details": r.details, "ip": r.ip, "created_at": r.created_at})
    return out


@router.get("/audit/verify")
def audit_verify(user: User = Depends(STAFF_MEMBERS), db: Session = Depends(get_db)):
    if user.role != Role.PLATFORM_ADMIN:
        permissions.require_scope(db, user, "audit.view", whole=True)
    return audit.verify_chain(db)
