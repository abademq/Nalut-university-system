"""Tamper-evident audit log.

Each entry stores the hash of the previous entry; editing or deleting a row breaks
the chain, which :func:`verify_chain` detects.
"""
from __future__ import annotations

import hashlib
import json
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import AuditLog, User

_lock = threading.Lock()


def _digest(prev: str | None, row: AuditLog) -> str:
    material = json.dumps(
        [prev, row.university_id, row.actor_id, row.action, row.target_type, row.target_id,
         row.details, row.ip, row.created_at.isoformat()],
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def record(db: Session, action: str, *, actor: User | None = None, university_id: int | None = None,
           target_type: str | None = None, target_id: object = None, details: dict | None = None,
           ip: str | None = None) -> AuditLog:
    """Add an audit row to the current transaction (caller commits)."""
    with _lock:
        prev = db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
        row = AuditLog(
            university_id=university_id if university_id is not None else (actor.university_id if actor else None),
            actor_id=actor.id if actor else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details or {},
            ip=ip,
            created_at=utcnow(),
            prev_hash=prev,
        )
        row.hash = _digest(prev, row)
        db.add(row)
        db.flush()
        return row


def verify_chain(db: Session) -> dict:
    prev = None
    count = 0
    for row in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        if row.prev_hash != prev or _digest(prev, row) != row.hash:
            return {"ok": False, "broken_at": row.id, "checked": count}
        prev = row.hash
        count += 1
    return {"ok": True, "checked": count}
