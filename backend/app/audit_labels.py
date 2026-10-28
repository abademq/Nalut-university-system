"""Arabic names for the audit log: each operation, its category, and a readable line of details."""
from __future__ import annotations

# action -> (label, category key)
ACTIONS: dict[str, tuple[str, str]] = {
    # sign-in and account security
    "auth.login": ("تسجيل دخول", "auth"),
    "auth.login_failed": ("محاولة دخول فاشلة", "auth"),
    "auth.locked": ("قفل الحساب مؤقتاً بعد محاولات فاشلة", "auth"),
    "auth.first_login_verified": ("تأكيد رقم الهاتف عند أول دخول", "auth"),
    "auth.password_changed": ("تغيير كلمة المرور", "auth"),
    "auth.password_reset": ("استعادة كلمة المرور", "auth"),
    "auth.reset_requested": ("طلب استعادة كلمة المرور", "auth"),
    "auth.mfa_enabled": ("تفعيل التحقق الثنائي", "auth"),
    "auth.mfa_disabled": ("إيقاف التحقق الثنائي", "auth"),
    "auth.sessions_revoked": ("الخروج من كل الأجهزة", "auth"),
    "auth.refresh_reuse": ("محاولة استخدام جلسة ملغاة (أُلغيت كل جلسات الحساب)", "auth"),
    "auth.refresh_retried": ("تجديد جلسة بعد انقطاع الاتصال", "auth"),
    "notifications.mutes_changed": ("تغيير الإشعارات الموقوفة", "communication"),
    "auth.handoff_started": ("فتح لوحة التحكم من التطبيق", "auth"),
    # accounts
    "user.created": ("إنشاء حساب", "user"),
    "user.updated": ("تعديل بيانات حساب", "user"),
    "user.password_reset_by_admin": ("إعادة تعيين كلمة مرور حساب", "user"),
    "user.mfa_changed": ("تعديل التحقق الثنائي لحساب", "user"),
    "user.profile_self_updated": ("تعديل المستخدم لبياناته", "user"),
    # organisation
    "university.created": ("إنشاء جامعة", "structure"),
    "university.updated": ("تعديل بيانات الجامعة", "structure"),
    "faculty.created": ("إنشاء كلية", "structure"),
    "faculty.updated": ("تعديل كلية", "structure"),
    "faculty.deleted": ("حذف كلية", "structure"),
    "department.created": ("إنشاء قسم", "structure"),
    "department.updated": ("تعديل قسم", "structure"),
    "department.deleted": ("حذف قسم", "structure"),
    "term.updated": ("تعديل فصل دراسي", "structure"),
    "term.deleted": ("حذف فصل دراسي", "structure"),
    "settings.updated": ("تعديل إعدادات المؤسسة", "settings"),
    "launch.image_set": ("تغيير صورة شاشة البداية", "settings"),
    "launch.image_removed": ("إرجاع صورة شاشة البداية الافتراضية", "settings"),
    "permissions.group_created": ("إنشاء مجموعة صلاحيات", "settings"),
    "permissions.group_updated": ("تعديل مجموعة صلاحيات", "settings"),
    "permissions.group_deleted": ("حذف مجموعة صلاحيات", "settings"),
    "permissions.group_members": ("تعديل أعضاء مجموعة صلاحيات", "settings"),
    "system.seeded": ("تهيئة البيانات التجريبية", "settings"),
    # courses and grades
    "course.created": ("إنشاء مقرر", "course"),
    "course.updated": ("تعديل مقرر", "course"),
    "course.staff_assigned": ("إسناد مقرر لعضو هيئة تدريس", "course"),
    "course.staff_removed": ("إلغاء إسناد مقرر", "course"),
    "course.enrolled": ("تسجيل طالب في مقرر", "course"),
    "course.unenrolled": ("إلغاء تسجيل طالب من مقرر", "course"),
    "component.updated": ("تعديل عنصر تقييم", "grade"),
    "component.deleted": ("حذف عنصر تقييم", "grade"),
    "grade.changed": ("تعديل درجة", "grade"),
    "grades.imported": ("استيراد درجات من ملف", "grade"),
    "results.submitted": ("رفع النتائج للاعتماد", "results"),
    "results.approved": ("اعتماد النتائج", "results"),
    "results.published": ("نشر النتائج للطلبة", "results"),
    "results.draft": ("إرجاع النتائج إلى المسودة", "results"),
    "assignment.created": ("إنشاء مهمة", "course"),
    "assignment.updated": ("تعديل مهمة", "course"),
    "submission.regraded": ("تعديل تقييم تسليم", "grade"),
    # attendance
    "attendance.session_created": ("فتح جلسة حضور", "attendance"),
    "attendance.session_closed": ("إغلاق جلسة حضور", "attendance"),
    "attendance.manual": ("تسجيل حضور يدوي", "attendance"),
    "attendance.change": ("تعديل حالة حضور", "attendance"),
    "attendance.selfie_viewed": ("الاطلاع على صورة تحقق", "attendance"),
    # files and records
    "archive.viewed": ("الاطلاع على ملف طالب", "archive"),
    "archive.national_id_viewed": ("إظهار الرقم الوطني لطالب", "archive"),
    "archive.record_updated": ("تعديل بيانات ملف طالب", "archive"),
    "archive.document_added": ("إضافة مستند لملف طالب", "archive"),
    "archive.document_downloaded": ("تنزيل مستند من ملف طالب", "archive"),
    "archive.document_deleted": ("حذف مستند من ملف طالب", "archive"),
    "personnel.viewed": ("الاطلاع على ملف وظيفي", "personnel"),
    "personnel.national_id_viewed": ("إظهار الرقم الوطني في ملف وظيفي", "personnel"),
    "personnel.record_updated": ("تعديل ملف وظيفي", "personnel"),
    "personnel.document_added": ("إضافة مستند لملف وظيفي", "personnel"),
    "personnel.document_downloaded": ("تنزيل مستند من ملف وظيفي", "personnel"),
    "personnel.document_deleted": ("حذف مستند من ملف وظيفي", "personnel"),
    "file.downloaded": ("تنزيل ملف", "archive"),
    # communication
    "notification.sent": ("إرسال إشعار", "communication"),
    "warning.issued": ("إصدار إنذار رسمي", "communication"),
    "banner.created": ("نشر إعلان مثبت", "communication"),
    "banner.updated": ("تعديل إعلان مثبت", "communication"),
    "banner.deleted": ("حذف إعلان مثبت", "communication"),
    "publication.created": ("نشر جدول أو إعلان مصور", "communication"),
    "publication.updated": ("تعديل جدول أو إعلان مصور", "communication"),
    "publication.deleted": ("حذف جدول أو إعلان مصور", "communication"),
    "message.reported": ("الإبلاغ عن رسالة", "communication"),
    "message.report_handled": ("معالجة بلاغ رسالة", "communication"),
    "message.oversight_viewed": ("اطلاع الإدارة على محادثة", "communication"),
    # service requests
    "request.in_review": ("طلب: قيد المراجعة", "requests"),
    "request.needs_documents": ("طلب: مطلوب مستندات", "requests"),
    "request.forwarded": ("طلب: إحالة لجهة أخرى", "requests"),
    "request.approved": ("طلب: اعتماد", "requests"),
    "request.rejected": ("طلب: رفض", "requests"),
    "request.comment": ("طلب: تعليق", "requests"),
}

