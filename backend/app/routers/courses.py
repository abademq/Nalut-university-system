"""Courses, staff assignment, enrollment and schedules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, permissions
from ..db import get_db
from ..deps import (
    client_ip,
    forbidden,
    get_course_for,
    can_teach_course,
    get_current_user,
    is_course_admin,
    not_found,
    require_roles,
    visible_course_ids,
)
from ..models import (
    AssessmentComponent,
    Course,
    CourseStaff,
    Department,
    Enrollment,
    Faculty,
    Role,
    Term,
    User,
)

router = APIRouter(prefix="/api", tags=["courses"])


def course_out(db: Session, c: Course, *, detail: bool = False) -> dict:
    staff = db.execute(
        select(User.id, User.full_name, CourseStaff.role).join(CourseStaff, CourseStaff.user_id == User.id)
        .where(CourseStaff.course_id == c.id)
    ).all()
    out = {
        "id": c.id, "code": c.code, "title": c.title, "credits": c.credits, "faculty_id": c.faculty_id,
        "department_id": c.department_id, "term_id": c.term_id, "schedule": c.schedule or [],
        "staff": [{"id": s.id, "full_name": s.full_name, "role": s.role} for s in staff],
        "students_count": db.scalar(select(func.count(Enrollment.id)).where(
            Enrollment.course_id == c.id, Enrollment.status == "active")),
    }
    if detail:
        out["components"] = [{"id": a.id, "name": a.name, "max_score": a.max_score} for a in db.scalars(
            select(AssessmentComponent).where(AssessmentComponent.course_id == c.id)
            .order_by(AssessmentComponent.position))]
    return out


@router.get("/courses")
def list_courses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = visible_course_ids(db, user)
    rows = db.scalars(select(Course).where(Course.id.in_(ids)).order_by(Course.code)).all() if ids else []
    return [course_out(db, c) for c in rows]


@router.get("/courses/{course_id}")
def get_course(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return course_out(db, get_course_for(db, user, course_id), detail=True)


class SlotIn(BaseModel):
    day: int = Field(ge=0, le=6)
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    room: str = Field(default="", max_length=50)


class ComponentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    max_score: float = Field(gt=0, le=1000)


class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    credits: int = Field(default=3, ge=0, le=20)
    faculty_id: int | None = None
    department_id: int | None = None
    term_id: int | None = None
    schedule: list[SlotIn] = Field(default_factory=list)
    components: list[ComponentIn] = Field(default_factory=list)


def _course_manager(user: User = Depends(require_roles(Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN)),
                    db: Session = Depends(get_db)) -> User:
    permissions.require(db, user, "courses.manage")
    return user


@router.post("/courses")
def create_course(body: CourseIn, request: Request,
                  user: User = Depends(_course_manager),
                  db: Session = Depends(get_db)):
    faculty_id = user.faculty_id if user.role == Role.FACULTY_ADMIN else body.faculty_id
    fac = db.get(Faculty, faculty_id) if faculty_id else None
    if not fac or fac.university_id != user.university_id:
        raise HTTPException(status_code=400, detail="حدد الكلية")
    if body.department_id:
        dep = db.get(Department, body.department_id)
        if not dep or dep.faculty_id != fac.id:
            raise HTTPException(status_code=400, detail="القسم لا يتبع الكلية")
    if body.term_id:
        term = db.get(Term, body.term_id)
        if not term or term.university_id != user.university_id:
            raise HTTPException(status_code=400, detail="الفصل الدراسي غير صحيح")
    c = Course(university_id=user.university_id, faculty_id=fac.id, department_id=body.department_id,
               term_id=body.term_id, code=body.code, title=body.title, credits=body.credits,
               schedule=[s.model_dump() for s in body.schedule])
    db.add(c)
    db.flush()
    for i, comp in enumerate(body.components or [ComponentIn(name="أعمال السنة", max_score=40),
                                                 ComponentIn(name="الامتحان النهائي", max_score=60)]):
        db.add(AssessmentComponent(course_id=c.id, name=comp.name, max_score=comp.max_score, position=i))
    audit.record(db, "course.created", actor=user, target_type="course", target_id=c.id, ip=client_ip(request))
    db.commit()
    return course_out(db, c, detail=True)


class CoursePatch(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=40)
    title: str | None = Field(default=None, max_length=200)
    credits: int | None = Field(default=None, ge=0, le=20)
    department_id: int | None = None
    term_id: int | None = None
    schedule: list[SlotIn] | None = None


@router.patch("/courses/{course_id}")
def patch_course(course_id: int, body: CoursePatch, request: Request, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    c = get_course_for(db, user, course_id)
    data = body.model_dump(exclude_unset=True)
    # the course's teachers may move their own lecture times; everything else is the administration's
    if is_course_admin(user, c):
        permissions.require(db, user, "courses.manage")
    elif set(data) <= {"schedule"} and can_teach_course(db, user, c):
        permissions.require(db, user, "courses.schedule")
    else:
        raise forbidden()
    if data.get("department_id") is not None:
        dep = db.get(Department, data["department_id"])
        if not dep or dep.faculty_id != c.faculty_id:
            raise HTTPException(status_code=400, detail="القسم لا يتبع كلية المقرر")
    if data.get("term_id") is not None:
        term = db.get(Term, data["term_id"])
        if not term or term.university_id != c.university_id:
            raise HTTPException(status_code=400, detail="الفصل الدراسي غير صحيح")
    if "schedule" in data:
        data["schedule"] = [s.model_dump() for s in body.schedule or []]
    for k, v in data.items():
        setattr(c, k, v)
    audit.record(db, "course.updated", actor=user, target_type="course", target_id=c.id,
                 details={"fields": sorted(data)}, ip=client_ip(request))
    db.commit()
    return course_out(db, c, detail=True)


class StaffIn(BaseModel):
    user_id: int
    role: str = Field(default="instructor", pattern="^(instructor|assistant)$")


@router.post("/courses/{course_id}/staff")
def assign_staff(course_id: int, body: StaffIn, request: Request,
                 user: User = Depends(_course_manager),
                 db: Session = Depends(get_db)):
    c = get_course_for(db, user, course_id)
    t = db.get(User, body.user_id)
    if not t or t.university_id != c.university_id or t.role not in Role.INSTRUCTORS:
        raise HTTPException(status_code=400, detail="المستخدم ليس عضو هيئة تدريس")
    if not db.scalar(select(CourseStaff.id).where(CourseStaff.course_id == c.id, CourseStaff.user_id == t.id)):
        db.add(CourseStaff(course_id=c.id, user_id=t.id, role=body.role))
    audit.record(db, "course.staff_assigned", actor=user, target_type="course", target_id=c.id,
                 details={"user_id": t.id, "role": body.role}, ip=client_ip(request))
    db.commit()
    return course_out(db, c)


@router.delete("/courses/{course_id}/staff/{user_id}")
def remove_staff(course_id: int, user_id: int, request: Request,
                 user: User = Depends(_course_manager),
                 db: Session = Depends(get_db)):
    c = get_course_for(db, user, course_id)
    row = db.scalar(select(CourseStaff).where(CourseStaff.course_id == c.id, CourseStaff.user_id == user_id))
    if not row:
        raise not_found()
    db.delete(row)
    audit.record(db, "course.staff_removed", actor=user, target_type="course", target_id=c.id,
                 details={"user_id": user_id}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


class EnrollIn(BaseModel):
    student_codes: list[str] = Field(min_length=1, max_length=1000)


@router.post("/courses/{course_id}/enrollments")
def enroll(course_id: int, body: EnrollIn, request: Request,
           user: User = Depends(_course_manager),
           db: Session = Depends(get_db)):
    c = get_course_for(db, user, course_id)
    added, unknown = [], []
    for code in {s.strip() for s in body.student_codes if s.strip()}:
        st = db.scalar(select(User).where(User.university_id == c.university_id, User.code == code,
                                          User.role == Role.STUDENT))
        if not st:
            unknown.append(code)
            continue
        e = db.scalar(select(Enrollment).where(Enrollment.course_id == c.id, Enrollment.student_id == st.id))
        if e:
            e.status = "active"
        else:
            db.add(Enrollment(course_id=c.id, student_id=st.id))
        added.append(code)
    audit.record(db, "course.enrolled", actor=user, target_type="course", target_id=c.id,
                 details={"added": len(added)}, ip=client_ip(request))
    db.commit()
    return {"added": sorted(added), "unknown": sorted(unknown)}


@router.delete("/courses/{course_id}/enrollments/{student_id}")
def unenroll(course_id: int, student_id: int, request: Request,
             user: User = Depends(_course_manager),
             db: Session = Depends(get_db)):
    c = get_course_for(db, user, course_id)
    e = db.scalar(select(Enrollment).where(Enrollment.course_id == c.id, Enrollment.student_id == student_id))
    if not e:
        raise not_found()
    e.status = "dropped"
    audit.record(db, "course.unenrolled", actor=user, target_type="course", target_id=c.id,
                 details={"student_id": student_id}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/courses/{course_id}/students")
def course_students(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_course_for(db, user, course_id, teach=True)
    rows = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id).where(
        Enrollment.course_id == c.id, Enrollment.status == "active").order_by(User.full_name)).all()
    return [{"id": u.id, "full_name": u.full_name, "code": u.code, "cohort": u.cohort} for u in rows]


@router.get("/me/schedule")
def my_schedule(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (Role.STUDENT, *Role.INSTRUCTORS):
        return []
    ids = visible_course_ids(db, user)
    out = []
    for c in db.scalars(select(Course).where(Course.id.in_(ids))) if ids else []:
        for slot in c.schedule or []:
            out.append({"course_id": c.id, "code": c.code, "title": c.title, **slot})
    return sorted(out, key=lambda s: (s["day"], s["start"]))


class ComponentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    max_score: float | None = Field(default=None, gt=0, le=1000)


def _component(db: Session, user: User, cid: int) -> tuple[AssessmentComponent, Course]:
    from .. import grades

    comp = db.get(AssessmentComponent, cid)
    if not comp:
        raise not_found()
    course = get_course_for(db, user, comp.course_id, teach=True)
    permissions.require(db, user, "courses.components")
    if grades.result_for(db, course.id).status != "draft":
        raise HTTPException(status_code=400, detail="لا يمكن تعديل عناصر التقييم بعد رفع النتائج")
    return comp, course


@router.patch("/components/{cid}")
def patch_component(cid: int, body: ComponentPatch, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from ..models import GradeEntry

    comp, course = _component(db, user, cid)
    if body.max_score is not None:
        top = db.scalar(select(func.max(GradeEntry.score)).where(GradeEntry.component_id == comp.id))
        if top is not None and top > body.max_score:
            raise HTTPException(status_code=400, detail=f"توجد درجات مرصودة أعلى من {body.max_score}")
        comp.max_score = body.max_score
    if body.name:
        comp.name = body.name.strip()
    audit.record(db, "component.updated", actor=user, target_type="course", target_id=course.id,
                 details={"component": comp.id, **body.model_dump(exclude_none=True)}, ip=client_ip(request))
    db.commit()
    return {"id": comp.id, "name": comp.name, "max_score": comp.max_score}


@router.delete("/components/{cid}")
def delete_component(cid: int, request: Request, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    from ..models import GradeEntry

    comp, course = _component(db, user, cid)
    if db.scalar(select(func.count(GradeEntry.id)).where(GradeEntry.component_id == comp.id)):
        raise HTTPException(status_code=400, detail="لا يمكن حذف عنصر عليه درجات مرصودة")
    audit.record(db, "component.deleted", actor=user, target_type="course", target_id=course.id,
                 details={"component": comp.name}, ip=client_ip(request))
    db.delete(comp)
    db.commit()
    return {"ok": True}
