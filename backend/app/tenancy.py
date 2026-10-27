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
        "late_after_minutes": 15,
        "rotation_seconds": 15,
        "warning_absence_percent": 15,
        "limit_absence_percent": 25,
        "default_radius_m": 150,
        # risk score at or above which a check-in waits for human review
        "review_threshold": 50,
        "selfie_retention_days": 30,
        # Per risk level: which extra factors are required.
        "levels": {
            "normal": {"require_location": False, "require_selfie": False},
            "high": {"require_location": True, "require_selfie": True},
        },
    },
    "messaging": {
        # students may only start conversations with staff of courses they are enrolled in
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
