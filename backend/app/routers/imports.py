"""Entering existing data from Excel: students (current and former, with their status, semester
and programme) and results obtained before the platform. Each upload is checked first and shown
as a preview with the problems of each row; nothing changes until it is applied."""
from __future__ import annotations

import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, permissions
from ..db import get_db
from ..deps import client_ip, get_current_user, not_found
from ..grades import _rows_from_upload
from ..models import (
    Department,
    Faculty,
    ImportJob,
    PriorCredit,
    Program,
    ProgramCourse,
    Role,
    StudentProgram,
    StudentRecord,
    StudentSemester,
    User,
)
from ..security import hash_password
from .admin import temp_password
from .auth import normalize_identifier

router = APIRouter(prefix="/api/import", tags=["import"])
KEYS = {"students": "users.manage", "results": "programs.manage"}
STATUS = {"مستمر": "active", "موقوف قيده": "suspended", "موقوف": "suspended", "متخرج": "graduated",
          "منسحب": "withdrawn", "active": "active", "suspended": "suspended", "graduated": "graduated",
          "withdrawn": "withdrawn"}
# column -> header names accepted (Arabic as in the template, or English)
COLUMNS = {
    "students": {"code": ["رقم القيد", "code"], "full_name": ["الاسم", "name"], "email": ["البريد", "email"],
                 "phone": ["الهاتف", "phone"], "faculty": ["الكلية", "faculty"], "department": ["القسم", "department"],
                 "cohort": ["الدفعة", "cohort"], "status": ["الحالة", "status"],
                 "semester": ["الفصل الدراسي", "semester"], "program": ["التخصص", "program"]},
    "results": {"code": ["رقم القيد", "code"], "course_code": ["رمز المقرر", "course_code"],
                "course_title": ["اسم المقرر", "course_title"], "credits": ["الوحدات", "credits"],
                "percent": ["الدرجة", "الدرجة %", "percent"], "term": ["الفصل", "term"], "kind": ["النوع", "kind"]},
}
REQUIRED = {"students": ["code", "full_name", "faculty"], "results": ["code", "course_code"]}
EXAMPLE = {
    "students": [["2020001", "سالم علي الطاهر", "salem@example.ly", "0912345678", "تقنية المعلومات", "علوم الحاسوب",
                  "2020", "مستمر", "7", "CS"],
                 ["2016004", "مريم محمد", "", "", "تقنية المعلومات", "نظم المعلومات", "2016", "متخرج", "", ""]],
    "results": [["2020001", "MATH101", "رياضة 1", "3", "78", "خريف 2020", "سابق"],
                ["2020001", "ENG101", "لغة إنجليزية 1", "2", "", "", "معادلة"]],
}
HELP = {
    "students": ["الحقول الإلزامية: رقم القيد، الاسم، الكلية. تُطابق الكلية والقسم والتخصص بالاسم أو الرمز.",
                 "الحالة: مستمر، موقوف قيده، متخرج، منسحب (المنسحب يُوقف حسابه).",
                 "الفصل الدراسي: رقم الفصل الذي فيه الطالب الآن (اختياري).",
                 "الطالب الموجود (بنفس رقم القيد) تُحدَّث بياناته؛ الجديد يُنشأ له حساب بكلمة مرور مؤقتة تظهر مرة واحدة."],
    "results": ["الحقول الإلزامية: رقم القيد، رمز المقرر. الاسم والوحدات تؤخذ من خطة الطالب إن تُركت فارغة.",
                "الدرجة نسبة من 100 (اختيارية؛ بدونها يُحتسب المقرر في الوحدات والمتطلبات فقط).",
                "النوع: سابق (درسه قبل المنصة) أو معادلة (من جامعة أخرى).",
                "تُسجَّل كل الأسطر نجاحاً في المقرر؛ المقررات التي رسب فيها لا تُدخل."],
}


def _scope(db: Session, user: User, kind: str):
    if kind not in KEYS:
        raise not_found()
    return permissions.require_scope(db, user, KEYS[kind])


