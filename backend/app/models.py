"""Database models.

Every tenant-owned table carries ``university_id``; all queries are scoped by the
caller's university so data of different universities never mixes.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime as DateTime, utcnow


class Role:
    PLATFORM_ADMIN = "platform_admin"
    UNIVERSITY_ADMIN = "university_admin"
    FACULTY_ADMIN = "faculty_admin"
    STAFF = "staff"
    TEACHER = "teacher"
    ASSISTANT = "assistant"
    STUDENT = "student"

    ALL = [PLATFORM_ADMIN, UNIVERSITY_ADMIN, FACULTY_ADMIN, STAFF, TEACHER, ASSISTANT, STUDENT]
    ADMINS = {PLATFORM_ADMIN, UNIVERSITY_ADMIN, FACULTY_ADMIN}
    INSTRUCTORS = {TEACHER, ASSISTANT}
    EMPLOYEES = {UNIVERSITY_ADMIN, FACULTY_ADMIN, STAFF, TEACHER, ASSISTANT}


# --------------------------------------------------------------------------- organisation


class University(Base):
    __tablename__ = "universities"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Faculty(Base):
    __tablename__ = "faculties"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("university_id", "code"),)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculties.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("faculty_id", "code"),)


class Term(Base):
    __tablename__ = "terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- identity


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int | None] = mapped_column(ForeignKey("universities.id"), index=True)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculties.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    role: Mapped[str] = mapped_column(String(30), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # student number or employee number
    code: Mapped[str | None] = mapped_column(String(40), index=True)
    cohort: Mapped[str | None] = mapped_column(String(20))  # e.g. admission year
    office: Mapped[str | None] = mapped_column(String(40))  # staff office, e.g. registrar
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(300))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    notification_prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("university_id", "code"),)


class AuthSession(Base):
    """Refresh-token sessions. Only a SHA-256 of the token is stored."""

    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(60))


class NotificationTopic(Base):
    """What a notification is about (see notifications.TOPICS), for the mutes below."""

    __tablename__ = "notification_topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"), unique=True)
    topic: Mapped[str] = mapped_column(String(40))


class NotificationMute(Base):
    """A notification topic a user chose not to receive (only where the administration allows it)."""

    __tablename__ = "notification_mutes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("user_id", "topic"),)


class SessionRotation(Base):
    """Which session replaced a rotated refresh token, and when.

    A phone on a weak network may send its refresh token, lose the reply and retry with the same
    token. Within a short grace period, from the same device, that retry is a lost reply rather
    than a stolen token, and must not sign the user out everywhere."""

    __tablename__ = "session_rotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("auth_sessions.id"), unique=True)
    successor_id: Mapped[int] = mapped_column(ForeignKey("auth_sessions.id"))
    rotated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class DeviceToken(Base):
    """Push notification tokens (FCM / APNs) registered by mobile apps."""

    __tablename__ = "device_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    token: Mapped[str] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Append-only audit trail. Each row is chained to the previous one by hash."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int | None] = mapped_column(Integer, index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(50))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


# --------------------------------------------------------------------------- courses


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculties.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    term_id: Mapped[int | None] = mapped_column(ForeignKey("terms.id"))
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    credits: Mapped[int] = mapped_column(Integer, default=3)
    # [{"day": 0-6 (0=Saturday), "start": "08:00", "end": "09:30", "room": "A101"}]
    schedule: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CourseStaff(Base):
    __tablename__ = "course_staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="instructor")  # instructor | assistant
    __table_args__ = (UniqueConstraint("course_id", "user_id"),)


class Enrollment(Base):
    __tablename__ = "enrollments"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("course_id", "student_id"),)


# --------------------------------------------------------------------------- files


class StoredFile(Base):
    __tablename__ = "stored_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int | None] = mapped_column(Integer, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))  # submission | message | request | selfie
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(100), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|clean|rejected
    scan_detail: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


# --------------------------------------------------------------------------- assignments


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="homework")  # homework|research|project|quiz
    open_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    allow_late: Mapped[bool] = mapped_column(Boolean, default=True)
    max_score: Mapped[float] = mapped_column(Float, default=10)
    allowed_extensions: Mapped[list] = mapped_column(JSON, default=list)
    max_file_mb: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(20), default="published")  # draft|published|archived
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress|submitted|reviewed
    note: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float)
    feedback: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime)
    grade_released: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"),)


class SubmissionFile(Base):
    __tablename__ = "submission_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    file: Mapped[StoredFile] = relationship(lazy="joined")


class SubmissionEvent(Base):
    __tablename__ = "submission_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- grades / results


class AssessmentComponent(Base):
    __tablename__ = "assessment_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    max_score: Mapped[float] = mapped_column(Float)
    position: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("course_id", "name"),)


class GradeEntry(Base):
    __tablename__ = "grade_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("assessment_components.id"))
    score: Mapped[float | None] = mapped_column(Float)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("student_id", "component_id"),)


class GradeChange(Base):
    __tablename__ = "grade_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    component_id: Mapped[int] = mapped_column(ForeignKey("assessment_components.id"))
    old_score: Mapped[float | None] = mapped_column(Float)
    new_score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual|import
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CourseResult(Base):
    """Approval workflow for official course results: draft -> submitted -> approved -> published."""

    __tablename__ = "course_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(500))


class GradeImport(Base):
    __tablename__ = "grade_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="preview")  # preview|committed|discarded
    rows: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- notifications


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # announcement | academic_note | official_warning | admin_notice | system
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(20), default="normal")  # normal|important|urgent
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # user | users | course | department | faculty | university | cohort
    target_type: Mapped[str] = mapped_column(String(20))
    target_ids: Mapped[list] = mapped_column(JSON, default=list)
    audience: Mapped[str] = mapped_column(String(20), default="students")  # students|staff|all
    channels: Mapped[list] = mapped_column(JSON, default=list)  # inapp, push, sms
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    link: Mapped[str | None] = mapped_column(String(300))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|sent|cancelled
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    recipients_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    push_status: Mapped[str | None] = mapped_column(String(20))  # sent|failed|skipped
    sms_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notification: Mapped[Notification] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("notification_id", "user_id"),)


# --------------------------------------------------------------------------- attendance


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculties.id"))
    kind: Mapped[str] = mapped_column(String(20), default="course")  # course | staff
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    radius_m: Mapped[int] = mapped_column(Integer, default=150)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    late_after_minutes: Mapped[int] = mapped_column(Integer, default=15)
    rotation_seconds: Mapped[int] = mapped_column(Integer, default=15)
    risk_level: Mapped[str] = mapped_column(String(20), default="normal")  # normal | high (exam)
    require_location: Mapped[bool] = mapped_column(Boolean, default=False)
    require_selfie: Mapped[bool] = mapped_column(Boolean, default=False)
    secret: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    absences_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(Integer, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # present | late | absent | excused | pending_review | rejected
    status: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(20))  # qr | manual | rfid | nfc | system
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    device_id: Mapped[str | None] = mapped_column(String(100))
    ip: Mapped[str | None] = mapped_column(String(60))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    # status at creation; later changes only through AttendanceChange rows
    initial_status: Mapped[str] = mapped_column(String(20))
    # status the record would have had if not flagged (used when a reviewer approves)
    provisional_status: Mapped[str | None] = mapped_column(String(20))
    selfie_file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id"))
    face_check: Mapped[str | None] = mapped_column(String(30))  # not_configured|match|no_match|...
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)


class AttendanceNonce(Base):
    """Single-use request ids that stop the same check-in request being replayed."""

    __tablename__ = "attendance_nonces"
    id: Mapped[int] = mapped_column(primary_key=True)
    nonce: Mapped[str] = mapped_column(String(80), unique=True)
    user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AttendanceChange(Base):
    __tablename__ = "attendance_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("attendance_records.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None = automatic rule
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserDevice(Base):
    """Devices a user has checked in from (random per-install id, not hardware ids)."""

    __tablename__ = "user_devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "device_id"),)


class AttendanceAlert(Base):
    """Threshold alerts already sent, so the same level is not re-sent."""

    __tablename__ = "attendance_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    level: Mapped[str] = mapped_column(String(20))  # warning | limit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("course_id", "user_id", "level"),)


# --------------------------------------------------------------------------- messaging


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="direct")  # direct | course | request
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("service_requests.id"))
    subject: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id"))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MessageReport(Base):
    __tablename__ = "message_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(Integer, index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | dismissed | actioned
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- service requests


class ServiceRequest(Base):
    """Administrative transactions (certificates, excuses, ...)."""

    __tablename__ = "service_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculties.id"))
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    office: Mapped[str] = mapped_column(String(40))  # office responsible, e.g. registrar
    subject: Mapped[str] = mapped_column(String(200))
    details: Mapped[str] = mapped_column(Text, default="")
    # submitted | in_review | needs_documents | forwarded | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="submitted")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ServiceRequestEvent(Base):
    __tablename__ = "service_request_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("service_requests.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


Index("ix_attendance_records_session_device", AttendanceRecord.session_id, AttendanceRecord.device_id)


# --------------------------------------------------------------------------- pinned announcements


class Banner(Base):
    """Announcement pinned at the top of the app/dashboard between starts_at and ends_at."""

    __tablename__ = "banners"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculties.id"))  # None = whole university
    audience: Mapped[str] = mapped_column(String(20), default="all")  # all | students | staff
    level: Mapped[str] = mapped_column(String(20), default="info")  # info | important | urgent
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- student archive


class StudentRecord(Base):
    """Personal file of a student kept by the faculty / registrar (archive)."""

    __tablename__ = "student_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    national_id_enc: Mapped[str | None] = mapped_column(String(300))  # encrypted at rest
    birth_date: Mapped[date | None] = mapped_column(Date)
    birth_place: Mapped[str | None] = mapped_column(String(100))
    nationality: Mapped[str | None] = mapped_column(String(60))
    gender: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(String(300))
    guardian_name: Mapped[str | None] = mapped_column(String(200))
    guardian_relation: Mapped[str | None] = mapped_column(String(50))
    guardian_phone: Mapped[str | None] = mapped_column(String(30))
    high_school: Mapped[str | None] = mapped_column(String(200))
    high_school_year: Mapped[str | None] = mapped_column(String(10))
    high_school_score: Mapped[float | None] = mapped_column(Float)
    admission_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|suspended|graduated|withdrawn
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StudentDocument(Base):
    __tablename__ = "student_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(500))
    file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(String(300))


# --------------------------------------------------------------------------- two-factor authentication


class MfaPreference(Base):
    """How a user proves the second factor, and whether an administrator made it mandatory.

    A separate table so existing databases need no column changes (tables are created on start).
    """

    __tablename__ = "mfa_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    method: Mapped[str] = mapped_column(String(10), default="totp")  # totp | sms
    forced: Mapped[bool] = mapped_column(Boolean, default=False)  # required for this account by an admin
    forced_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OtpChallenge(Base):
    """A one-time code sent by SMS. Only a keyed hash of the code is stored."""

    __tablename__ = "otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # login | verify
    code_hash: Mapped[str] = mapped_column(String(100))  # "<salt>$<hmac-sha256 hex>"
    provider_ref: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- timetables and posters


class Publication(Base):
    """A lecture timetable (image/PDF) or an image announcement, shown in the app for a period.

    Targeting narrows from the whole university to a faculty, a department and a cohort.
    """

    __tablename__ = "publications"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # schedule | poster
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    audience: Mapped[str] = mapped_column(String(20), default="all")  # all | students | staff
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculties.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    cohort: Mapped[str | None] = mapped_column(String(40))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- app launch screen


class AppAsset(Base):
    """A small image the mobile app shows before sign-in (the launch screen picture).

    Kept in the database (not the file store) because it is public and fetched by the app
    before anyone signs in; set by the platform administrator only.
    """

    __tablename__ = "app_assets"
    __table_args__ = (UniqueConstraint("university_id", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # splash
    content_type: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    version: Mapped[str] = mapped_column(String(16))  # first 16 hex chars of the SHA-256
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- permission groups


class PermissionGroup(Base):
    """A named set of capabilities given to chosen people, on top of what their role holds."""

    __tablename__ = "permission_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PermissionGroupMember(Base):
    __tablename__ = "permission_group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("permission_groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


# --------------------------------------------------------------------------- staff and faculty files


class PersonnelRecord(Base):
    """Employment file of a staff member or a faculty member (teacher / assistant).

    The fields live in ``data`` (whitelisted in routers/personnel.py); the national number is
    encrypted at rest in its own column.
    """

    __tablename__ = "personnel_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    national_id_enc: Mapped[str | None] = mapped_column(String(300))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonnelDocument(Base):
    __tablename__ = "personnel_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(ForeignKey("universities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(500))
    file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(String(300))
