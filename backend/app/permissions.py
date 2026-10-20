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
    "notify.official_warning": ("الإشعارات", "إصدار إنذار رسمي", [FA, TEACHER], [FA]),
    "notify.admin_notice": ("الإشعارات", "إرسال تعميم إداري", [FA, STAFF, TEACHER, ASSISTANT], [FA, STAFF]),
    "users.manage": ("الإدارة", "إنشاء وتعديل حسابات المستخدمين في الكلية", [FA], [FA]),
    "structure.departments": ("الإدارة", "إضافة الأقسام وتعديلها وحذفها", [FA], [FA]),
    "banners.manage": ("الإدارة", "نشر الإعلانات المثبتة", [FA], [FA]),
    "results.approve": ("الإدارة", "اعتماد النتائج ونشرها وإرجاعها", [FA], [FA]),
    "archive.access": ("الإدارة", "أرشيف الطلبة (للموظف: مكاتب الأرشيف فقط)", [FA, STAFF], [FA, STAFF]),
}

DEFAULT_PERMISSIONS = {key: list(default) for key, (_, _, _, default) in CAPABILITIES.items()}


def allowed(db: Session, user: User, key: str) -> bool:
    """True when the user's role holds the capability in their university."""
    if user.role == UA:
        return True
    from .deps import tenant_settings  # local import: deps imports models only

    roles = tenant_settings(db, user).get("permissions", {}).get(key, DEFAULT_PERMISSIONS.get(key, []))
    return user.role in roles


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
