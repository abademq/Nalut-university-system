"""Study programmes (التخصصات): plans by semester, students placed in them, and each student's
progress through their plan (what is left, what comes next, what must be passed this term)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, permissions, registration
from ..db import get_db
from ..deps import client_ip, forbidden, get_current_user, not_found, tenant_settings
from ..models import (
    CoursePrerequisite,
    Department,
    Faculty,
    Program,
    ProgramCourse,
    Role,
    StudentProgram,
    User,
)

router = APIRouter(prefix="/api", tags=["programs"])
KEY = "programs.manage"


def _out(db: Session, p: Program, *, detail: bool = False) -> dict:
    out = {"id": p.id, "name": p.name, "code": p.code, "faculty_id": p.faculty_id, "department_id": p.department_id,
           "semesters": p.semesters,
           "students": db.scalar(select(func.count(StudentProgram.id)).where(StudentProgram.program_id == p.id)),
           "credits": db.scalar(select(func.coalesce(func.sum(ProgramCourse.credits), 0)).where(
               ProgramCourse.program_id == p.id, ProgramCourse.required.is_(True)))}
    if detail:
        rows = db.scalars(select(ProgramCourse).where(ProgramCourse.program_id == p.id)
                          .order_by(ProgramCourse.semester, ProgramCourse.code)).all()
        req: dict[str, list[str]] = {}
        for a, b in db.execute(select(CoursePrerequisite.course_code, CoursePrerequisite.required_code).where(
                CoursePrerequisite.faculty_id == p.faculty_id, CoursePrerequisite.course_code.in_([r.code for r in rows] or ["-"]))):
            req.setdefault(a, []).append(b)
        out["courses"] = [{"semester": r.semester, "code": r.code, "title": r.title, "credits": r.credits,
                           "required": r.required, "prerequisites": sorted(req.get(r.code, []))} for r in rows]
    return out


def _program(db: Session, user: User, pid: int, *, manage: bool = False) -> Program:
    p = db.get(Program, pid)
    if not p or p.university_id != user.university_id:
        raise not_found("التخصص غير موجود")
    if manage:
        permissions.require_scope(db, user, KEY, p.faculty_id)
    return p


@router.get("/programs")
def list_programs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.STUDENT:
        raise forbidden()
    stmt = select(Program).where(Program.university_id == user.university_id)
    if user.faculty_id and user.role != Role.UNIVERSITY_ADMIN:
        stmt = stmt.where(Program.faculty_id == user.faculty_id)
    return [_out(db, p) for p in db.scalars(stmt.order_by(Program.name))]


@router.get("/programs/{pid}")
def get_program(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.STUDENT:
        raise forbidden()
    return _out(db, _program(db, user, pid), detail=True)


class ProgramIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=40)
    faculty_id: int | None = None
    department_id: int | None = None
    semesters: int = Field(default=8, ge=1, le=14)


@router.post("/programs")
def create_program(body: ProgramIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    sc = permissions.require_scope(db, user, KEY)
    faculty_id = body.faculty_id if sc == permissions.ALL else sc
    fac = db.get(Faculty, faculty_id) if faculty_id else None
    if not fac or fac.university_id != user.university_id:
        raise HTTPException(status_code=400, detail="حدد الكلية")
    if body.department_id:
        dep = db.get(Department, body.department_id)
        if not dep or dep.faculty_id != fac.id:
            raise HTTPException(status_code=400, detail="القسم لا يتبع الكلية")
    if db.scalar(select(Program.id).where(Program.faculty_id == fac.id, Program.code == body.code.strip())):
        raise HTTPException(status_code=400, detail="يوجد تخصص بهذا الرمز في الكلية")
    p = Program(university_id=user.university_id, faculty_id=fac.id, department_id=body.department_id,
                name=body.name.strip(), code=body.code.strip(), semesters=body.semesters)
    db.add(p)
    db.flush()
    audit.record(db, "program.created", actor=user, target_type="program", target_id=p.id,
                 details={"name": p.name}, ip=client_ip(request))
    db.commit()
    return _out(db, p, detail=True)


class ProgramPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    department_id: int | None = None
    semesters: int | None = Field(default=None, ge=1, le=14)


@router.patch("/programs/{pid}")
def patch_program(pid: int, body: ProgramPatch, request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    p = _program(db, user, pid, manage=True)
    data = body.model_dump(exclude_unset=True)
    if data.get("department_id") is not None:
        dep = db.get(Department, data["department_id"])
        if not dep or dep.faculty_id != p.faculty_id:
            raise HTTPException(status_code=400, detail="القسم لا يتبع كلية التخصص")
    for k, v in data.items():
        setattr(p, k, v)
    audit.record(db, "program.updated", actor=user, target_type="program", target_id=p.id,
                 details={"fields": sorted(data)}, ip=client_ip(request))
    db.commit()
    return _out(db, p, detail=True)


@router.delete("/programs/{pid}")
def delete_program(pid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _program(db, user, pid, manage=True)
    if db.scalar(select(StudentProgram.id).where(StudentProgram.program_id == p.id).limit(1)):
        raise HTTPException(status_code=400, detail="في التخصص طلبة؛ انقلهم إلى تخصص آخر أولاً")
    for r in db.scalars(select(ProgramCourse).where(ProgramCourse.program_id == p.id)):
        db.delete(r)
    audit.record(db, "program.deleted", actor=user, target_type="program", target_id=p.id,
                 details={"name": p.name}, ip=client_ip(request))
    db.delete(p)
    db.commit()
    return {"ok": True}


class PlanCourseIn(BaseModel):
    semester: int = Field(ge=1, le=14)
    code: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    credits: int = Field(default=3, ge=0, le=20)
    required: bool = True
    prerequisites: list[str] = Field(default_factory=list, max_length=10)


class PlanIn(BaseModel):
    courses: list[PlanCourseIn] = Field(max_length=200)


@router.put("/programs/{pid}/courses")
def save_plan(pid: int, body: PlanIn, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Replaces the plan. Each course's prerequisites (codes in the plan) become the faculty's
    registration rule for that code."""
    p = _program(db, user, pid, manage=True)
    courses = [c.model_copy(update={"code": c.code.strip().upper(),
                                    "prerequisites": sorted({x.strip().upper() for x in c.prerequisites if x.strip()})})
               for c in body.courses]
    codes = [c.code for c in courses]
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=400, detail="رمز مقرر مكرر في الخطة")
    sem_of = {c.code: c.semester for c in courses}
    for c in courses:
        if c.semester > p.semesters:
            raise HTTPException(status_code=400, detail=f"{c.code}: الفصل {c.semester} أكبر من عدد فصول التخصص")
        for r in c.prerequisites:
            if r == c.code:
                raise HTTPException(status_code=400, detail=f"{c.code}: لا يكون المقرر متطلباً لنفسه")
            if r not in sem_of:
                raise HTTPException(status_code=400, detail=f"{c.code}: المتطلب {r} ليس في الخطة")
            if sem_of[r] >= c.semester:
                raise HTTPException(status_code=400, detail=f"{c.code}: المتطلب {r} يجب أن يكون في فصل سابق")
    for r in db.scalars(select(ProgramCourse).where(ProgramCourse.program_id == p.id)):
        db.delete(r)
    for row in db.scalars(select(CoursePrerequisite).where(CoursePrerequisite.faculty_id == p.faculty_id,
                                                           CoursePrerequisite.course_code.in_(codes or ["-"]))):
        db.delete(row)
    db.flush()
    for c in courses:
        db.add(ProgramCourse(program_id=p.id, semester=c.semester, code=c.code, title=c.title.strip(),
                             credits=c.credits, required=c.required))
        for r in c.prerequisites:
            db.add(CoursePrerequisite(university_id=p.university_id, faculty_id=p.faculty_id, course_code=c.code,
                                      required_code=r))
    audit.record(db, "program.plan_saved", actor=user, target_type="program", target_id=p.id,
                 details={"courses": len(courses)}, ip=client_ip(request))
    db.commit()
    return _out(db, p, detail=True)


