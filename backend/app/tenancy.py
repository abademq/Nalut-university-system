"""Per-university configuration (branding, grading, attendance and messaging policies)."""
from __future__ import annotations

import copy

from .permissions import DEFAULT_PERMISSIONS

DEFAULT_SETTINGS: dict = {
    "branding": {
        "display_name": None,
        "logo_url": None,
        "primary_color": "#0f5c4d",
        "accent_color": "#c8a24a",
    },
    "languages": ["ar", "en"],
    "default_language": "ar",
    "security": {
        # Administrative accounts must enrol a second factor (TOTP).
        "require_mfa_for_admins": True,
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