@router.get("/{kind}/template")
def template(kind: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """An Excel file with the expected columns, two example rows and the rules."""
    from openpyxl import Workbook

    _scope(db, user, kind)
    wb = Workbook()
    ws = wb.active
    ws.title = "البيانات"
    ws.sheet_view.rightToLeft = True
    ws.append([names[0] for names in COLUMNS[kind].values()])
    for row in EXAMPLE[kind]:
        ws.append(row)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18
    info = wb.create_sheet("طريقة التعبئة")
    info.sheet_view.rightToLeft = True
    for line in HELP[kind] + ["احذف سطري المثال قبل الرفع. تُقرأ الورقة الأولى فقط."]:
        info.append([line])
    info.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    name = "students-template.xlsx" if kind == "students" else "results-template.xlsx"
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


def _header_map(kind: str, header: list[str]) -> dict[str, int]:
    norm = [re.sub(r"\s+", " ", (h or "").strip()).lower() for h in header]
    out = {}
    for key, names in COLUMNS[kind].items():
        for n in names:
            if n.lower() in norm:
                out[key] = norm.index(n.lower())
                break
    missing = [COLUMNS[kind][k][0] for k in REQUIRED[kind] if k not in out]
    if missing:
        raise HTTPException(status_code=400, detail=f"أعمدة ناقصة في الملف: {'، '.join(missing)} "
                                                    "(نزّل النموذج واستعمل عناوين أعمدته)")
    return out


def _text(v) -> str:
    s = str(v or "").strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s  # Excel turns 2020001 into 2020001.0


def _find_faculty(facs: list[Faculty], value: str) -> Faculty | None:
    v = value.strip()
    short = v[5:].strip() if v.startswith("كلية ") else v
    for f in facs:
        if v in (f.name, f.code) or short in (f.name, f.name.removeprefix("كلية ").strip(), f.code):
            return f
    return None


def _check_students(db: Session, user: User, sc, table: list[list[str]]) -> tuple[list, list]:
    cols = _header_map("students", table[0])
    facs = list(db.scalars(select(Faculty).where(Faculty.university_id == user.university_id)))
    deps = list(db.scalars(select(Department).where(Department.university_id == user.university_id)))
    progs = list(db.scalars(select(Program).where(Program.university_id == user.university_id)))
    rows, errors, seen = [], [], {"code": set(), "email": set(), "phone": set()}
    for i, raw in enumerate(table[1:], start=2):
        cell = {k: _text(raw[j]) if j < len(raw) else "" for k, j in cols.items()}
        if not any(cell.values()):
            continue
        problems = [f"«{COLUMNS['students'][k][0]}» فارغ" for k in REQUIRED["students"] if not cell.get(k)]
        fac = _find_faculty(facs, cell.get("faculty", "")) if cell.get("faculty") else None
        if cell.get("faculty") and not fac:
            problems.append(f"لا توجد كلية «{cell['faculty']}»")
        if fac and not permissions.in_scope(sc, fac.id):
            problems.append("الكلية خارج نطاق صلاحياتك")
        dep = None
        if cell.get("department") and fac:
            dep = next((d for d in deps if d.faculty_id == fac.id and cell["department"] in (d.name, d.code)), None)
            if not dep:
                problems.append(f"لا يوجد قسم «{cell['department']}» في {fac.name}")
        prog = None
        if cell.get("program") and fac:
            prog = next((p for p in progs if p.faculty_id == fac.id and cell["program"] in (p.name, p.code)), None)
            if not prog:
                problems.append(f"لا يوجد تخصص «{cell['program']}» في {fac.name}")
        status = STATUS.get(cell.get("status") or "مستمر")
        if not status:
            problems.append(f"حالة غير معروفة «{cell['status']}»")
        semester = None
        if cell.get("semester"):
            if not cell["semester"].isdigit() or not 1 <= int(cell["semester"]) <= 14:
                problems.append("الفصل الدراسي رقم من 1 إلى 14")
            else:
                semester = int(cell["semester"])
        email = cell.get("email", "").lower() or None
        phone = normalize_identifier(cell["phone"])[1] if cell.get("phone") else None
        existing = db.scalar(select(User).where(User.university_id == user.university_id, User.code == cell.get("code")))
        if existing and existing.role != Role.STUDENT:
            problems.append("رقم القيد مستعمل لحساب ليس طالباً")
        for key, value in (("code", cell.get("code")), ("email", email), ("phone", phone)):
            if value and value in seen[key]:
                problems.append(f"{COLUMNS['students'][key][0]} مكرر في الملف")
            if value:
                seen[key].add(value)
        for key, value in (("email", email), ("phone", phone)):
            if value:
                other = db.scalar(select(User).where(getattr(User, key) == value))
                if other and (not existing or other.id != existing.id):
                    problems.append(f"{COLUMNS['students'][key][0]} مستعمل لحساب آخر")
        row = {"line": i, "code": cell.get("code"), "full_name": cell.get("full_name"), "email": email, "phone": phone,
               "faculty_id": fac.id if fac else None, "faculty": fac.name if fac else cell.get("faculty"),
               "department_id": dep.id if dep else None, "cohort": cell.get("cohort") or None, "status": status,
               "semester": semester, "program_id": prog.id if prog else None,
               "action": "update" if existing else "create"}
        rows.append(row)
        if problems:
            errors.append({"line": i, "code": cell.get("code"), "problems": problems})
    return rows, errors


def _check_results(db: Session, user: User, sc, table: list[list[str]]) -> tuple[list, list]:
    from .. import registration

    cols = _header_map("results", table[0])
    rows, errors, seen, students = [], [], set(), {}
    for i, raw in enumerate(table[1:], start=2):
        cell = {k: _text(raw[j]) if j < len(raw) else "" for k, j in cols.items()}
        if not any(cell.values()):
            continue
        problems = [f"«{COLUMNS['results'][k][0]}» فارغ" for k in REQUIRED["results"] if not cell.get(k)]
        code = cell.get("code")
        st = students.get(code)
        if code and code not in students:
            st = students[code] = db.scalar(select(User).where(User.university_id == user.university_id,
                                                               User.code == code, User.role == Role.STUDENT))
        if code and not st:
            problems.append(f"لا يوجد طالب برقم القيد {code} (استورد الطلبة أولاً)")
        if st and not permissions.in_scope(sc, st.faculty_id):
            problems.append("الطالب خارج نطاق صلاحياتك")
        course = cell.get("course_code", "").upper()
        plan = None
        if st and course:
            prog = registration.program_of(db, st)
            plan = db.scalar(select(ProgramCourse).where(ProgramCourse.program_id == prog.id, ProgramCourse.code == course)) \
                if prog else None
        title = cell.get("course_title") or (plan.title if plan else "")
        if course and not title:
            problems.append(f"اكتب اسم المقرر {course} (ليس في خطة الطالب)")
        credits = cell.get("credits")
        if credits and (not credits.isdigit() or int(credits) > 20):
            problems.append("الوحدات رقم من 0 إلى 20")
        percent = cell.get("percent")
        try:
            percent = float(percent.replace("٫", ".").replace(",", ".")) if percent else None
            if percent is not None and not 0 <= percent <= 100:
                raise ValueError
        except ValueError:
            problems.append("الدرجة نسبة من 0 إلى 100")
            percent = None
        kind = {"سابق": "prior", "معادلة": "transfer", "prior": "prior", "transfer": "transfer"}.get(cell.get("kind") or "سابق")
        if not kind:
            problems.append("النوع: سابق أو معادلة")
        if (code, course) in seen:
            problems.append("المقرر مكرر لنفس الطالب في الملف")
        seen.add((code, course))
        rows.append({"line": i, "code": code, "student_id": st.id if st else None, "full_name": st.full_name if st else None,
                     "course_code": course, "course_title": title,
                     "credits": int(credits) if credits and credits.isdigit() else (plan.credits if plan else 3),
                     "percent": percent, "term": cell.get("term") or "", "kind": kind or "prior"})
        if problems:
            errors.append({"line": i, "code": code, "problems": problems})
    return rows, errors


@router.post("/{kind}/preview")
async def preview(kind: str, upload: UploadFile = File(...), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    sc = _scope(db, user, kind)
    data = await files.read_upload(upload, 10)
    table = _rows_from_upload(upload.filename or "", data)
    if len(table) < 2:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(table) > 20001:
        raise HTTPException(status_code=400, detail="الملف أكبر من 20000 سطر؛ قسّمه")
    rows, errors = (_check_students if kind == "students" else _check_results)(db, user, sc, table)
    job = ImportJob(university_id=user.university_id, kind=kind, uploaded_by=user.id,
                    filename=files.safe_filename(upload.filename or ""), rows=rows, errors=errors)
    db.add(job)
    db.commit()
    summary = {"rows": len(rows), "errors": len(errors)}
    if kind == "students":
        summary.update(create=sum(r["action"] == "create" for r in rows), update=sum(r["action"] == "update" for r in rows))
    return {"id": job.id, "summary": summary, "errors": errors[:500], "sample": rows[:20],
            "can_commit": bool(rows) and not errors}


@router.post("/jobs/{jid}/commit")
def commit(jid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(ImportJob, jid)
    if not job or job.university_id != user.university_id or job.uploaded_by != user.id:
        raise not_found()
    _scope(db, user, job.kind)
    if job.status != "preview":
        raise HTTPException(status_code=400, detail="طُبّق هذا الملف من قبل")
    if job.errors:
        raise HTTPException(status_code=400, detail="صحّح الأخطاء في الملف وارفعه من جديد")
    out = _apply_students(db, user, job.rows) if job.kind == "students" else _apply_results(db, user, job.rows)
    job.status = "committed"
    audit.record(db, f"import.{job.kind}", actor=user, details={"file": job.filename, **{k: v for k, v in out.items()
                                                                                          if k != "passwords"}},
                 ip=client_ip(request))
    db.commit()
    return out


def _apply_students(db: Session, user: User, rows: list[dict]) -> dict:
    created, updated, passwords = 0, 0, []
    for r in rows:
        st = db.scalar(select(User).where(User.university_id == user.university_id, User.code == r["code"]))
        if st is None:
            pw = temp_password()
            st = User(university_id=user.university_id, role=Role.STUDENT, code=r["code"], password_hash=hash_password(pw),
                      must_change_password=True, full_name=r["full_name"])
            db.add(st)
            passwords.append({"code": r["code"], "full_name": r["full_name"], "password": pw})
            created += 1
        else:
            updated += 1
        st.full_name, st.faculty_id, st.department_id = r["full_name"], r["faculty_id"], r["department_id"]
        st.cohort = r["cohort"] or st.cohort
        if r["email"]:
            st.email = r["email"]
        if r["phone"]:
            st.phone = r["phone"]
        st.is_active = r["status"] != "withdrawn"
        db.flush()
        rec = db.scalar(select(StudentRecord).where(StudentRecord.student_id == st.id))
        if rec is None:
            rec = StudentRecord(university_id=st.university_id, student_id=st.id)
            db.add(rec)
        rec.status = r["status"]
        if r["semester"]:
            sem = db.scalar(select(StudentSemester).where(StudentSemester.student_id == st.id))
            if sem:
                sem.semester, sem.set_by = r["semester"], user.id
            else:
                db.add(StudentSemester(student_id=st.id, semester=r["semester"], set_by=user.id))
        if r["program_id"]:
            sp = db.scalar(select(StudentProgram).where(StudentProgram.student_id == st.id))
            if sp:
                sp.program_id = r["program_id"]
            else:
                db.add(StudentProgram(student_id=st.id, program_id=r["program_id"]))
    return {"created": created, "updated": updated, "passwords": passwords}


def _apply_results(db: Session, user: User, rows: list[dict]) -> dict:
    added, updated = 0, 0
    for r in rows:
        p = db.scalar(select(PriorCredit).where(PriorCredit.student_id == r["student_id"],
                                                PriorCredit.code == r["course_code"]))
        if p is None:
            p = PriorCredit(university_id=user.university_id, student_id=r["student_id"], code=r["course_code"],
                            created_by=user.id)
            db.add(p)
            added += 1
        else:
            updated += 1
        p.title, p.credits, p.kind, p.percent = r["course_title"], r["credits"], r["kind"], r["percent"]
        p.note = f"الفصل: {r['term']}" if r["term"] else (p.note or "")
    return {"added": added, "updated": updated}
