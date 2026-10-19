"""File downloads. Access is decided from what the file is attached to."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files
from ..db import get_db
from ..deps import can_teach_course, client_ip, get_current_user, not_found
from ..models import (
    Assignment,
    ConversationParticipant,
    Course,
    Message,
    ServiceRequest,
    ServiceRequestEvent,
    StoredFile,
    Submission,
    SubmissionFile,
    User,
)
from .requests import can_handle

router = APIRouter(prefix="/api/files", tags=["files"])


def can_read(db: Session, user: User, f: StoredFile) -> bool:
    if f.university_id != user.university_id:
        return False
    if f.purpose == "submission":
        sub = db.scalar(select(Submission).join(SubmissionFile, SubmissionFile.submission_id == Submission.id)
                        .where(SubmissionFile.file_id == f.id))
        if not sub:
            return False
        if sub.student_id == user.id:
            return True
        a = db.get(Assignment, sub.assignment_id)
        return can_teach_course(db, user, db.get(Course, a.course_id))
    if f.purpose == "message":
        m = db.scalar(select(Message).where(Message.file_id == f.id))
        return bool(m and not m.hidden and db.scalar(select(ConversationParticipant.id).where(
            ConversationParticipant.conversation_id == m.conversation_id, ConversationParticipant.user_id == user.id)))
    if f.purpose == "request":
        ev = db.scalar(select(ServiceRequestEvent).where(ServiceRequestEvent.file_id == f.id))
        r = db.get(ServiceRequest, ev.request_id) if ev else None
        return bool(r and (r.requester_id == user.id or can_handle(user, r)))
    # selfies are only served through the attendance review endpoint
    return False


@router.get("/{file_id}")
def download(file_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(StoredFile, file_id)
    if not f or not can_read(db, user, f):
        raise not_found("الملف غير موجود")
    if f.owner_id != user.id:
        audit.record(db, "file.downloaded", actor=user, target_type="file", target_id=f.id, ip=client_ip(request))
        db.commit()
    return files.download_response(f)