CATEGORIES = {
    "auth": "الدخول والأمان", "user": "الحسابات", "structure": "الهيكل التنظيمي", "settings": "الإعدادات والصلاحيات",
    "course": "المقررات والمهام", "grade": "الدرجات", "results": "النتائج", "attendance": "الحضور",
    "archive": "ملفات الطلبة", "personnel": "الملفات الوظيفية", "communication": "الإشعارات والإعلانات",
    "requests": "الطلبات والمعاملات",
}

TARGETS = {
    "user": "حساب", "users": "حسابات", "student": "طالب", "course": "مقرر", "faculty": "كلية", "department": "قسم",
    "term": "فصل دراسي", "university": "الجامعة", "assignment": "مهمة", "submission": "تسليم", "grade": "درجة",
    "attendance_session": "جلسة حضور", "attendance_record": "سجل حضور", "banner": "إعلان مثبت",
    "publication": "منشور", "message": "رسالة", "conversation": "محادثة", "notification": "إشعار", "service_request": "طلب",
    "permission_group": "مجموعة صلاحيات", "file": "ملف",
}

# names of the keys found in details (values that are codes are translated with VALUES)
KEYS = {
    "reason": "السبب", "name": "الاسم", "title": "العنوان", "fields": "الحقول", "note": "ملاحظة", "role": "الدور",
    "old": "القيمة السابقة", "new": "القيمة الجديدة", "via": "عن طريق", "method": "الطريقة", "kind": "النوع",
    "section": "القسم", "doc_type": "نوع المستند", "status": "الحالة", "from": "من", "to": "إلى",
    "category": "الفئة", "priority": "الأولوية", "target": "المستهدفون", "targets": "المستهدفون",
    "recipients": "عدد المستلمين", "capabilities": "الصلاحيات", "added": "أُضيف", "removed": "أُزيل",
    "keys": "الأقسام", "rows": "عدد الصفوف", "changed": "عدد التغييرات", "late": "متأخر", "required": "إلزامي",
    "reset": "إعادة تعيين", "risk_level": "مستوى التحقق", "absent_marked": "عدد الغائبين", "comment": "تعليق",
    "action": "الإجراء", "component": "عنصر التقييم", "bytes": "الحجم (بايت)", "files": "الملفات",
    "by_platform_admin": "بواسطة مشرف المنصة", "note_text": "ملاحظة",
}
# technical keys left out of the readable line (ids, hashes)
HIDDEN = {"document_id", "user_id", "student_id", "course_id", "session_id", "import_id", "faculty_id",
          "sha256", "version", "ip"}

