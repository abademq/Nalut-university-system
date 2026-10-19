"""Background jobs: scheduled notifications, due reminders, auto-closing attendance
sessions, and retention clean-up.

Runs as a thread inside the API process by default (RUN_WORKER=true). For several
API instances, disable it there and run one dedicated worker::

    python -m app.worker
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import delete, select

from . import attendance, files, notifications
from .db import SessionLocal, utcnow
from .models import (
    Assignment,
    AttendanceNonce,
    AttendanceSession,
    Course,
    Enrollment,
    StoredFile,
    Submission,
    University,
)
from .tenancy import effective_settings

log = logging.getLogger("nus.worker")


def send_due_reminders(db) -> int:
    count = 0
    now = utcnow()
    for a in db.scalars(select(Assignment).where(Assignment.status == "published", Assignment.reminder_sent.is_(False),
                                                 Assignment.due_at > now)):
        hours = effective_settings(db.get(University, a.university_id))["notifications"]["due_reminder_hours"]
        if a.due_at - now > timedelta(hours=hours):
            continue
        done = set(db.scalars(select(Submission.student_id).where(
            Submission.assignment_id == a.id, Submission.status.in_(["submitted", "reviewed"]))))
        students = [s for s in db.scalars(select(Enrollment.student_id).where(
            Enrollment.course_id == a.course_id, Enrollment.status == "active")) if s not in done]
        course = db.get(Course, a.course_id)
        notifications.notify_users(db, a.university_id, students, f"اقترب موعد التسليم: {a.title}",
                                   f"مقرر {course.title} — آخر موعد {a.due_at:%Y-%m-%d %H:%M} UTC",
                                   priority="important", course_id=course.id, link=f"#/assignments/{a.id}")
        a.reminder_sent = True
        count += 1
    return count


def close_expired_sessions(db) -> int:
    count = 0
    for s in db.scalars(select(AttendanceSession).where(AttendanceSession.status == "open",
                                                        AttendanceSession.ends_at < utcnow())):
        attendance.close_session(db, s)
        count += 1
    return count


def purge_expired_files(db) -> int:
    count = 0
    for f in db.scalars(select(StoredFile).where(StoredFile.delete_after.is_not(None),
                                                 StoredFile.delete_after < utcnow(), StoredFile.deleted_at.is_(None))):
        files.delete_content(f)
        f.deleted_at = utcnow()
        count += 1
    db.execute(delete(AttendanceNonce).where(AttendanceNonce.created_at < utcnow() - timedelta(days=2)))
    return count


_wake = threading.Event()


def kick() -> None:
    """Ask the background loop to run now (e.g. push notifications were queued)."""
    _wake.set()


def run_once() -> dict:
    out = {}
    for name, job in (("push", notifications.send_pending_pushes),
                      ("notifications", notifications.dispatch_due), ("reminders", send_due_reminders),
                      ("sessions", close_expired_sessions), ("purge", purge_expired_files)):
        db = SessionLocal()
        try:
            out[name] = job(db)
            db.commit()
        except Exception:  # noqa: BLE001 - one failing job must not stop the others
            db.rollback()
            log.exception("job %s failed", name)
        finally:
            db.close()
    return out


def _loop(interval: int, stop: threading.Event) -> None:
    while not stop.is_set():
        if _wake.wait(interval):
            _wake.clear()
            time.sleep(1)  # let the request that queued the work commit first
        if not stop.is_set():
            run_once()


def start_background(interval: int) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(interval, stop), daemon=True, name="nus-worker").start()
    return stop


if __name__ == "__main__":  # pragma: no cover
    from .config import settings

    logging.basicConfig(level=logging.INFO)
    while True:
        log.info("worker run: %s", run_once())
        time.sleep(settings.worker_interval_seconds)
