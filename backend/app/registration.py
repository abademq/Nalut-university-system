"""Course registration rules and each student's academic load.

* Prerequisites are kept by course code within the faculty (a course is offered again every term
  under the same code); a prerequisite counts as passed once a result of that code is published
  and the student's total reaches the pass mark.
* Further rules come from the institution settings ("registration"): no repeating a course already
  passed, no two courses of the same term at the same time, and a ceiling on a term's credits.
* Those who register students may override a refusal with a written reason, which is audited."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import grades
from .models import Course, CoursePrerequisite, CourseResult, Enrollment, Term, User


def prerequisites(db: Session, course: Course) -> list[str]:
    return sorted(db.scalars(select(CoursePrerequisite.required_code).where(
        CoursePrerequisite.faculty_id == course.faculty_id, CoursePrerequisite.course_code == course.code)))


def titles(db: Session, university_id: int, codes: list[str]) -> dict[str, str]:
    """The latest title of each code (courses are repeated each term)."""
    out: dict[str, str] = {}
    for code, title in db.execute(select(Course.code, Course.title).where(
            Course.university_id == university_id, Course.code.in_(codes or ["-"])).order_by(Course.id)):
        out[code] = title
    return out


def history(db: Session, student: User, grading: dict) -> list[dict]:
    """Every course the student was registered in, with its credits and outcome:
    passed / failed (published results) or in_progress."""
    rows = db.execute(select(Course, Enrollment.status).join(Enrollment, Enrollment.course_id == Course.id).where(
        Enrollment.student_id == student.id, Enrollment.status == "active").order_by(Course.code)).all()
    published = set(db.scalars(select(CourseResult.course_id).where(
        CourseResult.course_id.in_([c.id for c, _ in rows] or [-1]), CourseResult.status == "published")))
    terms = {t.id: t for t in db.scalars(select(Term).where(Term.id.in_({c.term_id for c, _ in rows if c.term_id} or {-1})))}
    out = []
    for c, _ in rows:
        state, letter = "in_progress", None
        if c.id in published:
            s = grades.student_summary(db, c, student.id, grading)
            state = "passed" if s["passed"] else "failed"
            letter = s["letter"]
        t = terms.get(c.term_id)
        out.append({"id": c.id, "code": c.code, "title": c.title, "credits": c.credits, "state": state,
                    "letter": letter, "term_id": c.term_id, "term": t.name if t else None,
                    "current": bool(t and t.is_current) or (c.term_id is None and state == "in_progress")})
    return out


def passed_codes(db: Session, student: User, grading: dict) -> set[str]:
    return {h["code"] for h in history(db, student, grading) if h["state"] == "passed"}


def summary(db: Session, student: User, cfg: dict) -> dict:
    """Courses and credits: this term's load, credits earned so far, and the courses behind them."""
    hist = history(db, student, cfg["grading"])
    current = [h for h in hist if h["current"]]
    rules = cfg.get("registration") or {}
    load = sum(h["credits"] for h in current)
    lo, hi = int(rules.get("min_credits_per_term") or 0), int(rules.get("max_credits_per_term") or 0)
    return {
        "current_courses": len(current), "current_credits": load,
        "earned_credits": sum(h["credits"] for h in hist if h["state"] == "passed"),
        "passed_courses": sum(1 for h in hist if h["state"] == "passed"),
        "failed_courses": sum(1 for h in hist if h["state"] == "failed"),
        "attempted_credits": sum(h["credits"] for h in hist if h["state"] != "in_progress"),
        "min_credits": lo, "max_credits": hi,
        "load_warning": (f"أقل من الحد الأدنى ({lo} وحدة)" if lo and current and load < lo else
                         f"أكثر من الحد الأعلى ({hi} وحدة)" if hi and load > hi else None),
        "courses": hist,
    }


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _clash(a: list, b: list) -> dict | None:
    for x in a or []:
        for y in b or []:
            if x.get("day") == y.get("day") and _minutes(x["start"]) < _minutes(y["end"]) \
                    and _minutes(y["start"]) < _minutes(x["end"]):
                return x
    return None


def check(db: Session, student: User, course: Course, cfg: dict) -> list[str]:
    """Why ``student`` may not be registered in ``course`` (empty: allowed)."""
    rules = cfg.get("registration") or {}
    problems: list[str] = []
    hist = history(db, student, cfg["grading"])
    passed = {h["code"] for h in hist if h["state"] == "passed"}
    others = [h for h in hist if h["id"] != course.id]
    if rules.get("enforce_prerequisites", True):
        missing = [c for c in prerequisites(db, course) if c not in passed]
        if missing:
            names = titles(db, course.university_id, missing)
            problems.append("لم ينجح في المتطلب السابق: " + "، ".join(f"{names.get(c, c)} ({c})" for c in missing))
    if rules.get("block_passed_repeat", True) and course.code in {h["code"] for h in others if h["state"] == "passed"}:
        problems.append("نجح في هذا المقرر من قبل")
    same_term = [h for h in others if h["term_id"] == course.term_id and h["state"] == "in_progress"]
    if rules.get("block_schedule_clash", True) and same_term:
        for h in same_term:
            other = db.get(Course, h["id"])
            slot = _clash(course.schedule, other.schedule)
            if slot:
                problems.append(f"يتعارض موعده مع {other.title} ({other.code}) يوم {DAYS[slot['day']]} {slot['start']}")
    hi = int(rules.get("max_credits_per_term") or 0)
    load = sum(h["credits"] for h in same_term)
    if hi and load + course.credits > hi:
        problems.append(f"يتجاوز الحد الأعلى للوحدات في الفصل: {load} + {course.credits} > {hi}")
    return problems


DAYS = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"]


def would_cycle(db: Session, faculty_id: int, course_code: str, required: list[str]) -> str | None:
    """A code in ``required`` that already (directly or not) requires ``course_code``."""
    edges: dict[str, set[str]] = {}
    for a, b in db.execute(select(CoursePrerequisite.course_code, CoursePrerequisite.required_code).where(
            CoursePrerequisite.faculty_id == faculty_id, CoursePrerequisite.course_code != course_code)):
        edges.setdefault(a, set()).add(b)
    for start in required:
        seen, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x == course_code:
                return start
            if x not in seen:
                seen.add(x)
                stack.extend(edges.get(x, ()))
    return None