VALUES = {
    "student": "طالب", "teacher": "عضو هيئة تدريس", "assistant": "معيد", "staff": "موظف",
    "faculty_admin": "إدارة الكلية", "university_admin": "إدارة الجامعة", "platform_admin": "مشرف المنصة",
    "sms": "رسالة نصية", "totp": "تطبيق المصادقة", "password": "كلمة المرور", "mfa": "رمز التحقق",
    "faculty": "كلية", "staff_section": "الموظفون", "announcement": "إعلان", "academic_note": "ملاحظة أكاديمية",
    "official_warning": "إنذار رسمي", "admin_notice": "تعميم إداري", "system": "النظام", "normal": "عادي",
    "important": "مهم", "urgent": "عاجل", "university": "الجامعة كلها", "course": "مقرر", "department": "قسم",
    "cohort": "دفعة", "users": "أشخاص محددون", "present": "حاضر", "absent": "غائب", "excused": "بعذر",
    "pending_review": "بانتظار المراجعة", "rejected": "مرفوض", "draft": "مسودة", "submitted": "مرفوعة",
    "approved": "معتمدة", "published": "منشورة", "hide": "إخفاء الرسالة", "dismiss": "لا مخالفة",
    "schedule": "جدول محاضرات", "poster": "إعلان مصور", "cv": "السيرة الذاتية", "degree": "شهادة المؤهل",
    "national_id": "الرقم الوطني", "high_school": "شهادة الثانوية", "photo": "صورة شخصية", "otp": "رمز تحقق",
    "template": "رسالة إشعار", "high": "مرتفع",
    True: "نعم", False: "لا",
}

FIELD_NAMES = {
    "full_name": "الاسم", "email": "البريد", "phone": "الهاتف", "code": "الرقم", "role": "الدور",
    "is_active": "الحالة", "faculty_id": "الكلية", "department_id": "القسم", "cohort": "الدفعة", "office": "المكتب",
    "national_id": "الرقم الوطني", "status": "الحالة", "schedule": "مواعيد المحاضرات", "title": "العنوان",
    "credits": "الوحدات", "term_id": "الفصل", "job_title": "المسمى الوظيفي", "academic_rank": "الدرجة العلمية",
    "hire_date": "تاريخ التعيين", "birth_date": "تاريخ الميلاد", "address": "العنوان",
    "branding": "الهوية", "security": "الأمان", "notifications": "الإشعارات", "attendance": "الحضور",
    "grading": "التقييم", "permissions": "الصلاحيات", "launch": "شاشة البداية", "archive": "الأرشيف",
    "messaging": "الرسائل", "uploads": "رفع الملفات", "languages": "اللغات", "default_language": "اللغة الافتراضية",
}


def label(action: str) -> str:
    return ACTIONS.get(action, (action, ""))[0]


def category(action: str) -> str:
    if action in ACTIONS:
        return ACTIONS[action][1]
    return action.split(".", 1)[0]


def _value(v) -> str:
    if isinstance(v, bool):
        return VALUES[v]
    if isinstance(v, list):
        return "، ".join(_value(x) for x in v) or "—"
    if isinstance(v, dict):
        return "، ".join(f"{KEYS.get(k, FIELD_NAMES.get(k, k))}: {_value(x)}" for k, x in v.items())
    if isinstance(v, str):
        return FIELD_NAMES.get(v) or VALUES.get(v) or v
    return str(v)


def details_line(details: dict | None) -> str:
    """The details as one Arabic line, without ids and hashes."""
    parts = []
    for k, v in (details or {}).items():
        if k in HIDDEN or v in (None, "", [], {}):
            continue
        if k == "by_platform_admin":
            continue  # shown as its own badge
        parts.append(f"{KEYS.get(k, k)}: {_value(v)}")
    return " · ".join(parts)
