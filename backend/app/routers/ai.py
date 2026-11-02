"""AI features (Claude): the student's study advisor and outcome outlook, a question assistant,
draft review before submission, course summaries, feedback drafts and review questions for
teachers, written reports and a reading of attendance patterns for the administration, and help
wording announcements. See app/ai.py for the privacy rules."""
from __future__ import annotations

import base64
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai, audit, files, grades, registration
from .. import attendance as att
from ..ai import STR, AiError, arr, obj
from ..db import get_db, utcnow
from ..deps import (
    can_teach_course,
    client_ip,
    forbidden,
    get_course_for,
    get_current_user,
    is_enrolled,
    not_found,
    tenant_settings,
    visible_course_ids,
)
from ..models import (
    AiConsent,
    Assignment,
    Course,
    Enrollment,
    Role,
    StoredFile,
    Submission,
    SubmissionFile,
    User,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])
KNOWLEDGE = (Path(__file__).resolve().parent.parent / "ai_knowledge.md").read_text(encoding="utf-8")
DAYS = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"]


def _fail(exc: AiError):
    return HTTPException(status_code=503, detail=str(exc))


def _out(r: dict, **extra) -> dict:
    return {**r["result"], **extra, "generated_at": r["created_at"], "cached": r["cached"]}


@router.get("/status")
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Which AI features this account can use (the clients show only those)."""
    cfg = tenant_settings(db, user) if user.university_id else {}
    student = user.role == Role.STUDENT
    return {"available": ai.available(cfg, "assistant") or ai.available(cfg, "students") or ai.available(cfg, "staff"),
            "assistant": ai.available(cfg, "assistant"),
            "students": student and ai.available(cfg, "students"),
            "staff": not student and ai.available(cfg, "staff"),
            "consent": ai.has_consent(db, user) if student else None}


# --------------------------------------------------------------------------- consent


@router.post("/me/consent")
def give_consent(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.STUDENT:
        raise forbidden()
    if not ai.has_consent(db, user):
        db.add(AiConsent(user_id=user.id))
        audit.record(db, "ai.consent_given", actor=user, ip=client_ip(request))
        db.commit()
    return {"consent": True}


@router.delete("/me/consent")
def withdraw_consent(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(AiConsent).where(AiConsent.user_id == user.id))
    if row:
        db.delete(row)
        audit.record(db, "ai.consent_withdrawn", actor=user, ip=client_ip(request))
        db.commit()
    return {"consent": False}


# --------------------------------------------------------------------------- 1-2 advisor and outlook


def _student_picture(db: Session, s: User, cfg: dict) -> dict:
    """Everything the advisor needs about one student, without anything that identifies them."""
    tr = registration.transcript(db, s, cfg)
    plan = registration.plan_progress(db, s, cfg)
    now = utcnow()
    courses = []
    for cid in visible_course_ids(db, s):
        c = db.get(Course, cid)
        absence = att.course_absence(db, c.id, s.id)
        due = db.scalars(select(Assignment).where(Assignment.course_id == c.id, Assignment.status == "published")).all()
        subs = {x.assignment_id: x for x in db.scalars(select(Submission).where(
            Submission.student_id == s.id, Submission.assignment_id.in_([a.id for a in due] or [-1])))}
        past = [a for a in due if a.due_at <= now]
        released = [100 * subs[a.id].score / a.max_score for a in past
                    if a.id in subs and subs[a.id].score is not None and subs[a.id].grade_released]
        courses.append({
            "code": c.code, "title": c.title, "credits": c.credits,
            "lectures_held": absence["sessions"], "absence_percent": absence["absence_percent"], "late": absence["late"],
            "assignments_past_due": len(past),
            "submitted": sum(1 for a in past if a.id in subs and subs[a.id].status in ("submitted", "reviewed")),
            "released_assignment_average_percent": round(sum(released) / len(released), 1) if released else None,
            "upcoming": [{"title": a.title, "in_days": max((a.due_at - now).days, 0),
                          "started": a.id in subs} for a in due if now < a.due_at <= now + timedelta(days=14)],
            "weekly_lectures": [f"{DAYS[x['day']]} {x['start']}-{x['end']}" for x in (c.schedule or [])],
        })
    return {
        "pass_mark_percent": cfg["grading"]["pass_mark"],
        "absence_limit_percent": cfg["attendance"]["limit_absence_percent"],
        "published_results_by_term": [{"term": t["term"], "average": t["average"],
                                        "courses": [{"code": c["code"], "title": c["title"], "credits": c["credits"],
                                                     "percent": c["percent"], "result": c["state"]} for c in t["courses"]]}
                                       for t in tr["terms"]],
        "cumulative_average": tr["cumulative_average"],
        "this_term": courses,
        "study_plan": None if not plan else {
            "semester_reached": plan["level"], "remaining_required_credits": plan["remaining_credits"],
            "must_pass_this_term": plan["must_pass"],
            "next_term_courses": [{"code": c["code"], "title": c["title"], "status": c["status"]}
                                  for c in plan["next_courses"]]},
    }


ANALYSIS = obj({
    "summary": STR,
    "strengths": arr(STR),
    "focus": arr(obj({"course": STR, "why": STR, "action": STR})),
    "outlook": arr(obj({"course_code": STR,
                        "outlook": {"type": "string", "enum": ["good", "watch", "at_risk", "unknown"]},
                        "reason": STR})),
    "weekly_plan": arr(obj({"day": STR, "plan": STR})),
    "tip": STR,
})
ANALYSIS_SYSTEM = (
    "Act as a study advisor for one student, writing to them directly (أنت). From the record: "
    "summarise their level in two or three sentences; list real strengths; list the courses to focus "
    "on with the reason and one concrete action each; for every course of this term give an outlook "
    "(good / watch / at_risk / unknown when there is too little data) with the reason, based only on "
    "absence against the limit, submitted work and released assignment scores (final results are not "
    "known yet - say it is an estimate); give a weekly study plan that fits around their lecture times "
    "and the upcoming deadlines; end with one practical tip. If a course of this term is a prerequisite "
    "for next term (must_pass_this_term), stress it."
)


@router.post("/me/analysis")
def my_analysis(fresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The study advisor (1) and the outlook for this term's courses (2)."""
    if user.role != Role.STUDENT:
        raise forbidden()
    cfg = tenant_settings(db, user)
    try:
        ai.require(cfg, "students")
        if not ai.has_consent(db, user):
            raise HTTPException(status_code=409, detail="وافق أولاً على تحليل بياناتك دون اسمك")
        r = ai.run(db, user, kind="student_analysis", subject=f"student:{user.id}", system=ANALYSIS_SYSTEM,
                   data=_student_picture(db, user, cfg), schema=ANALYSIS, fresh=fresh)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    return _out(r)


