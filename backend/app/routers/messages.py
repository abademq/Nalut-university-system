"""Internal messaging with policy-based contact rules and abuse reporting."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, files, notifications, permissions
from ..db import get_db, utcnow
from ..deps import client_ip, forbidden, get_current_user, not_found, tenant_settings
from ..models import (
    Conversation,
    ConversationParticipant,
    CourseStaff,
    Enrollment,
    Message,
    MessageReport,
    Role,
    StoredFile,
    User,
)
from ..security import limiter

router = APIRouter(prefix="/api", tags=["messages"])


def _shared_course(db: Session, student_id: int, staff_id: int, course_id: int | None = None) -> bool:
    q = select(Enrollment.id).join(CourseStaff, CourseStaff.course_id == Enrollment.course_id).where(
        Enrollment.student_id == student_id, Enrollment.status == "active", CourseStaff.user_id == staff_id)
    if course_id:
        q = q.where(Enrollment.course_id == course_id)
    return db.scalar(q.limit(1)) is not None


def can_message(db: Session, sender: User, recipient: User, course_id: int | None = None) -> bool:
    if sender.id == recipient.id or sender.university_id != recipient.university_id or not recipient.is_active:
        return False
    s, r = sender.role, recipient.role
    if s == Role.STUDENT:
        # institution policy (messaging.student_can_message): the teaching staff of their own
        # courses; or also their faculty's staff and administration; or nobody
        rule = tenant_settings(db, sender)["messaging"].get("student_can_message", "course_staff")
        if rule == "none":
            return False
        if r in Role.INSTRUCTORS and _shared_course(db, sender.id, recipient.id, course_id):
            return True
        return rule == "faculty" and r in (Role.STAFF, Role.FACULTY_ADMIN) and recipient.faculty_id == sender.faculty_id
    if s in Role.INSTRUCTORS:
        if r == Role.STUDENT:
            return _shared_course(db, recipient.id, sender.id, course_id)
        return r in Role.EMPLOYEES and (recipient.faculty_id in (None, sender.faculty_id))
    if s == Role.STAFF:
        if r == Role.STUDENT:
            return sender.faculty_id is None or recipient.faculty_id == sender.faculty_id
        return r in Role.EMPLOYEES
    if s == Role.FACULTY_ADMIN:
        return recipient.faculty_id == sender.faculty_id or r in Role.EMPLOYEES
    return s == Role.UNIVERSITY_ADMIN


def _participant(db: Session, user: User, cid: int) -> Conversation:
    conv = db.get(Conversation, cid)
    if not conv or conv.university_id != user.university_id:
        raise not_found()
    if not db.scalar(select(ConversationParticipant.id).where(ConversationParticipant.conversation_id == cid,
                                                             ConversationParticipant.user_id == user.id)):
        raise not_found()
    return conv


@router.get("/contacts")
def contacts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """People the user may start a conversation with (bounded list for the picker)."""
    if user.role == Role.STUDENT:
        rows = db.execute(select(User, CourseStaff.course_id).join(CourseStaff, CourseStaff.user_id == User.id).join(
            Enrollment, Enrollment.course_id == CourseStaff.course_id).where(
            Enrollment.student_id == user.id, Enrollment.status == "active")).all()
    elif user.role in Role.INSTRUCTORS:
        rows = db.execute(select(User, Enrollment.course_id).join(Enrollment, Enrollment.student_id == User.id).join(
            CourseStaff, CourseStaff.course_id == Enrollment.course_id).where(
            CourseStaff.user_id == user.id, Enrollment.status == "active")).all()
        rows += [(u, None) for u in db.scalars(select(User).where(
            User.university_id == user.university_id, User.role.in_([Role.FACULTY_ADMIN, Role.STAFF]),
            User.faculty_id == user.faculty_id))]
    else:
        stmt = select(User).where(User.university_id == user.university_id, User.id != user.id, User.is_active.is_(True))
        if user.role in (Role.FACULTY_ADMIN, Role.STAFF) and user.faculty_id:
            stmt = stmt.where((User.faculty_id == user.faculty_id) | User.role.in_(list(Role.EMPLOYEES)))
        rows = [(u, None) for u in db.scalars(stmt.order_by(User.full_name).limit(500))]
    seen = {}
    for u, course_id in rows:
        item = seen.setdefault(u.id, {"id": u.id, "full_name": u.full_name, "role": u.role, "code": u.code,
                                      "course_ids": []})
        if course_id and course_id not in item["course_ids"]:
            item["course_ids"].append(course_id)
    return sorted(seen.values(), key=lambda x: x["full_name"])


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Conversation, ConversationParticipant.last_read_at).join(
        ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id).where(
        ConversationParticipant.user_id == user.id).order_by(Conversation.last_message_at.desc()).limit(100)).all()
    out = []
    for conv, last_read in rows:
        others = db.scalars(select(User).join(ConversationParticipant, ConversationParticipant.user_id == User.id)
                            .where(ConversationParticipant.conversation_id == conv.id, User.id != user.id)).all()
        unread_q = select(func.count(Message.id)).where(Message.conversation_id == conv.id,
                                                        Message.sender_id != user.id)
        if last_read:
            unread_q = unread_q.where(Message.created_at > last_read)
        out.append({"id": conv.id, "subject": conv.subject, "kind": conv.kind, "course_id": conv.course_id,
                    "last_message_at": conv.last_message_at, "unread": db.scalar(unread_q),
                    "participants": [{"id": o.id, "full_name": o.full_name, "role": o.role} for o in others]})
    return out


class ConversationIn(BaseModel):
    recipient_ids: list[int] = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    course_id: int | None = None


@router.post("/conversations")
def start_conversation(body: ConversationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not limiter.hit(f"conv:{user.id}", 10, 300):
        raise HTTPException(status_code=429, detail="عدد كبير من المحادثات الجديدة، حاول لاحقاً")
    if user.role == Role.STUDENT and len(body.recipient_ids) > 3:
        raise forbidden("لا يمكن للطالب إرسال رسائل جماعية")
    recipients = []
    for rid in set(body.recipient_ids):
        r = db.get(User, rid)
        if not r or not can_message(db, user, r, body.course_id):
            raise forbidden("لا تسمح سياسة المؤسسة بمراسلة هذا المستخدم")
        recipients.append(r)
    conv = Conversation(university_id=user.university_id, kind="course" if body.course_id else "direct",
                        course_id=body.course_id, subject=body.subject, created_by=user.id)
    db.add(conv)
    db.flush()
    now = utcnow()
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=user.id, last_read_at=now))
    for r in recipients:
        db.add(ConversationParticipant(conversation_id=conv.id, user_id=r.id))
    db.add(Message(conversation_id=conv.id, sender_id=user.id, body=body.body, created_at=now))
    conv.last_message_at = now
    notifications.notify_users(db, user.university_id, [r.id for r in recipients], f"رسالة جديدة من {user.full_name}",
                               body.subject, category="system", link=f"#/messages/{conv.id}")
    db.commit()
    return {"id": conv.id}


@router.get("/conversations/{cid}/messages")
def get_messages(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _participant(db, user, cid)
    msgs = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({m.sender_id for m in msgs} or {-1})))}
    part = db.scalar(select(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id,
                                                          ConversationParticipant.user_id == user.id))
    part.last_read_at = utcnow()
    db.commit()
    out = []
    for m in msgs:
        f = db.get(StoredFile, m.file_id) if m.file_id else None
        out.append({"id": m.id, "sender_id": m.sender_id, "sender": names.get(m.sender_id), "mine": m.sender_id == user.id,
                    "body": "[أُخفيت هذه الرسالة بعد مراجعة بلاغ]" if m.hidden else m.body,
                    "file": files.file_info(f) if f and not m.hidden else None, "created_at": m.created_at})
    return {"id": conv.id, "subject": conv.subject, "messages": out}


@router.post("/conversations/{cid}/messages")
async def post_message(cid: int, body: str = Form("", max_length=5000),
                       upload: UploadFile | None = File(None), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    conv = _participant(db, user, cid)
    body = body.strip()
    if not body and upload is None:  # a file alone is a message too
        raise HTTPException(status_code=400, detail="اكتب رسالة أو أرفق ملفاً")
    if not limiter.hit(f"msg:{user.id}", 30, 60):
        raise HTTPException(status_code=429, detail="عدد كبير من الرسائل، حاول بعد قليل")
    others = db.scalars(select(User).join(ConversationParticipant, ConversationParticipant.user_id == User.id).where(
        ConversationParticipant.conversation_id == conv.id, User.id != user.id)).all()
    # re-check policy on every message (e.g. the enrolment may have ended)
    if not any(can_message(db, user, o, conv.course_id) for o in others):
        raise forbidden("لم يعد مسموحاً بالمراسلة في هذه المحادثة")
    file_id = None
    if upload is not None:
        cfg = tenant_settings(db, user)
        data = await files.read_upload(upload, int(cfg["messaging"]["max_attachment_mb"]))
        f = files.store(db, owner=user, purpose="message", filename=upload.filename or "file", data=data,
                        allowed_extensions=cfg["uploads"]["allowed_extensions"])
        file_id = f.id
    now = utcnow()
    db.add(Message(conversation_id=conv.id, sender_id=user.id, body=body, file_id=file_id, created_at=now))
    conv.last_message_at = now
    part = db.scalar(select(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id,
                                                          ConversationParticipant.user_id == user.id))
    part.last_read_at = now
    notifications.notify_users(db, user.university_id, [o.id for o in others], f"رسالة جديدة من {user.full_name}",
                               conv.subject, category="system", link=f"#/messages/{conv.id}")
    db.commit()
    return {"ok": True}


class ReportIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/messages/{mid}/report")
def report_message(mid: int, body: ReportIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    m = db.get(Message, mid)
    if not m:
        raise not_found()
    _participant(db, user, m.conversation_id)
    if m.sender_id == user.id:
        raise HTTPException(status_code=400, detail="لا يمكنك الإبلاغ عن رسالتك")
    rep = MessageReport(university_id=user.university_id, message_id=m.id, reporter_id=user.id, reason=body.reason)
    db.add(rep)
    db.flush()
    sender = db.get(User, m.sender_id)
    admins = db.scalars(select(User.id).where(User.university_id == user.university_id, User.role == Role.FACULTY_ADMIN,
                                              User.faculty_id == (sender.faculty_id or user.faculty_id)))
    notifications.notify_users(db, user.university_id, list(admins), "بلاغ عن رسالة",
                               f"تم الإبلاغ عن رسالة: {body.reason}", priority="important", link="#/reports-abuse")
    audit.record(db, "message.reported", actor=user, target_type="message", target_id=m.id,
                 details={"reason": body.reason}, ip=client_ip(request))
    db.commit()
    return {"id": rep.id}


@router.get("/message-reports")
def list_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN):
        raise forbidden()
    permissions.require(db, user, "messages.moderate")
    rows = db.execute(select(MessageReport, Message).join(Message, Message.id == MessageReport.message_id).where(
        MessageReport.university_id == user.university_id).order_by(MessageReport.id.desc()).limit(200)).all()
    out = []
    for rep, m in rows:
        sender = db.get(User, m.sender_id)
        if user.role == Role.FACULTY_ADMIN and sender.faculty_id != user.faculty_id:
            continue
        reporter = db.get(User, rep.reporter_id)
        out.append({"id": rep.id, "status": rep.status, "reason": rep.reason, "created_at": rep.created_at,
                    "message": {"id": m.id, "body": m.body, "hidden": m.hidden},
                    "sender": {"id": sender.id, "full_name": sender.full_name, "role": sender.role},
                    "reporter": {"id": reporter.id, "full_name": reporter.full_name}})
    return out


class ReportAction(BaseModel):
    action: str = Field(pattern="^(dismiss|hide)$")


@router.post("/message-reports/{rid}")
def handle_report(rid: int, body: ReportAction, request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    if user.role not in (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN):
        raise forbidden()
    permissions.require(db, user, "messages.moderate")
    rep = db.get(MessageReport, rid)
    if not rep or rep.university_id != user.university_id:
        raise not_found()
    m = db.get(Message, rep.message_id)
    if user.role == Role.FACULTY_ADMIN and db.get(User, m.sender_id).faculty_id != user.faculty_id:
        raise forbidden()
    rep.status, rep.handled_by = ("actioned" if body.action == "hide" else "dismissed"), user.id
    if body.action == "hide":
        m.hidden = True
    audit.record(db, "message.report_handled", actor=user, target_type="message", target_id=m.id,
                 details={"action": body.action}, ip=client_ip(request))
    db.commit()
    return {"ok": True}



# ---------------------------------------------------------------- oversight
# The university administration (and the platform administrator, who acts as it) may read every
# conversation of the university. Users are told so on the messages page, and each conversation
# opened this way is written to the audit log with the reader's name.

def _oversight(user: User) -> None:
    if user.role != Role.UNIVERSITY_ADMIN:
        raise forbidden("الاطلاع على كل الرسائل خاص بإدارة الجامعة ومشرف المنصة")


@router.get("/oversight/conversations")
def oversight_list(q: str = "", limit: int = 50, offset: int = 0, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _oversight(user)
    limit = max(1, min(limit, 200))
    stmt = select(Conversation).where(Conversation.university_id == user.university_id)
    if q.strip():
        like = f"%{q.strip()}%"
        in_body = select(Message.conversation_id).where(Message.body.ilike(like))
        by_name = select(ConversationParticipant.conversation_id).join(
            User, User.id == ConversationParticipant.user_id).where(User.full_name.ilike(like))
        stmt = stmt.where(Conversation.subject.ilike(like) | Conversation.id.in_(in_body) | Conversation.id.in_(by_name))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    convs = db.scalars(stmt.order_by(Conversation.last_message_at.desc()).limit(limit).offset(offset)).all()
    out = []
    for c in convs:
        people = db.scalars(select(User).join(ConversationParticipant, ConversationParticipant.user_id == User.id)
                            .where(ConversationParticipant.conversation_id == c.id)).all()
        last = db.scalar(select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc()).limit(1))
        count = db.scalar(select(func.count(Message.id)).where(Message.conversation_id == c.id))
        out.append({"id": c.id, "subject": c.subject, "kind": c.kind, "last_message_at": c.last_message_at,
                    "messages": count, "participants": [{"id": u.id, "full_name": u.full_name, "role": u.role} for u in people],
                    "last": (last.body[:140] if last and last.body else ("[ملف مرفق]" if last and last.file_id else ""))})
    return {"total": total, "items": out}


@router.get("/oversight/conversations/{cid}")
def oversight_read(cid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _oversight(user)
    conv = db.get(Conversation, cid)
    if not conv or conv.university_id != user.university_id:
        raise not_found()
    msgs = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    people = db.scalars(select(User).join(ConversationParticipant, ConversationParticipant.user_id == User.id)
                        .where(ConversationParticipant.conversation_id == conv.id)).all()
    names = {u.id: u.full_name for u in people}
    names.update({u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({m.sender_id for m in msgs} - set(names) or {-1})))})
    audit.record(db, "message.oversight_viewed", actor=user, target_type="conversation", target_id=conv.id,
                 details={"subject": conv.subject}, ip=client_ip(request))
    db.commit()
    out = []
    for m in msgs:
        f = db.get(StoredFile, m.file_id) if m.file_id else None
        out.append({"id": m.id, "sender_id": m.sender_id, "sender": names.get(m.sender_id), "mine": False,
                    "body": m.body, "hidden": m.hidden, "file": files.file_info(f) if f else None,
                    "created_at": m.created_at})
    return {"id": conv.id, "subject": conv.subject, "kind": conv.kind,
            "participants": [{"id": u.id, "full_name": u.full_name, "role": u.role} for u in people], "messages": out}
