"""Deleting an account for good (not only switching it off).

Whoever holds users.delete may delete directly, within what the institution allows: with the
"faculty" option the faculty administration decides for its faculty's accounts, with "university"
only the university administration does. Anyone else who works with the person (a head of
department, an employee) files a request with a reason, and the deciders are notified. The
deletion removes the account and everything that belongs to it (see purge.py) and is audited
with the account's name and number."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, notifications, permissions, purge
from ..db import get_db, utcnow
from ..deps import can_view_user, client_ip, forbidden, get_current_user, manageable_roles, not_found, tenant_settings
from ..models import AccountDeletionRequest, Role, User

router = APIRouter(prefix="/api", tags=["accounts"])
KEY = "users.delete"


def can_decide(db: Session, actor: User, target_faculty_id: int | None, target_role: str) -> bool:
    if permissions.is_platform(actor):
        return target_role != Role.PLATFORM_ADMIN
    if target_role not in manageable_roles(actor):
        return False
    sc = permissions.scope(db, actor, KEY)
    if sc is None:
        return False
    if tenant_settings(db, actor)["accounts"].get("deletion_approver") == "university":
        return sc == permissions.ALL
    return permissions.in_scope(sc, target_faculty_id)


def _target(db: Session, actor: User, uid: int) -> User:
    u = db.get(User, uid)
    if not u or u.university_id != actor.university_id or u.role == Role.PLATFORM_ADMIN:
        raise not_found("الحساب غير موجود")
    if u.id == actor.id:
        raise HTTPException(status_code=400, detail="لا يحذف المستخدم حسابه بنفسه من هنا")
    return u


def _delete(db: Session, actor: User, u: User, reason: str, request: Request, req: AccountDeletionRequest | None = None):
    snapshot = {"name": u.full_name, "code": u.code, "role": u.role, "faculty_id": u.faculty_id, "reason": reason,
                "request_id": req.id if req else None, "requested_by": req.requested_by if req else None}
    uid = u.id
    if req is not None:
        req.status, req.decided_by, req.decided_at = "approved", actor.id, utcnow()
    db.flush()
    counts = purge.purge_users(db, {uid})
    audit.record(db, "user.deleted", actor=actor, target_type="user", target_id=uid,
                 details={**snapshot, "rows": sum(counts.values())}, ip=client_ip(request))
    db.commit()
    purge.remove_purged_files(db)
    return {"deleted": True, "rows": sum(counts.values())}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/users/{uid}/delete")
def delete_account(uid: int, body: ReasonIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Deletes the account now (for those who decide deletions)."""
    u = _target(db, user, uid)
    if not can_decide(db, user, u.faculty_id, u.role):
        raise forbidden("حذف هذا الحساب يحتاج موافقة الإدارة: قدّم طلب حذف")
    pending = db.scalar(select(AccountDeletionRequest).where(AccountDeletionRequest.target_id == u.id,
                                                             AccountDeletionRequest.status == "pending"))
    return _delete(db, user, u, body.reason.strip(), request, pending)


