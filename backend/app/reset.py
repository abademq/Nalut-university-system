"""Starting the platform again from nothing: ``sudo nus-reset`` (deploy/install-vps.sh).

Everything people entered is deleted (accounts, courses, grades, attendance, messages,
notifications, requests, files ...), after a backup of the database and the files is taken.
What is kept, so the platform still opens and is still yours:

* the university and its settings (branding, permissions, policies, SMS template ids);
* the platform administrator accounts (with their passwords and second factor), and the
  app's launch picture;
* unless ``--all``: the structure — faculties, departments, terms, programmes with their plans
  and prerequisites — to enter students and results into.

Run with the service stopped (the command does it). ``--yes`` skips the typed confirmation."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from . import models as m
from .config import settings
from .db import Base, SessionLocal, engine

STRUCTURE = [m.Faculty, m.Department, m.Term, m.Program, m.ProgramCourse, m.CoursePrerequisite]
CONFIRM = "امسح كل شيء"


def _rows(db, model, where=None) -> list[dict]:
    stmt = select(model) if where is None else select(model).where(where)
    return [{c.key: getattr(r, c.key) for c in model.__table__.columns} for r in db.scalars(stmt)]


def backup() -> list[Path]:
    """Copies of the database and the files, next to the daily backups."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files_dir = Path(settings.storage_dir)
    out_dir = files_dir.parent / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    url = settings.database_url
    if url.startswith("sqlite:///"):
        src = sqlite3.connect(url[len("sqlite:///"):])
        dest_path = out_dir / f"nus-before-reset-{stamp}.db"
        dest = sqlite3.connect(dest_path)
        src.backup(dest)
        dest.close()
        src.close()
        made.append(dest_path)
    else:
        print("! PostgreSQL: take a pg_dump yourself before resetting", file=sys.stderr)
    if files_dir.exists():
        tar_path = out_dir / f"files-before-reset-{stamp}.tgz"
        with tarfile.open(tar_path, "w:gz") as t:
            t.add(files_dir, arcname="files")
        made.append(tar_path)
    return made


def reset(*, keep_structure: bool = True) -> dict:
    db = SessionLocal()
    try:
        keep: list[tuple[type, list[dict]]] = [(m.University, _rows(db, m.University))]
        admins = _rows(db, m.User, m.User.role == m.Role.PLATFORM_ADMIN)
        for a in admins:  # never tied to one faculty or department after the reset
            a["faculty_id"] = a["department_id"] = None
        keep.append((m.User, admins))
        ids = [a["id"] for a in admins] or [-1]
        keep.append((m.MfaPreference, _rows(db, m.MfaPreference, m.MfaPreference.user_id.in_(ids))))
        keep.append((m.AppAsset, _rows(db, m.AppAsset)))
        keep.append((m.PermissionGroup, _rows(db, m.PermissionGroup)))  # the positions, without holders
        keep.append((m.PositionScope, _rows(db, m.PositionScope)))
        if keep_structure:
            keep += [(model, _rows(db, model)) for model in STRUCTURE]
    finally:
        db.close()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    counts = {}
    try:
        for model, rows in keep:
            for r in rows:
                db.add(model(**r))
            db.flush()
            counts[model.__tablename__] = len(rows)
        from . import audit

        for uni in keep[0][1]:  # the new audit chain starts with the reset itself
            audit.record(db, "system.reset", university_id=uni["id"],
                         details={"kept_structure": keep_structure})
        db.commit()
    finally:
        db.close()
    files_dir = Path(settings.storage_dir)
    if files_dir.exists():
        for child in files_dir.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    return counts


def delete_accounts() -> dict:
    """Every account but the platform administrators, with everything that belongs to them
    (their courses' enrolments, grades, attendance, messages, requests, files ...). Courses,
    structure, positions and settings stay."""
    from . import audit, purge

    db = SessionLocal()
    try:
        ids = set(db.scalars(select(m.User.id).where(m.User.role != m.Role.PLATFORM_ADMIN)))
        counts = purge.purge_users(db, ids)
        for uni in db.scalars(select(m.University)):
            audit.record(db, "system.accounts_deleted", university_id=uni.id, details={"accounts": len(ids)})
        db.commit()
        purge.remove_purged_files(db)
        return counts
    finally:
        db.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Delete all data and start again (a backup is taken first).")
    p.add_argument("--all", action="store_true", help="also delete faculties, departments, terms and programmes")
    p.add_argument("--yes", action="store_true", help="do not ask for the typed confirmation")
    p.add_argument("--accounts", action="store_true",
                   help="only delete every account but the platform administrator (and what belongs to them)")
    args = p.parse_args(argv)
    if args.accounts:
        print("ستُحذف كل الحسابات عدا مشرف المنصة، ومعها كل ما يخص أصحابها: التسجيل في المقررات والدرجات والحضور "
              "والرسائل والطلبات والملفات.\nيبقى: الجامعة وإعداداتها والهيكل والتخصصات والمقررات والصفات الوظيفية.")
        if not args.yes and input(f"اكتب «{CONFIRM}» للمتابعة: ").strip() != CONFIRM:
            print("أُلغي، لم يُحذف شيء.")
            return 1
        for path in backup():
            print(f"backup: {path}")
        counts = delete_accounts()
        print(f"done. accounts deleted: {counts.get('users', 0)}; rows: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    kept = "الجامعة وإعداداتها وحسابات مشرف المنصة" + ("" if args.all else "، والكليات والأقسام والفصول والتخصصات وخططها")
    print(f"سيُحذف كل ما أُدخل في المنصة: الحسابات والمقررات والدرجات والحضور والرسائل والطلبات والملفات.\nيبقى: {kept}.")
    if not args.yes:
        answer = input(f"اكتب «{CONFIRM}» للمتابعة: ").strip()
        if answer != CONFIRM:
            print("أُلغي، لم يُحذف شيء.")
            return 1
    for path in backup():
        print(f"backup: {path}")
    counts = reset(keep_structure=not args.all)
    print("done. kept: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if not args.yes:  # the platform account may still carry a demo password
        import getpass

        from .security import hash_password

        pw = getpass.getpass("كلمة مرور جديدة لحساب مشرف المنصة (Enter للإبقاء على الحالية): ").strip()
        if pw:
            if len(pw) < 10:
                print("! أقصر من 10 أحرف: لم تتغير. غيّرها من «حسابي» بعد الدخول.")
            else:
                db = SessionLocal()
                for u in db.scalars(select(m.User).where(m.User.role == m.Role.PLATFORM_ADMIN)):
                    u.password_hash = hash_password(pw)
                db.commit()
                db.close()
                print("تم تغيير كلمة مرور مشرف المنصة.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
