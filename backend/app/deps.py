"""Request dependencies and the authorization rules shared by all routers.

Rules are enforced on the server for every request:

* every query is scoped by the caller's ``university_id`` (tenant isolation);
* faculty admins are further limited to their faculty;
* instructors to the courses they are assigned to;
* students to the courses they are enrolled in and to their own records.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Course, CourseStaff, Enrollment, Faculty, Role, University, User
from .security import decode_token
from .tenancy import effective_settings


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def forbidden(msg: str = "غير مصرح لك بهذا الإجراء") -> HTTPException:
    return HTTPException(status_code=403, detail=msg)


def not_found(msg: str = "غير موجود") -> HTTPException:
    return HTTPException(status_code=404, detail=msg)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="يلزم تسجيل الدخول")
    payload = decode_token(auth[7:].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="انتهت الجلسة، يرجى تسجيل الدخول مجدداً")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="الحساب غير مفعل")
    if user.university_id is not None:
        uni = db.get(University, user.university_id)
        if not uni or not uni.is_active:
            raise HTTPException(status_code=401, detail="المؤسسة غير مفعلة")
    request.state.user = user
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise forbidden()
        return user

    return checker


def tenant_settings(db: Session, user: User) -> dict:
    uni = db.get(University, user.university_id) if user.university_id else None
    fac = db.get(Faculty, user.faculty_id) if user.faculty_id else None
    return effective_settings(uni, fac)


# --------------------------------------------------------------------------- course scope


def is_course_staff(db: Session, user: User, course_id: int) -> bool:
    return db.scalar(
        select(CourseStaff.id).where(CourseStaff.course_id == course_id, CourseStaff.user_id == user.id)
    ) is not None


def is_enrolled(db: Session, user_id: int, course_id: int) -> bool:
    return db.scalar(
        select(Enrollment.id).where(
            Enrollment.course_id == course_id, Enrollment.student_id == user_id, Enrollment.status == "active"
        )
    ) is not None


def is_course_admin(user: User, course: Course) -> bool:
    if user.university_id != course.university_id:
        return False
    if user.role == Role.UNIVERSITY_ADMIN:
        return True
    return user.role == Role.FACULTY_ADMIN and user.faculty_id == course.faculty_id


def can_view_course(db: Session, user: User, course: Course) -> bool:
    if user.university_id != course.university_id:
        return False
    if is_course_admin(user, course):
        return True
    if user.role in Role.INSTRUCTORS:
        return is_course_staff(db, user, course.id)
    if user.role == Role.STUDENT:
        return is_enrolled(db, user.id, course.id)
    return False


def can_teach_course(db: Session, user: User, course: Course) -> bool:
    """Instructors of the course (and its faculty/university admins)."""
    if user.university_id != course.university_id:
        return False
    if is_course_admin(user, course):
        return True
    return user.role in Role.INSTRUCTORS and is_course_staff(db, user, course.id)


def get_course_for(db: Session, user: User, course_id: int, *, teach: bool = False) -> Course:
    course = db.get(Course, course_id)
    # A course of another university is reported as "not found" to avoid leaking its existence.
    if not course or course.university_id != user.university_id:
        raise not_found("المقرر غير موجود")
    allowed = can_teach_course(db, user, course) if teach else can_view_course(db, user, course)
    if not allowed:
        raise forbidden("لا تملك صلاحية الوصول إلى هذا المقرر")
    return course


def visible_course_ids(db: Session, user: User) -> list[int]:
    q = select(Course.id).where(Course.university_id == user.university_id)
    if user.role == Role.UNIVERSITY_ADMIN:
        pass
    elif user.role == Role.FACULTY_ADMIN:
        q = q.where(Course.faculty_id == user.faculty_id)
    elif user.role in Role.INSTRUCTORS:
        q = q.join(CourseStaff, CourseStaff.course_id == Course.id).where(CourseStaff.user_id == user.id)
    elif user.role == Role.STUDENT:
        q = q.join(Enrollment, Enrollment.course_id == Course.id).where(
            Enrollment.student_id == user.id, Enrollment.status == "active"
        )
    else:
        return []
    return list(db.scalars(q))


# --------------------------------------------------------------------------- user scope

# which roles each administrative role may create / manage
MANAGEABLE_ROLES = {
    Role.PLATFORM_ADMIN: {Role.UNIVERSITY_ADMIN},
    Role.UNIVERSITY_ADMIN: {Role.FACULTY_ADMIN, Role.STAFF, Role.TEACHER, Role.ASSISTANT, Role.STUDENT},
    Role.FACULTY_ADMIN: {Role.STAFF, Role.TEACHER, Role.ASSISTANT, Role.STUDENT},
}


def can_manage_user(actor: User, target: User) -> bool:
    if actor.id == target.id:
        return False  # nobody edits their own role/status through admin endpoints
    if target.role not in MANAGEABLE_ROLES.get(actor.role, set()):
        return False
    if actor.role == Role.PLATFORM_ADMIN:
        return True
    if actor.university_id != target.university_id:
        return False
    if actor.role == Role.FACULTY_ADMIN:
        return target.faculty_id == actor.faculty_id
    return True


def can_view_user(db: Session, actor: User, target: User) -> bool:
    if actor.id == target.id:
        return True
    if actor.university_id != target.university_id:
        return False
    if actor.role == Role.UNIVERSITY_ADMIN:
        return True
    if actor.role == Role.FACULTY_ADMIN:
        return target.faculty_id == actor.faculty_id
    if actor.role in Role.INSTRUCTORS and target.role == Role.STUDENT:
        # students enrolled in one of the instructor's courses
        q = (
            select(Enrollment.id)
            .join(CourseStaff, CourseStaff.course_id == Enrollment.course_id)
            .where(CourseStaff.user_id == actor.id, Enrollment.student_id == target.id)
        )
        return db.scalar(q.limit(1)) is not None
    if actor.role == Role.STAFF:
        # staff see the people they need for their office's work, within their faculty
        return actor.faculty_id is None or target.faculty_id == actor.faculty_id
    return False


def public_user(u: User) -> dict:
    return {"id": u.id, "full_name": u.full_name, "role": u.role, "code": u.code}