class PlaceIn(BaseModel):
    student_codes: list[str] = Field(min_length=1, max_length=2000)


@router.post("/programs/{pid}/students")
def place_students(pid: int, body: PlaceIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    p = _program(db, user, pid, manage=True)
    placed, unknown = [], []
    for code in sorted({c.strip() for c in body.student_codes if c.strip()}):
        st = db.scalar(select(User).where(User.university_id == p.university_id, User.code == code,
                                          User.role == Role.STUDENT))
        if not st or st.faculty_id != p.faculty_id:
            unknown.append(code)
            continue
        row = db.scalar(select(StudentProgram).where(StudentProgram.student_id == st.id))
        if row:
            row.program_id = p.id
        else:
            db.add(StudentProgram(student_id=st.id, program_id=p.id))
        placed.append(code)
    audit.record(db, "program.students_placed", actor=user, target_type="program", target_id=p.id,
                 details={"placed": len(placed)}, ip=client_ip(request))
    db.commit()
    return {"placed": placed, "unknown": unknown}


@router.get("/me/plan")
def my_plan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The student's study plan and where they stand in it."""
    if user.role != Role.STUDENT:
        raise forbidden()
    out = registration.plan_progress(db, user, tenant_settings(db, user))
    db.commit()
    return out or {"program": None}


@router.get("/students/{sid}/plan")
def student_plan(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .reports import _can_see_person

    st = db.get(User, sid)
    if not st or st.role != Role.STUDENT or not _can_see_person(db, user, st):
        raise forbidden()
    out = registration.plan_progress(db, st, tenant_settings(db, st))
    db.commit()
    return out or {"program": None}
