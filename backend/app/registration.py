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
    from .models import PriorCredit
    from .tenancy import letter_for

    for p in db.scalars(select(PriorCredit).where(PriorCredit.student_id == student.id).order_by(PriorCredit.code)):
        out.append({"id": None, "prior_id": p.id, "code": p.code, "title": p.title, "credits": p.credits,
                    "state": "passed", "source": p.kind, "percent": p.percent,
                    "letter": letter_for(p.percent, grading)[0] if p.percent is not None else None,
                    "term_id": None, "term": "معادلة" if p.kind == "transfer" else "قبل المنصة", "current": False})
    for c, _ in rows:
        state, letter, percent = "in_progress", None, None
        if c.id in published:
            s = grades.student_summary(db, c, student.id, grading)
            state = "passed" if s["passed"] else "failed"
            letter, percent = s["letter"], s["percent"]
        t = terms.get(c.term_id)
        out.append({"id": c.id, "source": "platform", "code": c.code, "title": c.title, "credits": c.credits, "state": state,
                    "letter": letter, "percent": percent, "term_id": c.term_id, "term": t.name if t else None,
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


def _weighted(items: list[dict]) -> float | None:
    credits = sum(i["credits"] for i in items)
    if not credits:
        return None
    return round(sum(i["percent"] * i["credits"] for i in items) / credits, 2)


def transcript(db: Session, student: User, cfg: dict) -> dict:
    """Published results by term, each term's average and the cumulative average.

    Averages are weighted by credits. For the cumulative one a course taken again counts once,
    with its latest published result."""
    from .tenancy import letter_for

    grading = cfg["grading"]
    full = history(db, student, grading)
    prior = [h for h in full if h["source"] != "platform"]
    hist = [h for h in full if h["source"] == "platform" and h["state"] != "in_progress" and h["percent"] is not None]
    term_rows = {t.id: t for t in db.scalars(select(Term).where(Term.id.in_({h["term_id"] for h in hist if h["term_id"]} or {-1})))}
    by_term: dict = {}
    for h in hist:
        by_term.setdefault(h["term_id"], []).append(h)
    order = sorted(by_term, key=lambda tid: (term_rows[tid].start_date.isoformat() if tid in term_rows else "", tid or 0))
    terms, latest = [], {}
    if prior:  # passed outside the platform: first, as their own group
        graded = [i for i in prior if i["percent"] is not None]
        avg = _weighted(graded)
        terms.append({"term_id": None, "term": "مواد منجزة قبل المنصة أو بالمعادلة", "prior": True,
                      "courses": sorted(prior, key=lambda h: h["code"]), "credits": sum(i["credits"] for i in prior),
                      "earned_credits": sum(i["credits"] for i in prior), "average": avg,
                      "letter": letter_for(avg, grading)[0] if avg is not None else None,
                      "label": letter_for(avg, grading)[1] if avg is not None else None})
        for i in prior:
            latest[i["code"]] = i
    for tid in order:
        items = sorted(by_term[tid], key=lambda h: h["code"])
        avg = _weighted(items)
        t = term_rows.get(tid)
        terms.append({"term_id": tid, "term": t.name if t else "دون فصل", "courses": items,
                      "credits": sum(i["credits"] for i in items),
                      "earned_credits": sum(i["credits"] for i in items if i["state"] == "passed"),
                      "average": avg, "letter": letter_for(avg, grading)[0] if avg is not None else None,
                      "label": letter_for(avg, grading)[1] if avg is not None else None})
        for i in items:
            latest[i["code"]] = i
    cum = _weighted([i for i in latest.values() if i["percent"] is not None])
    return {"terms": terms, "cumulative_average": cum,
            "cumulative_letter": letter_for(cum, grading)[0] if cum is not None else None,
            "cumulative_label": letter_for(cum, grading)[1] if cum is not None else None,
            "earned_credits": sum(i["credits"] for i in latest.values() if i["state"] == "passed"),
            "pass_mark": grading["pass_mark"]}


def blocked_by(db: Session, student: User, failed_codes: list[str]) -> dict[str, list[str]]:
    """For each failed code, the courses (codes) that require it."""
    out: dict[str, list[str]] = {}
    for a, b in db.execute(select(CoursePrerequisite.course_code, CoursePrerequisite.required_code).where(
            CoursePrerequisite.faculty_id == student.faculty_id, CoursePrerequisite.required_code.in_(failed_codes or ["-"]))):
        out.setdefault(b, []).append(a)
    return out


# --------------------------------------------------------------------------- study plans


def program_of(db: Session, student: User):
    """The student's programme: the one they were placed in, else the only one of their department."""
    from .models import Program, StudentProgram

    sp = db.scalar(select(StudentProgram).where(StudentProgram.student_id == student.id))
    if sp:
        return db.get(Program, sp.program_id)
    if student.department_id:
        rows = db.scalars(select(Program).where(Program.department_id == student.department_id)).all()
        if len(rows) == 1:
            return rows[0]
    return None


def plan_progress(db: Session, student: User, cfg: dict) -> dict | None:
    """The programme semester by semester with the state of each course, the semester the student
    has reached, what the plan expects next, and the courses of this term that must be passed so
    that next term's courses are not closed to them."""
    from .models import ProgramCourse

    program = program_of(db, student)
    if not program:
        return None
    hist = history(db, student, cfg["grading"])
    state: dict[str, str] = {}
    for h in hist:  # passed wins over a later attempt still running, which wins over a fail
        rank = {"failed": 0, "in_progress": 1, "passed": 2}
        if rank[h["state"]] >= rank.get(state.get(h["code"], ""), -1):
            state[h["code"]] = h["state"]
    rows = list(db.scalars(select(ProgramCourse).where(ProgramCourse.program_id == program.id)
                           .order_by(ProgramCourse.semester, ProgramCourse.code)))
    plan_codes = {r.code for r in rows}
    prereq: dict[str, list[str]] = {}
    for a, b in db.execute(select(CoursePrerequisite.course_code, CoursePrerequisite.required_code).where(
            CoursePrerequisite.faculty_id == program.faculty_id, CoursePrerequisite.course_code.in_(plan_codes or ["-"]))):
        prereq.setdefault(a, []).append(b)
    names = {r.code: r.title for r in rows}
    from .models import StudentSemester

    terms_taken = {h["term_id"] for h in hist if h["term_id"] is not None}
    running = any(h["state"] == "in_progress" for h in hist)
    manual = db.scalar(select(StudentSemester.semester).where(StudentSemester.student_id == student.id))
    if manual:  # set by the administration (transfers, students from before the platform)
        level, nxt = manual, manual + 1
    else:  # counted: the semester the student is in (or has just finished)
        level = max(len(terms_taken), 1)
        nxt = level + 1 if running or terms_taken else 1

    source = {h["code"]: h["source"] for h in hist if h["state"] == "passed"}

    def course_row(r) -> dict:
        st = state.get(r.code, "remaining")
        reqs = sorted(prereq.get(r.code, []))
        return {"code": r.code, "title": r.title, "credits": r.credits, "required": r.required, "semester": r.semester,
                "state": st, "source": source.get(r.code) if st == "passed" else None, "prerequisites": [{"code": c, "title": names.get(c, c), "state": state.get(c, "remaining")}
                                               for c in reqs]}

    semesters = []
    for n in range(1, program.semesters + 1):
        items = [course_row(r) for r in rows if r.semester == n]
        semesters.append({"semester": n, "courses": items, "credits": sum(i["credits"] for i in items),
                          "earned": sum(i["credits"] for i in items if i["state"] == "passed")})
    # next term: this level's courses, and anything left over from earlier semesters
    upcoming = []
    for s in semesters:
        if s["semester"] > nxt:
            break
        for c in s["courses"]:
            if c["state"] in ("passed", "in_progress"):
                continue
            missing = [p for p in c["prerequisites"] if p["state"] != "passed"]
            pending = [p for p in missing if p["state"] == "in_progress"]
            upcoming.append({**c, "overdue": s["semester"] < nxt,
                             "status": "open" if not missing else "pending" if len(pending) == len(missing) else "closed",
                             "missing": missing})
    # this term's courses whose failure would close a course of the next term
    unlocks: dict[str, list[str]] = {}
    for c in upcoming:
        for p in c["prerequisites"]:
            if p["state"] == "in_progress":
                unlocks.setdefault(p["code"], []).append(f"{c['title']} ({c['code']})")
    must_pass = [{"code": k, "title": names.get(k) or next((h["title"] for h in hist if h["code"] == k), k),
                  "unlocks": v} for k, v in sorted(unlocks.items())]
    total = sum(r.credits for r in rows if r.required)
    earned = sum(r.credits for r in rows if state.get(r.code) == "passed")
    return {"program": {"id": program.id, "name": program.name, "code": program.code, "semesters": program.semesters},
            "level": level if (manual or running or terms_taken) else 0, "next_semester": nxt,
            "semester_set_manually": bool(manual),
            "semesters": semesters, "next_courses": upcoming, "must_pass": must_pass,
            "plan_credits": total, "earned_credits": earned, "remaining_credits": max(total - earned, 0)}
