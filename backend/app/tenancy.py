"""Per-university configuration (branding, grading, attendance and messaging policies)."""
from __future__ import annotations

import copy
import re

from .permissions import DEFAULT_PERMISSIONS

DEFAULT_SETTINGS: dict = {
    "branding": {
        "display_name": None,
        "logo_url": None,
        "primary_color": "#c9a646",
        "accent_color": "#c9a646",
    },
    "languages": ["ar", "en"],
    "default_language": "ar",
    "security": {
        # Administrative accounts must enrol a second factor (TOTP).
        "require_mfa_for_admins": True,
        # a code by SMS at the first sign-in of an account created with a temporary password
        "first_login_otp": True,
        # also required for these roles, and for whoever holds one of these capabilities
        "mfa_required_roles": [],
        "mfa_required_capabilities": [],
        # second-factor methods users may choose: authenticator app and/or SMS code
        "mfa_methods": ["totp", "sms"],
        # wrong passwords in a row before the account is locked, and for how long
        "max_login_failures": 5,
        "lockout_minutes": 15,
    },
    "grading": {
        "pass_mark": 50,
        # (minimum percentage, letter, Arabic label)
        "scale": [
            [85, "A", "ممتاز"],
            [75, "B", "جيد جداً"],
            [65, "C", "جيد"],
            [50, "D", "مقبول"],
            [0, "F", "راسب"],
        ],
        "low_performance_percent": 50,
    },
    "attendance": {
        # lectures: a student is late this many minutes after the session starts
        "late_after_minutes": 15,
        "default_duration_minutes": 90,
        # staff shifts: an employee is late this many minutes after the shift starts, and
        # leaving more than staff_early_leave_minutes before its end is flagged (0 = not checked)
        "staff_late_after_minutes": 15,
        "staff_early_leave_minutes": 15,
        "staff_default_duration_minutes": 480,
        # check-in opens this many minutes before a session starts
        "open_before_minutes": 10,
        "rotation_seconds": 15,
        "warning_absence_percent": 15,
        "limit_absence_percent": 25,
        "default_radius_m": 150,
        # risk score at or above which a check-in waits for human review
        "review_threshold": 50,
        "selfie_retention_days": 30,
        # points each signal adds to a check-in's risk score
        "risk_weights": {"outside_geofence": 50, "no_device_id": 20, "shared_device": 60,
                         "device_used_by_other_account": 30, "new_device": 15, "face_mismatch": 60},
        # Per risk level: which extra factors are required.
        "levels": {
            "normal": {"require_location": False, "require_selfie": False},
            "high": {"require_location": True, "require_selfie": True},
        },
    },
    "messaging": {
        # whom students may start conversations with: course_staff (the teaching staff of
        # their courses), faculty (also their faculty's staff and administration) or none
        "student_can_message": "course_staff",
        "max_attachment_mb": 5,
    },
    "notifications": {
        "sms_enabled": False,
        # categories whose urgent messages also go out by SMS when SMS is enabled
        "sms_categories": ["official_warning", "admin_notice"],
        "due_reminder_hours": 24,
        # tone each kind of notification plays on phones (names in notifications.TONES)
        "tones": {"normal": "chime", "important": "rising", "urgent": "alarm", "official_warning": "siren"},
    },
    # the app's launch screen and start-up sound; set by the platform administrator only
    "launch": {
        "enabled": True,
        "duration_ms": 1800,  # minimum time on screen, 0-6000
        "title": "منصة الجامعة الذكية",
        "subtitle": "",  # empty: the university's name
        "background": "#2B2622",
        "foreground": "#F7F4EC",
        "accent": "#C9A646",
        "show_loader": True,
        "sound": "welcome",  # a name from notifications.LAUNCH_SOUNDS or TONES, or "none"
    },
    "archive": {
        # staff offices (besides faculty / university administration) allowed to manage student files
        "offices": ["registrar"],
        "max_file_mb": 10,
    },
    # which roles hold each configurable capability (see permissions.py); platform admin only
    "permissions": DEFAULT_PERMISSIONS,
    "uploads": {
        "allowed_extensions": ["pdf", "docx", "doc", "pptx", "xlsx", "txt", "png", "jpg", "jpeg", "zip"],
        "max_file_mb": 20,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def effective_settings(university, faculty=None) -> dict:
    merged = _merge(DEFAULT_SETTINGS, university.settings if university else {})
    if faculty is not None and faculty.settings:
        merged = _merge(merged, faculty.settings)
    return merged


def letter_for(percent: float, grading: dict) -> tuple[str, str]:
    for minimum, letter, label in grading["scale"]:
        if percent >= minimum:
            return letter, label
    return "F", ""


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_launch(launch: dict) -> dict:
    """Checks and normalises the launch screen settings (HTTP 400 on bad values)."""
    from fastapi import HTTPException

    from .notifications import LAUNCH_SOUNDS, TONES

    if not isinstance(launch, dict) or set(launch) - set(DEFAULT_SETTINGS["launch"]):
        raise HTTPException(status_code=400, detail="إعدادات شاشة البداية غير صحيحة")
    out = dict(launch)
    try:
        out["duration_ms"] = int(out["duration_ms"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="مدة شاشة البداية غير صحيحة") from None
    if not 0 <= out["duration_ms"] <= 6000:
        raise HTTPException(status_code=400, detail="مدة شاشة البداية بين 0 و 6 ثوانٍ")
    for key in ("background", "foreground", "accent"):
        if not isinstance(out[key], str) or not _HEX_COLOR.match(out[key]):
            raise HTTPException(status_code=400, detail="لون غير صحيح")
    for key, limit in (("title", 60), ("subtitle", 80)):
        out[key] = str(out[key] or "").strip()[:limit]
    out["enabled"] = bool(out["enabled"])
    out["show_loader"] = bool(out["show_loader"])
    if out["sound"] != "none" and out["sound"] not in LAUNCH_SOUNDS and out["sound"] not in TONES:
        raise HTTPException(status_code=400, detail="نغمة تشغيل غير معروفة")
    return out


# (section, key) -> (minimum, maximum) for the numbers an administration may change
NUMBER_LIMITS = {
    ("security", "max_login_failures"): (3, 20), ("security", "lockout_minutes"): (1, 1440),
    ("attendance", "late_after_minutes"): (0, 180), ("attendance", "default_duration_minutes"): (5, 720),
    ("attendance", "staff_late_after_minutes"): (0, 240), ("attendance", "staff_early_leave_minutes"): (0, 240),
    ("attendance", "staff_default_duration_minutes"): (30, 960), ("attendance", "open_before_minutes"): (0, 120),
    ("attendance", "rotation_seconds"): (5, 120), ("attendance", "warning_absence_percent"): (0, 100),
    ("attendance", "limit_absence_percent"): (0, 100), ("attendance", "review_threshold"): (1, 300),
    ("attendance", "default_radius_m"): (20, 5000), ("attendance", "selfie_retention_days"): (1, 365),
    ("grading", "pass_mark"): (0, 100), ("grading", "low_performance_percent"): (0, 100),
    ("notifications", "due_reminder_hours"): (1, 168), ("messaging", "max_attachment_mb"): (1, 25),
}
NUMBER_LABELS = {
    "max_login_failures": "عدد محاولات الدخول الخاطئة", "lockout_minutes": "مدة قفل الحساب",
    "late_after_minutes": "التأخر عن المحاضرة", "default_duration_minutes": "مدة المحاضرة الافتراضية",
    "staff_late_after_minutes": "التأخر عن الدوام", "staff_early_leave_minutes": "الانصراف المبكر",
    "staff_default_duration_minutes": "مدة الدوام الافتراضية", "open_before_minutes": "فتح التسجيل قبل البداية",
    "rotation_seconds": "مدة صلاحية الرمز", "warning_absence_percent": "نسبة غياب التنبيه",
    "limit_absence_percent": "حد الغياب", "review_threshold": "درجة المراجعة", "default_radius_m": "نطاق القاعة",
    "selfie_retention_days": "مدة الاحتفاظ بالصور", "pass_mark": "درجة النجاح",
    "low_performance_percent": "حد الأداء الضعيف", "due_reminder_hours": "التذكير قبل التسليم",
    "max_attachment_mb": "حجم المرفق",
}
RISK_SIGNALS = ("outside_geofence", "no_device_id", "shared_device", "device_used_by_other_account",
                "new_device", "face_mismatch")
STUDENT_MESSAGING = ("course_staff", "faculty", "none")
NOTIFICATION_CATEGORIES = ("announcement", "academic_note", "official_warning", "admin_notice", "system")


def validate_policies(changes: dict) -> None:
    """Range and shape checks for the policy sections; HTTP 400 naming the field in Arabic."""
    from fastapi import HTTPException

    def bad(msg: str):
        raise HTTPException(status_code=400, detail=msg)

    for (section, key), (lo, hi) in NUMBER_LIMITS.items():
        part = changes.get(section)
        if not isinstance(part, dict) or key not in part:
            continue
        try:
            value = float(part[key])
        except (TypeError, ValueError):
            bad(f"{NUMBER_LABELS[key]}: أدخل رقماً")
        if not lo <= value <= hi:
            bad(f"{NUMBER_LABELS[key]} يجب أن يكون بين {lo} و {hi}")
    att = changes.get("attendance") or {}
    if "warning_absence_percent" in att and "limit_absence_percent" in att \
            and float(att["warning_absence_percent"]) > float(att["limit_absence_percent"]):
        bad("نسبة غياب التنبيه يجب ألا تتجاوز حد الغياب")
    weights = att.get("risk_weights")
    if weights is not None:
        if not isinstance(weights, dict) or not set(weights) <= set(RISK_SIGNALS):
            bad("مؤشرات المخاطر غير صحيحة")
        for k, v in weights.items():
            if not isinstance(v, (int, float)) or not 0 <= v <= 100:
                bad("وزن كل مؤشر مخاطر بين 0 و 100")
    levels = att.get("levels")
    if levels is not None:
        if not isinstance(levels, dict) or not set(levels) <= {"normal", "high"} or any(
                not isinstance(v, dict) or not set(v) <= {"require_location", "require_selfie"}
                or not all(isinstance(x, bool) for x in v.values()) for v in levels.values()):
            bad("مستويات التحقق في الحضور غير صحيحة")
    msg = changes.get("messaging") or {}
    if "student_can_message" in msg and msg["student_can_message"] not in STUDENT_MESSAGING:
        bad("سياسة مراسلة الطلبة غير معروفة")
    cats = (changes.get("notifications") or {}).get("sms_categories")
    if cats is not None and (not isinstance(cats, list) or not set(cats) <= set(NOTIFICATION_CATEGORIES)):
        bad("نوع إشعار غير معروف في الرسائل النصية")
    scale = (changes.get("grading") or {}).get("scale")
    if scale is not None:
        ok = isinstance(scale, list) and 2 <= len(scale) <= 12 and all(
            isinstance(r, list) and len(r) == 3 and isinstance(r[0], (int, float)) and 0 <= r[0] <= 100
            and isinstance(r[1], str) and 1 <= len(r[1].strip()) <= 4 and isinstance(r[2], str)
            and 1 <= len(r[2].strip()) <= 40 for r in scale)
        if not ok:
            bad("سلم التقديرات غير صحيح: لكل تقدير حد أدنى بين 0 و 100 ورمز واسم")
        mins = [r[0] for r in scale]
        if mins != sorted(mins, reverse=True) or len(set(mins)) != len(mins) or mins[-1] != 0:
            bad("رتّب سلم التقديرات من الأعلى للأدنى بحدود مختلفة، وآخرها يبدأ من 0")