@router.post("/users/{uid}/deletion-requests")
def request_deletion(uid: int, body: ReasonIn, request: Request, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """A head of department or an employee asks the administration to delete an account."""
    if user.role not in permissions.GROUP_ROLES and not permissions.is_platform(user):
        raise forbidden()
    u = _target(db, user, uid)
    if not can_view_user(db, user, u) and not permissions.in_unit(db, user, "students.view", u.faculty_id, u.department_id):
        raise not_found("الحساب غير موجود")
    if u.role in (Role.UNIVERSITY_ADMIN, Role.FACULTY_ADMIN):
        raise HTTPException(status_code=400, detail="حسابات الإدارة لا تُحذف بطلب")
    if db.scalar(select(AccountDeletionRequest.id).where(AccountDeletionRequest.target_id == u.id,
                                                         AccountDeletionRequest.status == "pending")):
        raise HTTPException(status_code=400, detail="يوجد طلب حذف قيد النظر لهذا الحساب")
    req = AccountDeletionRequest(university_id=u.university_id, target_id=u.id, target_name=u.full_name,
                                 target_code=u.code, target_role=u.role, target_faculty_id=u.faculty_id,
                                 reason=body.reason.strip(), requested_by=user.id)
    db.add(req)
    db.flush()
    wide = tenant_settings(db, user)["accounts"].get("deletion_approver") == "university"
    deciders = [i for i in permissions.holders(db, u.university_id, KEY, None if wide else u.faculty_id) if i != user.id]
    notifications.notify_users(db, u.university_id, deciders, "طلب حذف حساب",
                               f"طلب {user.full_name} حذف حساب {u.full_name}: {req.reason}", priority="important",
                               link="#/deletions", sender=user)
    audit.record(db, "user.deletion_requested", actor=user, target_type="user", target_id=u.id,
                 details={"name": u.full_name, "code": u.code, "reason": req.reason}, ip=client_ip(request))
    db.commit()
    return {"id": req.id, "status": req.status}


def _out(db: Session, r: AccountDeletionRequest, viewer: User) -> dict:
    names = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({x for x in (r.requested_by, r.decided_by) if x} or {-1})))}
    return {"id": r.id, "status": r.status, "reason": r.reason, "created_at": r.created_at, "decided_at": r.decided_at,
            "decision_note": r.decision_note,
            "target": {"id": r.target_id, "full_name": r.target_name, "code": r.target_code, "role": r.target_role},
            "requested_by": names.get(r.requested_by), "decided_by": names.get(r.decided_by),
            "can_decide": r.status == "pending" and can_decide(db, viewer, r.target_faculty_id, r.target_role)}


@router.get("/account-deletions")
def list_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The requests this account can decide, and the ones it filed."""
    if user.role == Role.STUDENT:
        raise forbidden()
    rows = db.scalars(select(AccountDeletionRequest).where(AccountDeletionRequest.university_id == user.university_id)
                      .order_by(AccountDeletionRequest.id.desc()).limit(300))
    out = []
    for r in rows:
        item = _out(db, r, user)
        if item["can_decide"] or r.requested_by == user.id or (r.status != "pending" and can_decide(
                db, user, r.target_faculty_id, r.target_role)):
            out.append(item)
    return out


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.post("/account-deletions/{rid}")
def decide(rid: int, body: DecideIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    r = db.get(AccountDeletionRequest, rid)
    if not r or r.university_id != user.university_id:
        raise not_found()
    if r.status != "pending":
        raise HTTPException(status_code=400, detail="بُتّ في هذا الطلب من قبل")
    if not can_decide(db, user, r.target_faculty_id, r.target_role):
        raise forbidden("ليس لك البت في هذا الطلب")
    r.decision_note = body.note.strip()
    if body.approve:
        u = db.get(User, r.target_id)
        if not u:
            r.status, r.decided_by, r.decided_at = "approved", user.id, utcnow()
            db.commit()
            return {"deleted": True, "rows": 0}
        out = _delete(db, user, u, r.reason, request, r)
        if r.requested_by:
            notifications.notify_users(db, user.university_id, [r.requested_by], "نُفّذ طلب حذف حساب",
                                       f"حُذف حساب {r.target_name} نهائياً.", link="#/deletions")
            db.commit()
        return out
    r.status, r.decided_by, r.decided_at = "rejected", user.id, utcnow()
    audit.record(db, "user.deletion_rejected", actor=user, target_type="user", target_id=r.target_id,
                 details={"name": r.target_name, "note": r.decision_note}, ip=client_ip(request))
    if r.requested_by:
        notifications.notify_users(db, user.university_id, [r.requested_by], "رُفض طلب حذف حساب",
                                   f"طلب حذف حساب {r.target_name}: {r.decision_note or 'رُفض'}", link="#/deletions")
    db.commit()
    return {"status": "rejected"}
