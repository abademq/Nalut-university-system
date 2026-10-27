"""Configurable permissions.

Each university can decide which roles hold each capability below. The matrix is stored in
the university settings under ``permissions`` and only the platform administrator may change
it. University administrators always hold every capability, so a university can never be
locked out of its own administration. Scope rules (own faculty, own courses, own university)
still apply on top of these.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Role, User

UA, FA, STAFF, TEACHER, ASSISTANT = (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN, Role.STAFF, Role.TEACHER,
                                     Role.ASSISTANT)

# key -> (group, label, roles that may be granted it, roles holding it by default)
CAPABILITIES: dict[str, tuple[str, str, list[str], list[str]]] = {
    "notify.announcement": ("الإشعارات", "إرسال إعلان عام", [FA, STAFF, TEACHER, ASSISTANT],
                            [FA, TEACHER, ASSISTANT]),
    "notify.academic_note": ("الإشعارات", "إرسال ملاحظة أكاديمية", [FA, STAFF, TEACHER, ASSISTANT],
                             [FA, TEACHER, ASSISTANT]),
    "notify.official_warning": ("الإشعارات", "إصدار إنذار رسمي", [FA, STAFF, TEACHER, ASSISTANT], [FA]),
    "notify.admin_notice": ("الإشعارات", "إرسال تعميم إداري", [FA, STAFF, TEACHER, ASSISTANT], [FA, STAFF]),
    "users.manage": ("الإدارة", "إنشاء وتعديل حسابات المستخدمين في الكلية", [FA], [FA]),
    "structure.departments": ("الإدارة", "إضافة الأقسام وتعديلها وحذفها", [FA], [FA]),
    "banners.manage": ("الإدارة", "نشر الإعلانات المثبتة", [FA, STAFF], [FA]),
    "publications.manage": ("الإدارة", "نشر جداول المحاضرات والإعلانات المصورة", [FA, STAFF], [FA]),
    "results.approve": ("الإدارة", "اعتماد النتائج ونشرها وإرجاعها", [FA], [FA]),
    "archive.access": ("الإدارة", "أرشيف الطلبة (للموظف: مكاتب الأرشيف فقط)", [FA, STAFF], [FA, STAFF]),
    "audit.view": ("الإدارة", "الاطلاع على سجل التدقيق", [FA], [FA]),
    "messages.moderate": ("الإدارة", "معالجة بلاغات الرسائل وإخفاء المخالف منها", [FA], [FA]),
    "courses.manage": ("المقررات", "إنشاء المقررات وتعديلها وإسناد الأساتذة وتسجيل الطلبة", [FA], [FA]),
    "courses.schedule": ("المقررات", "تعديل مواعيد محاضرات مقرراته", [TEACHER, ASSISTANT], [TEACHER, ASSISTANT]),
    "courses.components": ("المقررات", "إدارة عناصر التقييم في مقرراته", [TEACHER, ASSISTANT], [TEACHER, ASSISTANT]),
    "grades.enter": ("الدرجات", "رصد الدرجات وتعديلها واستيرادها", [TEACHER, ASSISTANT], [TEACHER, ASSISTANT]),
    "results.submit": ("الدرجات", "رفع نتائج المقرر للاعتماد", [TEACHER, ASSISTANT], [TEACHER, ASSISTANT]),
    "assignments.manage": ("التدريس", "إنشاء المهام وتقييم التسليمات ونشر درجاتها", [TEACHER, ASSISTANT],
                           [TEACHER, ASSISTANT]),
    "attendance.manage": ("التدريس", "فتح جلسات الحضور والتسجيل اليدوي ومراجعة الحالات", [TEACHER, ASSISTANT],
                          [TEACHER, ASSISTANT]),
    "staff.view": ("شؤون الموظفين", "الاطلاع على ملفات الموظفين", [FA, STAFF], [FA]),
    "staff.manage": ("شؤون الموظفين", "تعديل ملفات الموظفين ومستنداتهم", [FA, STAFF], []),
    "students.view": ("شؤون الطلبة", "قسم الطلبة: القوائم والوضع الدراسي لكل طالب", [FA, STAFF, TEACHER, ASSISTANT],
                      [FA, STAFF]),
    "faculty.view": ("شؤون أعضاء هيئة التدريس", "الاطلاع على ملفات أعضاء هيئة التدريس", [FA, STAFF], [FA]),
    "faculty.manage": ("شؤون أعضاء هيئة التدريس", "تعديل ملفات أعضاء هيئة التدريس ومستنداتهم", [FA, STAFF], []),
    "reports.view": ("التقارير", "التقارير والإحصاءات وتقارير الأفراد", [FA, TEACHER, ASSISTANT],
                     [FA, TEACHER, ASSISTANT]),
}

DEFAULT_PERMISSIONS = {key: list(default) for key, (_, _, _, default) in CAPABILITIES.items()}


def allowed(db: Session, user: User, key: str) -> bool:
    """True when the user's role holds the capability in their university, or one of their groups does."""
    if user.role == UA:
        return True
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
GROUP_ROLES = (FA, STAFF, TEACHER, ASSISTANT)


def require(db: Session, user: User, key: str) -> None:
    """Refuses the action when the user's role can be granted ``key`` but neither the role nor a group has it.

    Roles outside the capability's options keep their fixed rules (checked by the caller), so a
    faculty administrator managing a course is not affected by an instructor-only capability.
    """
    if user.role in CAPABILITIES[key][2] and not allowed(db, user, key):
        from .deps import forbidden

        raise forbidden(f"صلاحية «{CAPABILITIES[key][1]}» غير مفعلة لحسابك")


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