# --------------------------------------------------------------------------- 3 assistant


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=600)


@router.post("/ask")
def ask(body: AskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Questions about using the platform and the institution's rules, from the guide and settings."""
    cfg = tenant_settings(db, user) if user.university_id else {}
    try:
        ai.require(cfg, "assistant")
        rules = {"attendance": {k: cfg["attendance"].get(k) for k in (
                     "late_after_minutes", "warning_absence_percent", "limit_absence_percent")},
                 "grading": {"pass_mark": cfg["grading"]["pass_mark"], "scale": cfg["grading"]["scale"]},
                 "registration": cfg.get("registration"),
                 "students_may_message": cfg["messaging"].get("student_can_message")} if cfg else {}
        system = ("Answer the user's question about the university platform and the institution's "
                  "rules, using only the guide and the rules below. If the answer is not there, say you "
                  "do not know and suggest the office to ask (شؤون الطلبة، إدارة الكلية). Name the page in "
                  "the platform where they can do it. Keep it under 120 words.\n\n# الدليل\n" + KNOWLEDGE
                  + "\n\n# قواعد المؤسسة الحالية\n" + str(rules))
        r = ai.run(db, user, kind="ask", subject=f"role:{user.role}", system=system,
                   data={"role": user.role, "question": body.question.strip()},
                   schema=obj({"answer": STR}), effort="low", max_tokens=4000)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    return _out(r)


# --------------------------------------------------------------------------- 4 draft review


class DraftIn(BaseModel):
    text: str = Field(min_length=30, max_length=20000)


@router.post("/assignments/{aid}/review-draft")
def review_draft(aid: int, body: DraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Comments on a student's draft before they submit it; never writes the work for them."""
    a = db.get(Assignment, aid)
    if not a or a.university_id != user.university_id or user.role != Role.STUDENT \
            or not is_enrolled(db, user.id, a.course_id) or a.status != "published":
        raise not_found("المهمة غير موجودة")
    cfg = tenant_settings(db, user)
    system = ("Review a student's draft before they submit it. Comment on how well it answers the task, "
              "its organisation, clarity, evidence and language. Do NOT write or rewrite the answer, "
              "do not give solutions; point to what to improve and why. Give a short checklist to go "
              "through before submitting.")
    try:
        ai.require(cfg, "students")
        if not ai.has_consent(db, user):
            raise HTTPException(status_code=409, detail="وافق أولاً على استخدام الذكاء الاصطناعي")
        r = ai.run(db, user, kind="draft_review", subject=f"student:{user.id}", system=system,
                   data={"task_title": a.title, "task_description": a.description, "kind": a.kind,
                         "max_score": a.max_score, "draft": body.text},
                   schema=obj({"overall": STR, "strengths": arr(STR), "improvements": arr(STR), "checklist": arr(STR)}),
                   effort="medium")
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    return _out(r)


# --------------------------------------------------------------------------- 5 course summary


def _teacher_course(db: Session, user: User, cid: int) -> Course:
    c = get_course_for(db, user, cid, teach=True)
    if user.role == Role.STUDENT:
        raise forbidden()
    return c


@router.post("/courses/{cid}/summary")
def course_summary(cid: int, fresh: bool = False, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """For the course's teachers: where the class stands, who needs attention, the hardest parts."""
    from .reports import course_stats

    c = _teacher_course(db, user, cid)
    cfg = tenant_settings(db, user)
    students = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(
        Enrollment.course_id == c.id, Enrollment.status == "active").order_by(User.id)).all()
    comps = grades.components(db, c.id)
    labels, rows = {}, []
    now = utcnow()
    due = db.scalars(select(Assignment).where(Assignment.course_id == c.id, Assignment.status == "published",
                                              Assignment.due_at <= now)).all()
    comp_scores: dict[int, list[float]] = {x.id: [] for x in comps}
    for i, s in enumerate(students, start=1):
        label = f"طالب {i}"
        labels[label] = s
        absence = att.course_absence(db, c.id, s.id)
        subs = {x.assignment_id: x for x in db.scalars(select(Submission).where(
            Submission.student_id == s.id, Submission.assignment_id.in_([a.id for a in due] or [-1])))}
        scored = [100 * subs[a.id].score / a.max_score for a in due if a.id in subs and subs[a.id].score is not None]
        summary = grades.student_summary(db, c, s.id, cfg["grading"], comps)
        for x in comps:
            v = summary["scores"].get(str(x.id))
            if v is not None:
                comp_scores[x.id].append(100 * v / x.max_score)
        rows.append({"student": label, "absence_percent": absence["absence_percent"], "late": absence["late"],
                     "submitted": sum(1 for a in due if a.id in subs and subs[a.id].status in ("submitted", "reviewed")),
                     "assignments_due": len(due),
                     "assignment_average_percent": round(sum(scored) / len(scored), 1) if scored else None,
                     "running_total_percent": summary["percent"] if any(
                         v is not None for v in summary["scores"].values()) else None})
    data = {"course": {"code": c.code, "title": c.title, "credits": c.credits},
            "class": {k: v for k, v in course_stats(db, c).items() if k != "course"},
            "assessment_components": [{"name": x.name, "max": x.max_score,
                                       "class_average_percent": round(sum(v) / len(v), 1) if v else None}
                                      for x, v in ((x, comp_scores[x.id]) for x in comps)],
            "assignments": [{"title": a.title, "kind": a.kind} for a in due],
            "pass_mark_percent": cfg["grading"]["pass_mark"],
            "absence_limit_percent": cfg["attendance"]["limit_absence_percent"],
            "students": rows}
    system = ("Summarise this course for its teacher: where the class stands (attendance, submissions, "
              "scores), which students need attention and why, with one suggestion each (refer to them "
              "only by their label, e.g. طالب 3), which assessment parts were hardest, and two to four "
              "teaching suggestions. Do not judge students; these are signals for the teacher.")
    try:
        ai.require(cfg, "staff")
        r = ai.run(db, user, kind="course_summary", subject=f"course:{c.id}", system=system, data=data,
                   schema=obj({"overview": STR,
                               "at_risk": arr(obj({"student": STR, "reason": STR, "suggestion": STR})),
                               "difficult_parts": arr(STR), "suggestions": arr(STR)}), fresh=fresh)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    res = dict(r["result"])
    res["at_risk"] = [{**x, "student_id": labels[x["student"]].id if x["student"] in labels else None,
                       "full_name": labels[x["student"]].full_name if x["student"] in labels else x["student"]}
                      for x in res.get("at_risk", [])]
    return {**res, "generated_at": r["created_at"], "cached": r["cached"]}


# --------------------------------------------------------------------------- 6 feedback draft


@router.post("/submissions/{sid}/feedback-draft")
def feedback_draft(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A draft comment on one submission for the teacher to edit; nothing is sent to the student."""
    sub = db.get(Submission, sid)
    a = db.get(Assignment, sub.assignment_id) if sub else None
    if not a or a.university_id != user.university_id:
        raise not_found()
    c = db.get(Course, a.course_id)
    if user.role == Role.STUDENT or not can_teach_course(db, user, c):
        raise forbidden()
    cfg = tenant_settings(db, user)
    docs, names = [], []
    for f in db.scalars(select(StoredFile).join(SubmissionFile, SubmissionFile.file_id == StoredFile.id).where(
            SubmissionFile.submission_id == sub.id)):
        ext = files.extension_of(f.original_name or "")
        names.append(f"ملف {ext.upper() or 'بلا امتداد'} {len(names) + 1}")  # file names may carry the student's name
        if ext == "pdf" and (f.size or 0) <= 5 * 1024 * 1024 and len(docs) < 2:
            docs.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                        "data": base64.standard_b64encode(files.read_bytes(f)).decode()}})
    system = ("Draft a short, encouraging and specific comment from the teacher on this submission: "
              "what is good, what to improve, and one next step. The teacher will edit it before sending. "
              "If only file names are given (no content), comment on the note and say the files need the "
              "teacher's reading.")
    try:
        ai.require(cfg, "staff")
        r = ai.run(db, user, kind="feedback_draft", subject=f"submission:{sub.id}", system=system,
                   data={"task_title": a.title, "task_description": a.description, "max_score": a.max_score,
                         "score": sub.score, "late": sub.is_late, "student_note": sub.note, "files": names,
                         "files_attached_for_reading": len(docs)},
                   schema=obj({"feedback": STR}), attachments=docs)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    return _out(r)


# --------------------------------------------------------------------------- 7 review questions


class QuestionsIn(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    count: int = Field(default=5, ge=1, le=15)
    kind: str = Field(default="mixed", pattern="^(mcq|short|mixed)$")
    level: str = Field(default="medium", pattern="^(easy|medium|hard)$")


@router.post("/courses/{cid}/questions")
def review_questions(cid: int, body: QuestionsIn, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    c = _teacher_course(db, user, cid)
    cfg = tenant_settings(db, user)
    system = ("Write review questions for a university course on the topic given, at the level asked, "
              "with the correct answer and a one-line explanation each. For multiple choice give four "
              "choices; for short answer leave choices empty. Questions must be accurate; avoid trick "
              "questions.")
    try:
        ai.require(cfg, "staff")
        r = ai.run(db, user, kind="questions", subject=f"course:{c.id}", system=system,
                   data={"course": f"{c.code} {c.title}", **body.model_dump()},
                   schema=obj({"questions": arr(obj({"question": STR, "choices": arr(STR), "answer": STR,
                                                     "explanation": STR}))}), cache=False)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    return _out(r)


# --------------------------------------------------------------------------- 8 written report


@router.post("/reports/narrative")
def report_narrative(fresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The reports overview, in words, for the administration (aggregates only)."""
    from .reports import overview

    if user.role in (Role.STUDENT, *Role.INSTRUCTORS):
        raise forbidden()
    data = overview(user=user, db=db)
    data = {"people": data["people"], "totals": data["totals"], "breakdown": data["breakdown"],
            "courses": [{k: v for k, v in s.items() if k != "course"} | {"course": s["course"]["code"] + " " + s["course"]["title"]}
                        for s in data["courses"]],
            "pending_attendance_reviews": data["pending_attendance_reviews"],
            "results_awaiting_approval": data["results_awaiting_approval"], "open_requests": data["open_requests"]}
    cfg = tenant_settings(db, user)
    system = ("Write a short report for the university/faculty administration from these statistics of "
              "the last 30 days: one headline, four to six findings with numbers (compare faculties or "
              "departments and name the courses that stand out), and two to four recommendations.")
    try:
        ai.require(cfg, "staff")
        r = ai.run(db, user, kind="report", subject=f"scope:{user.faculty_id or 'all'}", system=system, data=data,
                   schema=obj({"headline": STR, "findings": arr(STR), "recommendations": arr(STR)}), fresh=fresh)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    return _out(r)


# --------------------------------------------------------------------------- 9 attendance patterns


@router.post("/attendance/patterns")
def attendance_patterns(days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A reading of the attendance anomalies for a human to review (never a verdict)."""
    from .attendance import anomalies

    if user.role == Role.STUDENT:
        raise forbidden()
    raw = anomalies(days=days, user=user, db=db)
    labels: dict[int, str] = {}

    def label(u: dict) -> str:
        return labels.setdefault(u["id"], f"حساب {len(labels) + 1}")

    data = {"days": days,
            "shared_devices": [{"device": d["device"], "accounts": [label(u) for u in d["users"]]}
                               for d in raw["shared_devices"]],
            "frequently_flagged": [{"account": label(f["user"]), "flagged_checkins": f["flagged_checkins"]}
                                   for f in raw["frequently_flagged"]],
            "pending_review": raw["pending_review"]}
    cfg = tenant_settings(db, user)
    system = ("Explain these attendance signals to the staff who review them: what each pattern may "
              "mean (innocent explanations included, such as a shared family phone), why it matters, and "
              "what to check. Accounts are labelled (حساب 1 ...). Never accuse anyone; the decision is human.")
    try:
        ai.require(cfg, "staff")
        r = ai.run(db, user, kind="attendance_patterns", subject=f"scope:{user.faculty_id or 'all'}", system=system,
                   data=data, schema=obj({"summary": STR, "items": arr(obj({
                       "what": STR, "why_it_matters": STR, "what_to_check": STR}))}))
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    names = {v: k for k, v in labels.items()}
    return _out(r, accounts={lab: db.get(User, uid).full_name for lab, uid in names.items()})


# --------------------------------------------------------------------------- 10 wording


class ComposeIn(BaseModel):
    draft: str = Field(min_length=5, max_length=3000)
    purpose: str = Field(default="announcement", pattern="^(announcement|academic_note|official_warning|admin_notice|message)$")
    audience: str = Field(default="students", max_length=60)


@router.post("/compose")
def compose(body: ComposeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Improves the wording of an announcement and gives a version that fits one SMS (70 letters)."""
    if user.role == Role.STUDENT:
        raise forbidden()
    cfg = tenant_settings(db, user)
    system = ("Improve the wording of this university notice: keep every fact, date and name exactly; "
              "make it clear, polite and short; give a title of at most 60 characters. Also give an SMS "
              "version of at most 60 Arabic characters (it is sent through a template that adds the "
              "university's name), without emojis or diacritics.")
    try:
        ai.require(cfg, "staff")
        r = ai.run(db, user, kind="compose", subject=f"user:{user.id}", system=system, data=body.model_dump(),
                   schema=obj({"title": STR, "text": STR, "sms": STR}), effort="low", max_tokens=4000, cache=False)
    except AiError as exc:
        raise _fail(exc) from None
    db.commit()
    sms = r["result"].get("sms", "")
    return _out(r, sms_length=len(sms), sms_fits=len(sms) <= 60)
