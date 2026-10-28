"""Configurable permissions.

Each university can decide which roles hold each capability below, the university
administration included. The matrix is stored in the university settings under ``permissions``
and only the platform administrator may change it; the platform administrator always holds every
capability, so the platform can never be locked out. Scope rules (own faculty, own courses, own
university) still apply on top of these.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Role, User

UA, FA, STAFF, TEACHER, ASSISTANT = (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.STAFF, Role.TEACHER,
                                     Role.ASSISTANT)

# key -> (group, label, roles that may be granted it, roles holding it by default)
# Every capability can be given to any role (students excepted). A holder acts within their own
# faculty, or across the university when they belong to no faculty (university administration,
# central offices); see scope(). The platform administrator always holds everything.
ROLES = [UA, FA, STAFF, TEACHER, ASSISTANT]
_T, _A = TEACHER, ASSISTANT
CAPABILITIES: dict[str, tuple[str, str, list[str], list[str]]] = {
    "notify.announcement": ("الإشعارات", "إرسال إعلان عام", ROLES, [UA, FA, _T, _A]),
    "notify.academic_note": ("الإشعارات", "إرسال ملاحظة أكاديمية", ROLES, [UA, FA, _T, _A]),
    "notify.official_warning": ("الإشعارات", "إصدار إنذار رسمي", ROLES, [UA, FA]),
    "notify.admin_notice": ("الإشعارات", "إرسال تعميم إداري", ROLES, [UA, FA, STAFF]),
    "users.manage": ("الإدارة", "إنشاء وتعديل حسابات المستخدمين", ROLES, [UA, FA]),
    "structure.faculties": ("الإدارة", "إضافة الكليات وتعديلها وحذفها", ROLES, [UA]),
    "structure.departments": ("الإدارة", "إضافة الأقسام وتعديلها وحذفها", ROLES, [UA, FA]),
    "structure.terms": ("الإدارة", "إدارة الفصول الدراسية", ROLES, [UA]),
    "settings.manage": ("الإدارة", "تعديل إعدادات المؤسسة", ROLES, [UA]),
    "banners.manage": ("الإدارة", "نشر الإعلانات المثبتة", ROLES, [UA, FA]),
    "publications.manage": ("الإدارة", "نشر جداول المحاضرات والإعلانات المصورة", ROLES, [UA, FA]),
    "results.approve": ("الإدارة", "اعتماد النتائج ونشرها وإرجاعها", ROLES, [UA, FA]),
    "archive.access": ("الإدارة", "أرشيف الطلبة (للموظف: مكاتب الأرشيف فقط)", ROLES, [UA, FA, STAFF]),
    "audit.view": ("الإدارة", "الاطلاع على سجل التدقيق", ROLES, [UA, FA]),
    "messages.moderate": ("الإدارة", "معالجة بلاغات الرسائل وإخفاء المخالف منها", ROLES, [UA, FA]),
    "messages.oversight": ("الإدارة", "الاطلاع على كل الرسائل (رقابة الرسائل)", ROLES, [UA]),
    "courses.manage": ("المقررات", "إنشاء المقررات وتعديلها وإسناد الأساتذة وتسجيل الطلبة", ROLES, [UA, FA]),
    "courses.schedule": ("المقررات", "تعديل مواعيد المحاضرات", ROLES, [UA, FA, _T, _A]),
    "courses.components": ("المقررات", "إدارة عناصر التقييم", ROLES, [UA, FA, _T, _A]),
    "grades.enter": ("الدرجات", "رصد الدرجات وتعديلها واستيرادها", ROLES, [UA, FA, _T, _A]),
    "results.submit": ("الدرجات", "رفع نتائج المقرر للاعتماد", ROLES, [UA, FA, _T, _A]),
    "assignments.manage": ("التدريس", "إنشاء المهام وتقييم التسليمات ونشر درجاتها", ROLES, [UA, FA, _T, _A]),
    "attendance.manage": ("التدريس", "فتح جلسات الحضور والتسجيل اليدوي ومراجعة الحالات", ROLES, [UA, FA, _T, _A]),
    "attendance.staff": ("التدريس", "فتح جلسات دوام الموظفين", ROLES, [UA, FA]),
    "staff.view": ("شؤون الموظفين", "الاطلاع على ملفات الموظفين", ROLES, [UA, FA]),
    "staff.manage": ("شؤون الموظفين", "تعديل ملفات الموظفين ومستنداتهم", ROLES, [UA]),
    "students.view": ("شؤون الطلبة", "قسم الطلبة: القوائم والوضع الدراسي لكل طالب", ROLES, [UA, FA, STAFF]),
    "faculty.view": ("شؤون أعضاء هيئة التدريس", "الاطلاع على ملفات أعضاء هيئة التدريس", ROLES, [UA, FA]),
    "faculty.manage": ("شؤون أعضاء هيئة التدريس", "تعديل ملفات أعضاء هيئة التدريس ومستنداتهم", ROLES, [UA]),
    "reports.view": ("التقارير", "التقارير والإحصاءات وتقارير الأفراد", ROLES, [UA, FA, _T, _A]),
}

# Rights some roles used to hold by fixed rule rather than by the matrix: the university
# administration held everything, and faculty administrations the teaching rights over their
# faculty's courses. A university's saved matrix gains these once (db.py, permissions version 2),
# so nobody loses a right they had.
_TEACHING = ("courses.schedule", "courses.components", "grades.enter", "results.submit",
             "assignments.manage", "attendance.manage")
IMPLICIT_BEFORE = {key: ([UA, FA] if key in _TEACHING else [UA]) for key in CAPABILITIES}

DEFAULT_PERMISSIONS = {key: list(default) for key, (_, _, _, default) in CAPABILITIES.items()}


def is_platform(user: User) -> bool:
    return user.role == Role.PLATFORM_ADMIN or bool(getattr(user, "acting_platform_admin", False))


def allowed(db: Session, user: User, key: str) -> bool:
    """True when the user's role holds the capability in their university, or one of their groups does.

    The platform administrator always does, so the matrix can never lock the platform out."""
    if is_platform(user):
        return True
    if user.role == Role.STUDENT:
        return False
    from .deps import tenant_settings  # local import: deps imports models only

    roles = tenant_settings(db, user).get("permissions", {}).get(key, DEFAULT_PERMISSIONS.get(key, []))
    return user.role in roles or key in group_capabilities(db, user)


def group_capabilities(db: Session, user: User) -> set[str]:
    """Capabilities given to the user through permission groups (cached on the user for the request)."""
    cached = getattr(user, "_group_caps", None)
    if cached is not None:
        return cached
    from sqlalchemy import select

    from .models import PermissionGroup, PermissionGroupMember

    caps: set[str] = set()
    if user.id is not None and user.role in GROUP_ROLES:
        for group_caps in db.scalars(select(PermissionGroup.capabilities).join(
                PermissionGroupMember, PermissionGroupMember.group_id == PermissionGroup.id).where(
                PermissionGroupMember.user_id == user.id, PermissionGroup.university_id == user.university_id)):
            caps.update(group_caps or [])
    try:
        user._group_caps = caps
    except AttributeError:
        pass
    return caps


# who can be put in a permission group (students never: their rights are fixed)
GROUP_ROLES = (UA, FA, STAFF, TEACHER, ASSISTANT)
ALL = "all"


def require(db: Session, user: User, key: str) -> None:
    """Refuses the action unless the user (role or group) holds ``key``."""
    if not allowed(db, user, key):
        from .deps import forbidden

        raise forbidden(f"صلاحية «{CAPABILITIES[key][1]}» غير مفعلة لحسابك")


def scope(db: Session, user: User, key: str):
    """Where the user may use ``key``: ALL (the whole university), a faculty id, or None.

    University administration and the platform act everywhere; anyone else within their own
    faculty, or everywhere when they belong to no faculty (central offices)."""
    if not allowed(db, user, key):
        return None
    if is_platform(user) or user.role == UA or not user.faculty_id:
        return ALL
    return user.faculty_id


def require_scope(db: Session, user: User, key: str, faculty_id=None, *, whole: bool = False):
    """scope() or HTTP 403. ``faculty_id``: the record's faculty must be inside the scope;
    ``whole``: the action concerns the whole university (only a university-wide scope)."""
    from .deps import forbidden

    sc = scope(db, user, key)
    if sc is None:
        raise forbidden(f"صلاحية «{CAPABILITIES[key][1]}» غير مفعلة لحسابك")
    if sc != ALL and (whole or (faculty_id is not None and faculty_id != sc)):
        raise forbidden("هذا الإجراء خارج نطاق كليتك")
    return sc


def in_scope(sc, faculty_id) -> bool:
    return sc == ALL or (sc is not None and faculty_id == sc)


def validate(matrix: dict) -> dict:
    """Checks a submitted matrix; returns it cleaned (unknown roles are an error, not ignored)."""
    if not isinstance(matrix, dict):
        raise ValueError("صيغة الصلاحيات غير صحيحة")
    out = {}
    for key, roles in matrix.items():
        if key not in CAPABILITIES:
            raise ValueError(f"صلاحية غير معروفة: {key}")
        if not isinstance(roles, list) or not set(roles) <= set(CAPABILITIES[key][2]):
            raise ValueError(f"أدوار غير مسموحة للصلاحية: {key}")
        out[key] = sorted(set(roles))
    return out


def catalog() -> list[dict]:
    return [{"key": k, "group": g, "label": label, "options": opts, "default": d}
            for k, (g, label, opts, d) in CAPABILITIES.items()]


def holders(db: Session, university_id: int, key: str, faculty_id=None) -> list[int]:
    """Active accounts of the university that may use ``key`` on a record of ``faculty_id``
    (used to address work notifications to whoever the matrix gives the job).

    Those acting inside that faculty come first: the university-wide holders are returned only
    when the faculty has nobody, so the administration is not told of every faculty's routine work."""
    from sqlalchemy import select

    from .models import User

    stmt = select(User).where(User.university_id == university_id, User.is_active.is_(True),
                              User.role.in_(list(GROUP_ROLES)))
    if faculty_id is None:
        stmt = stmt.where(User.faculty_id.is_(None) | (User.role == UA))
    else:
        stmt = stmt.where(User.faculty_id.is_(None) | (User.faculty_id == faculty_id) | (User.role == UA))
    local, wide = [], []
    for u in db.scalars(stmt):
        sc = scope(db, u, key)
        if sc is not None and faculty_id is not None and sc == faculty_id:
            local.append(u.id)
        elif sc == ALL:
            wide.append(u.id)
    return local or wide
