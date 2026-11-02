"""Deleting accounts for good, with everything that belongs to them.

Starting from the users to delete, every row that depends on a deleted row is found through the
foreign keys: a required reference (a submission's student, a message's sender) deletes the row,
an optional one (who graded, who created) is cleared and the row stays. This runs until nothing
new is found, then the rows go children first, and the stored files of deleted file rows are
removed from disk. The audit log keeps its rows (it holds ids only), so its chain stays intact."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import Base


def _refs():
    """[(child table, column, parent table)] for every foreign key."""
    out = []
    for t in Base.metadata.sorted_tables:
        for fk in t.foreign_keys:
            out.append((t, fk.parent, fk.column.table))
    return out


def purge_users(db: Session, user_ids: set[int]) -> dict[str, int]:
    """Deletes these users and what depends on them (the caller commits). Returns rows per table."""
    from .models import StoredFile

    users = Base.metadata.tables["users"]
    doomed: dict = {users: set(user_ids)}
    nulls: dict = {}  # (table, column) -> parent ids whose references are cleared
    refs = _refs()
    changed = True
    while changed:
        changed = False
        for child, col, parent in refs:
            ids = doomed.get(parent)
            if not ids:
                continue
            pk = list(child.primary_key.columns)[0]
            rows = set(db.execute(select(pk).where(col.in_(ids))).scalars())
            if col.nullable:
                key = (child, col)
                if not ids <= nulls.get(key, set()):
                    nulls[key] = nulls.get(key, set()) | ids
                    changed = True
                continue
            new = rows - doomed.get(child, set())
            if new:
                doomed[child] = doomed.get(child, set()) | new
                changed = True
    files = []
    if Base.metadata.tables["stored_files"] in doomed:
        ids = doomed[Base.metadata.tables["stored_files"]]
        files = list(db.scalars(select(StoredFile.stored_name).where(StoredFile.id.in_(ids))))
    for (child, col), ids in nulls.items():
        if child in doomed:  # rows going anyway need no clearing, unless they stay
            pk = list(child.primary_key.columns)[0]
            db.execute(update(child).where(col.in_(ids), pk.not_in(doomed[child])).values({col.name: None}))
        else:
            db.execute(update(child).where(col.in_(ids)).values({col.name: None}))
    counts = {}
    for t in reversed(Base.metadata.sorted_tables):
        ids = doomed.get(t)
        if ids:
            pk = list(t.primary_key.columns)[0]
            for chunk in (list(ids)[i:i + 500] for i in range(0, len(ids), 500)):
                db.execute(delete(t).where(pk.in_(chunk)))
            counts[t.name] = len(ids)
    db.flush()
    db.info.setdefault("purged_files", []).extend(files)
    return counts


def remove_purged_files(db: Session) -> None:
    """After commit: the stored files of deleted file rows."""
    root = Path(settings.storage_dir)
    for name in db.info.pop("purged_files", []):
        p = root / name
        if p.is_file():
            p.unlink()
