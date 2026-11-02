"""Official documents with a QR to check them: enrolment certificate and transcript.

What a document says is frozen when it is issued (snapshot + SHA-256), so a later change of grades
does not change a paper already handed out. The QR leads to a public page that shows whether the
document is genuine, still valid or revoked, and its key facts, so a recipient can compare the paper."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
from datetime import timedelta
from html import escape

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, permissions, registration
from ..db import as_utc, get_db, utcnow
from ..deps import client_ip, get_current_user, not_found, tenant_settings
from ..models import (Department, Faculty, IssuedDocument, Program, Role, StudentProgram, StudentSemester, Term,
                      University, User)
from ..security import limiter
from ..tenancy import effective_settings

router = APIRouter(tags=["documents"])
KEY = "documents.issue"
KINDS = {"enrollment": "إفادة قيد", "transcript": "كشف درجات"}


def _student(db: Session, user: User, sid: int) -> User:
    st = db.get(User, sid)
    if not st or st.role != Role.STUDENT or st.university_id != user.university_id:
        raise not_found("الطالب غير موجود")
    return st


def _snapshot(db: Session, st: User, kind: str, cfg: dict) -> dict:
    fac = db.get(Faculty, st.faculty_id) if st.faculty_id else None
    dep = db.get(Department, st.department_id) if st.department_id else None
    sp = db.scalar(select(StudentProgram).where(StudentProgram.student_id == st.id))
    prog = db.get(Program, sp.program_id) if sp else None
    sem = db.scalar(select(StudentSemester.semester).where(StudentSemester.student_id == st.id))
    term = db.scalar(select(Term).where(Term.university_id == st.university_id, Term.is_current.is_(True)))
    base = {"name": st.full_name, "code": st.code, "faculty": fac.name if fac else None,
            "department": dep.name if dep else None, "program": prog.name if prog else None,
            "semester": sem, "term": term.name if term else None, "active": st.is_active}
    if kind == "enrollment":
        s = registration.summary(db, st, cfg)
        base.update(current_courses=s["current_courses"], current_credits=s["current_credits"],
                    earned_credits=s["earned_credits"])
    else:
        t = registration.transcript(db, st, cfg)
        base.update(terms=[{"term": x["term"], "average": x["average"], "letter": x["letter"],
                            "credits": x["credits"], "earned_credits": x["earned_credits"],
                            "courses": [{"code": c["code"], "title": c["title"], "credits": c["credits"],
                                         "percent": c["percent"], "letter": c.get("letter"), "state": c["state"]}
                                        for c in x["courses"]]} for x in t["terms"]],
                    cumulative_average=t["cumulative_average"], cumulative_letter=t["cumulative_letter"],
                    cumulative_label=t["cumulative_label"], earned_credits=t["earned_credits"])
    return base


def _hash(doc_fields: dict) -> str:
    return hashlib.sha256(json.dumps(doc_fields, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _can_see(db: Session, user: User, d: IssuedDocument) -> bool:
    if user.university_id != d.university_id:
        return False
    return d.student_id == user.id or permissions.in_scope(permissions.scope(db, user, KEY), d.faculty_id)


def _out(db: Session, d: IssuedDocument) -> dict:
    st = db.get(User, d.student_id)
    return {"id": d.id, "code": d.code, "kind": d.kind, "kind_label": KINDS[d.kind], "addressee": d.addressee,
            "student": {"id": st.id, "full_name": st.full_name, "code": st.code} if st else None,
            "issuer": d.issuer_name, "issuer_title": d.issuer_title, "self_issued": d.self_issued,
            "issued_at": d.issued_at, "revoked_at": d.revoked_at, "revoked_reason": d.revoked_reason,
            "hash": d.content_hash[:16]}


class IssueIn(BaseModel):
    student_id: int | None = None  # none: myself (a student, when the institution allows it)
    kind: str = Field(pattern="^(enrollment|transcript)$")
    addressee: str = Field(default="إلى من يهمه الأمر", min_length=3, max_length=200)


@router.post("/api/documents")
def issue(body: IssueIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = tenant_settings(db, user)
    self_issue = body.student_id in (None, user.id)
    if self_issue:
        if user.role != Role.STUDENT:
            raise HTTPException(status_code=400, detail="حدد الطالب")
        if body.kind != "enrollment" or not cfg["documents"].get("student_self_enrollment"):
            raise HTTPException(status_code=403, detail="تُصدر هذه الوثيقة من شؤون الطلبة؛ قدّم طلباً من «الطلبات والمعاملات»")
        st = user
    else:
        st = _student(db, user, body.student_id)
        permissions.require_scope(db, user, KEY, st.faculty_id)
    if not limiter.hit(f"doc:{user.id}", 30, 3600):
        raise HTTPException(status_code=429, detail="وثائق كثيرة خلال ساعة، حاول لاحقاً")
    from .admin import positions_of

    snap = _snapshot(db, st, body.kind, cfg)
    pos = positions_of(db, [user.id]).get(user.id)
    d = IssuedDocument(code=secrets.token_urlsafe(12), university_id=st.university_id, faculty_id=st.faculty_id,
                       student_id=st.id, kind=body.kind, addressee=body.addressee.strip(), snapshot=snap,
                       issued_by=user.id, issuer_name="" if self_issue else user.full_name,
                       issuer_title="" if self_issue else (pos["name"] if pos else ""), self_issued=self_issue,
                       issued_at=utcnow(), content_hash="")
    d.content_hash = _hash({"code": d.code, "kind": d.kind, "student": st.id, "addressee": d.addressee,
                            "snapshot": snap, "issued_at": d.issued_at.isoformat()})
    db.add(d)
    db.flush()
    audit.record(db, "document.issued", actor=user, target_type="document", target_id=d.id,
                 details={"kind": d.kind, "student_id": st.id, "code": d.code}, ip=client_ip(request))
    db.commit()
    return _out(db, d)


@router.get("/api/documents")
def list_documents(student_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(IssuedDocument).where(IssuedDocument.university_id == user.university_id)
    if user.role == Role.STUDENT or student_id == user.id:
        q = q.where(IssuedDocument.student_id == user.id)
    else:
        sc = permissions.require_scope(db, user, KEY)
        if student_id:
            q = q.where(IssuedDocument.student_id == student_id)
        if sc != permissions.ALL:
            q = q.where(IssuedDocument.faculty_id == sc)
    return [_out(db, d) for d in db.scalars(q.order_by(IssuedDocument.id.desc()).limit(200))]


def _get(db: Session, user: User, did: int) -> IssuedDocument:
    d = db.get(IssuedDocument, did)
    if not d or not _can_see(db, user, d):
        raise not_found("الوثيقة غير موجودة")
    return d


class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/api/documents/{did}/revoke")
def revoke(did: int, body: RevokeIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    d = _get(db, user, did)
    permissions.require_scope(db, user, KEY, d.faculty_id)
    if d.revoked_at:
        raise HTTPException(status_code=400, detail="الوثيقة ملغاة مسبقاً")
    d.revoked_at, d.revoked_reason = utcnow(), body.reason.strip()
    audit.record(db, "document.revoked", actor=user, target_type="document", target_id=d.id,
                 details={"code": d.code, "reason": d.revoked_reason}, ip=client_ip(request))
    db.commit()
    return _out(db, d)


def _qr(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=1)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def _verify_url(request: Request, code: str) -> str:
    return str(request.base_url).rstrip("/") + f"/verify/{code}"


def _fmt(dt) -> str:
    from zoneinfo import ZoneInfo

    return as_utc(dt).astimezone(ZoneInfo("Africa/Tripoli")).strftime("%Y-%m-%d")


def _num(v) -> str:
    return "—" if v is None else f"{v:g}"


STYLE = """body{font-family:'Noto Naskh Arabic','Amiri',system-ui,sans-serif;margin:0;background:#eee;color:#111}
.page{background:#fff;max-width:19cm;margin:1cm auto;padding:1.6cm 1.6cm 1.2cm;box-shadow:0 0 8px #0002}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:3px double #333;padding-bottom:.4cm}
header img{height:2.2cm}h1{text-align:center;font-size:20pt;margin:.6cm 0 .3cm}h2{font-size:13pt;margin:.4cm 0 .2cm}
p{font-size:13pt;line-height:1.9}table{width:100%;border-collapse:collapse;font-size:10.5pt;margin:.2cm 0}
td,th{border:1px solid #999;padding:3px 6px;text-align:center}th{background:#f1f1f1}td.t{text-align:right}
footer{display:flex;gap:.6cm;align-items:center;border-top:1px solid #999;margin-top:.8cm;padding-top:.3cm;font-size:9.5pt}
footer img{width:2.8cm;height:2.8cm}.sig{margin-top:.8cm;text-align:left;font-size:12pt}.void{color:#b00;font-weight:bold;
font-size:16pt;text-align:center;border:3px solid #b00;padding:.2cm}@media print{body{background:#fff}.page{box-shadow:none;margin:0;
max-width:none}.noprint{display:none}}"""


@router.get("/api/documents/{did}/html", response_class=HTMLResponse)
def document_html(did: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The printable document (the app saves it and opens it)."""
    from ..printlinks import PRINT_CSP

    return HTMLResponse(render(db, _get(db, user, did), request), headers={"Content-Security-Policy": PRINT_CSP})


@router.post("/api/documents/{did}/link")
def document_link(did: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A ten-minute link to open the printable document in a new browser tab."""
    from ..printlinks import make

    return {"url": make("doc", _get(db, user, did).id)}


@router.get("/print/doc/{token}", response_class=HTMLResponse, include_in_schema=False)
def document_print(token: str, request: Request, db: Session = Depends(get_db)):
    from ..printlinks import PRINT_CSP, check

    did = check("doc", token)
    d = db.get(IssuedDocument, did) if did else None
    if not d:
        return HTMLResponse("<p dir='rtl'>انتهت صلاحية الرابط، افتح الوثيقة من المنصة مرة أخرى.</p>", status_code=410,
                            headers={"Content-Security-Policy": PRINT_CSP})
    return HTMLResponse(render(db, d, request), headers={"Content-Security-Policy": PRINT_CSP})


def render(db: Session, d: IssuedDocument, request: Request) -> str:
    uni = db.get(University, d.university_id)
    cfg = effective_settings(uni)
    name = cfg["branding"].get("display_name") or uni.name
    s = d.snapshot
    url = _verify_url(request, d.code)
    e = escape
    who = (f"الطالب/ـة <b>{e(s['name'])}</b>، رقم القيد <b>{e(s.get('code') or '—')}</b>"
           + (f"، {e(s['faculty'])}" if s.get("faculty") else "") + (f"، قسم {e(s['department'])}" if s.get("department") else "")
           + (f"، تخصص {e(s['program'])}" if s.get("program") else ""))
    if d.kind == "enrollment":
        body = (f"<p>تشهد {e(name)} بأن {who}، "
                + ("مقيد/ـة بالجامعة" if s.get("active") else "كان/ت مقيداً/ـة بالجامعة")
                + (f" في {e(s['term'])}" if s.get("term") else "")
                + (f"، الفصل الدراسي {s['semester']}" if s.get("semester") else "")
                + (f"، ومسجل/ـة في {s['current_courses']} مقررات ({s['current_credits']} وحدة)" if s.get("current_courses") else "")
                + f"، وقد أنجز/ت {s.get('earned_credits', 0)} وحدة دراسية.</p>"
                + "<p>وقد أُعطيت هذه الإفادة بناءً على طلبه/ا لتقديمها " + e(d.addressee) + "، دون أدنى مسؤولية على الجامعة.</p>")
    else:
        rows = []
        for t in s.get("terms", []):
            rows.append(f"<h2>{e(t['term'])}</h2><table><tr><th>الرمز</th><th>المقرر</th><th>الوحدات</th><th>الدرجة</th>"
                        "<th>التقدير</th></tr>" + "".join(
                f"<tr><td>{e(c['code'])}</td><td class='t'>{e(c['title'])}</td><td>{c['credits']}</td>"
                f"<td>{_num(c['percent'])}</td><td>{e(c.get('letter') or '—')}</td></tr>" for c in t["courses"])
                + f"<tr><th colspan='2'>معدل الفصل</th><th>{t['earned_credits']}/{t['credits']}</th>"
                  f"<th>{_num(t['average'])}</th><th>{e(t['letter'] or '—')}</th></tr></table>")
        body = (f"<p>{who}.</p>" + "".join(rows)
                + f"<h2>المعدل التراكمي: {_num(s.get('cumulative_average'))}"
                  f" ({e(s.get('cumulative_label') or s.get('cumulative_letter') or '—')}) — الوحدات المنجزة: {s.get('earned_credits', 0)}</h2>")
    void = f"<div class='void'>وثيقة ملغاة: {e(d.revoked_reason or '')}</div>" if d.revoked_at else ""
    sig = ("<div class='sig'>صادرة إلكترونياً بطلب الطالب</div>" if d.self_issued else
           f"<div class='sig'>{e(d.issuer_title or 'المختص')}<br><b>{e(d.issuer_name)}</b></div>")
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{KINDS[d.kind]} — {e(s['name'])}</title><style>{STYLE}</style></head><body><div class="page">
<header><div><b style="font-size:15pt">{e(name)}</b><br>{e(s.get('faculty') or '')}</div>
<img src="/static/logo-full.png" alt="" onerror="this.remove()"></header>
<div style="display:flex;justify-content:space-between;font-size:10pt;margin-top:.2cm"><span>الرقم: {e(d.code)}</span>
<span>التاريخ: {_fmt(d.issued_at)}</span></div>{void}
<h1>{KINDS[d.kind]}</h1>{body}{sig}
<footer><img src="{_qr(url)}" alt="QR"><div>وثيقة صادرة من منصة {e(name)}. للتحقق من صحتها امسح الرمز أو افتح:<br>
<span dir="ltr">{e(url)}</span><br>بصمة المحتوى: <span dir="ltr">{d.content_hash[:16]}</span></div></footer>
<p class="noprint" style="text-align:center;color:#666">للطباعة أو الحفظ PDF: قائمة المتصفح ← طباعة (Ctrl+P).</p></div></body></html>"""


def _verify_data(db: Session, code: str) -> dict | None:
    d = db.scalar(select(IssuedDocument).where(IssuedDocument.code == code))
    if not d:
        return None
    uni = db.get(University, d.university_id)
    cfg = effective_settings(uni)
    days = int(cfg["documents"].get("valid_days") or 0)
    expired = bool(days) and utcnow() > as_utc(d.issued_at) + timedelta(days=days)
    s = d.snapshot
    return {"valid": not d.revoked_at and not expired, "revoked": bool(d.revoked_at), "revoked_reason": d.revoked_reason,
            "expired": expired, "kind": KINDS[d.kind], "university": cfg["branding"].get("display_name") or uni.name,
            "student": s["name"], "student_code": s.get("code"), "faculty": s.get("faculty"),
            "program": s.get("program"), "issued_at": _fmt(d.issued_at), "addressee": d.addressee,
            "issuer": None if d.self_issued else d.issuer_name, "self_issued": d.self_issued,
            "cumulative_average": s.get("cumulative_average") if d.kind == "transcript" else None,
            "earned_credits": s.get("earned_credits"), "hash": d.content_hash[:16], "valid_days": days}


@router.get("/api/verify/{code}")
def verify_json(code: str, request: Request, db: Session = Depends(get_db)):
    if not limiter.hit(f"verify:{client_ip(request)}", 60, 60):
        raise HTTPException(status_code=429, detail="محاولات كثيرة")
    data = _verify_data(db, code[:40])
    if not data:
        raise not_found("لا توجد وثيقة بهذا الرقم")
    return data


@router.get("/verify/{code}", response_class=HTMLResponse, include_in_schema=False)
def verify_page(code: str, request: Request, db: Session = Depends(get_db)):
    if not limiter.hit(f"verify:{client_ip(request)}", 60, 60):
        raise HTTPException(status_code=429, detail="محاولات كثيرة")
    v = _verify_data(db, code[:40])
    e = escape
    if not v:
        state, color, rows = "لا توجد وثيقة بهذا الرقم — قد تكون مزورة", "#b00", ""
    else:
        state, color = (("وثيقة صحيحة وسارية", "#0a7a3d") if v["valid"] else
                        (f"وثيقة ملغاة: {e(v['revoked_reason'] or '')}", "#b00") if v["revoked"] else
                        (f"وثيقة صحيحة لكن انتهت صلاحيتها ({v['valid_days']} يوماً من الإصدار)", "#b36b00"))
        facts = [("نوع الوثيقة", v["kind"]), ("الجهة", v["university"]), ("الطالب", v["student"]),
                 ("رقم القيد", v["student_code"]), ("الكلية", v["faculty"]), ("التخصص", v["program"]),
                 ("تاريخ الإصدار", v["issued_at"]), ("موجهة إلى", v["addressee"]),
                 ("أصدرها", "الطالب إلكترونياً" if v["self_issued"] else v["issuer"]),
                 ("المعدل التراكمي", v["cumulative_average"]), ("الوحدات المنجزة", v["earned_credits"]),
                 ("بصمة المحتوى", v["hash"])]
        rows = "".join(f"<tr><th>{k}</th><td>{e(str(x))}</td></tr>" for k, x in facts if x not in (None, ""))
    from ..printlinks import PRINT_CSP

    return HTMLResponse(f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>التحقق من وثيقة</title><style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;
padding:16px;background:#f6f6f6}}.card{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px #0002}}
.state{{color:#fff;background:{color};padding:12px;border-radius:8px;font-size:18px;font-weight:bold;text-align:center}}
table{{width:100%;border-collapse:collapse;margin-top:12px}}th,td{{padding:8px;border-bottom:1px solid #eee;text-align:right}}
th{{color:#555;width:40%}}p{{color:#555;font-size:14px}}</style></head><body><div class="card"><h1>التحقق من وثيقة</h1>
<div class="state">{state}</div><table>{rows}</table><p>قارن هذه البيانات بالورقة التي بين يديك؛ أي اختلاف يعني أن الورقة عُدّلت بعد إصدارها.</p>
</div></body></html>""", headers={"Content-Security-Policy": PRINT_CSP})
