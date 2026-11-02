"""SMS through templates approved by the provider (Resala): one template per kind of message.

Resala only sends texts registered in advance, so a notification never goes out as free text:
it names a template and fills its few short variables. The template ids are entered by the
administration in the institution settings (notifications.sms_templates); each template may
have a second version signed by the university alone, used when the sender belongs to no faculty.
A notification that names no template uses "urgent" (a pointer to the platform)."""
from __future__ import annotations


UNI = "جامعة نالوت"

# key -> (label, faculty version, university version or None, [(variable, label, max letters)])
# The faculty name is always the last variable of the faculty version (without the word "كلية").
CATALOG: dict[str, tuple[str, str, str | None, list[tuple[str, str, int]]]] = {
    "lecture_change": ("تغيير موعد محاضرة", "تغير موعد $1 إلى $2 - كلية $3 بجامعة نالوت",
                       "تغير موعد $1 إلى $2 - جامعة نالوت", [("course", "المقرر", 8), ("time", "الموعد الجديد", 11)]),
    "lecture_cancel": ("إلغاء محاضرة", "ألغيت محاضرة $1 يوم $2 - كلية $3 بجامعة نالوت",
                       "ألغيت محاضرة $1 يوم $2 - جامعة نالوت", [("course", "المقرر", 10), ("day", "اليوم", 6)]),
    "exam": ("موعد امتحان", "امتحان $1 يوم $2 - كلية $3 بجامعة نالوت", "امتحان $1 يوم $2 - جامعة نالوت",
             [("course", "المقرر", 11), ("date", "اليوم والتاريخ", 11)]),
    "assignment": ("مهمة جديدة", "مهمة جديدة في $1 حتى $2 - كلية $3 بجامعة نالوت", None,
                   [("course", "المقرر", 9), ("due", "آخر موعد", 6)]),
    "absence": ("تجاوز حد الغياب", "تجاوزت حد الغياب في $1 - كلية $2 بجامعة نالوت", None,
                [("course", "المقرر", 14)]),
    "result": ("نشر النتائج", "نشرت نتائج $1 في المنصة - كلية $2 بجامعة نالوت", "نشرت نتائج $1 في المنصة - جامعة نالوت",
               [("what", "المقرر أو الفصل", 13)]),
    "summon": ("استدعاء لمراجعة مكتب", "راجع مكتب $1 في أقرب وقت - كلية $2 بجامعة نالوت",
               "راجع مكتب $1 في أقرب وقت - جامعة نالوت", [("office", "المكتب", 12)]),
    "warning": ("إنذار رسمي", "صدر لك إنذار رسمي في $1 - كلية $2 بجامعة نالوت", None, [("course", "المقرر", 13)]),
    "request": ("تحديث على طلب", "طلبك $1، التفاصيل في المنصة - جامعة نالوت", None, [("status", "الحالة", 31)]),
    "free": ("نص حر (لأي إشعار)", "$1 - كلية $2 بجامعة نالوت", "$1 - جامعة نالوت",
             [("message", "نص الرسالة", 70)]),
    "urgent": ("إشعار عاجل (لأي موضوع آخر)", "لديك إشعار عاجل في المنصة - كلية $1 بجامعة نالوت",
               "لديك إشعار عاجل في المنصة - جامعة نالوت", []),
}
FACULTY_MAX = 15
# the faculty version ends with the faculty, except for these (signed by the university only)
NO_FACULTY = {"request"}


def short_faculty(name: str | None) -> str:
    n = (name or "").strip()
    return n[5:].strip() if n.startswith("كلية ") else n


def catalog_out(ids: dict) -> list[dict]:
    out = []
    for key, (label, fac_text, uni_text, vars_) in CATALOG.items():
        conf = (ids or {}).get(key) or {}
        out.append({"key": key, "label": label, "text": fac_text, "text_university": uni_text,
                    "variables": [{"name": n, "label": lab, "max": m} for n, lab, m in vars_],
                    "has_faculty": key not in NO_FACULTY, "faculty_max": FACULTY_MAX,
                    "id": conf.get("id", ""), "id_university": conf.get("id_university", "")})
    return out


def fit(key: str, values: dict) -> dict:
    """For messages the platform sends by itself: each variable cut to its limit."""
    return {n: str(values.get(n, ""))[:m] for n, _, m in CATALOG[key][3]}


def clean_vars(key: str, values: dict) -> dict:
    """Checks the variables of a template chosen for a notification (an error message if not)."""
    if key not in CATALOG:
        raise ValueError("قالب الرسالة النصية غير معروف")
    out = {}
    for name, label, limit in CATALOG[key][3]:
        v = str((values or {}).get(name, "")).strip()
        if not v:
            raise ValueError(f"اكتب «{label}» للرسالة النصية")
        if len(v) > limit:
            raise ValueError(f"«{label}» في الرسالة النصية {len(v)} حرفاً، والحد {limit}")
        out[name] = v
    return out


def choose(key: str | None, ids: dict, faculty_name: str | None) -> tuple[str | None, str, bool]:
    """(template id, key used, faculty version?) for a send. A notification naming no template uses
    the free-text one when it is entered, else "urgent"; a template without the version needed (the
    sender's faculty, or the university alone) falls back the same way; id None: none configured."""
    if key not in CATALOG:
        key = "free" if ((ids or {}).get("free") or {}) else "urgent"
    conf = (ids or {}).get(key) or {}
    if key in NO_FACULTY:
        tid, with_faculty = conf.get("id"), False
    elif faculty_name:
        tid, with_faculty = conf.get("id"), True
    else:
        tid, with_faculty = conf.get("id_university"), False
    if not tid and key not in ("urgent", "free"):
        return choose(None, ids, faculty_name)
    if not tid and key == "free":
        return choose("urgent", ids, faculty_name)
    return tid or None, key, with_faculty


def params(key: str, values: dict, faculty_name: str | None, with_faculty: bool) -> list[str]:
    """$1, $2 ... in order, each within its limit."""
    out = [str((values or {}).get(n, ""))[:m] for n, _, m in CATALOG[key][3]]
    if with_faculty:
        out.append(short_faculty(faculty_name)[:FACULTY_MAX])
    return out


def validate_ids(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("صيغة قوالب الرسائل غير صحيحة")
    out = {}
    for key, conf in value.items():
        if key not in CATALOG or not isinstance(conf, dict):
            raise ValueError(f"قالب غير معروف: {key}")
        item = {}
        for f in ("id", "id_university"):
            v = str(conf.get(f) or "").strip()
            if len(v) > 80:
                raise ValueError("رقم القالب طويل جداً")
            if v:
                item[f] = v
        if item:
            out[key] = item
    return out
