"""Demo data that walks through the full scenario.

    python -m app.seed            # create demo data if missing
    python -m app.seed --reset    # drop everything and recreate

All demo accounts use the password printed at the end. Never run this in production.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

from sqlalchemy import select

from . import attendance, audit, files, notifications
from .config import settings
from .db import Base, SessionLocal, engine, init_db, utcnow
from .models import (
    AssessmentComponent,
    Assignment,
    AttendanceRecord,
    AttendanceSession,
    Conversation,
    ConversationParticipant,
    Course,
    CourseResult,
    CourseStaff,
    Department,
    Enrollment,
    Faculty,
    GradeChange,
    GradeEntry,
    Message,
    Role,
    ServiceRequest,
    ServiceRequestEvent,
    Submission,
    SubmissionEvent,
    SubmissionFile,
    Term,
    University,
    User,
)
from .security import hash_password

DEMO_PASSWORD = "Demo@12345"

STUDENT_NAMES = [
    "علي محمد الطاهر", "فاطمة سالم الزروق", "محمد عبدالله الشريف", "مريم خليفة الورفلي", "يوسف إبراهيم بن سعيد",
    "هدى عمر القماطي", "عبدالرحمن صالح الجبالي", "آمنة مصطفى النعاس", "حمزة علي المبروك", "سارة أحمد الفيتوري",
    "إبراهيم ناجي الحاجي", "رحاب منصور الككلي",
]
ENG_STUDENTS = ["خالد ميلاد التومي", "نور الهدى بشير الصغير", "أسامة فرج الدرسي", "ريم عادل المنتصر"]


def _pdf(text: str) -> bytes:
    body = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode()
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length " + str(len(body)).encode() + b">>stream\n" + body + b"\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def _user(db, uni, role, name, email, phone=None, code=None, faculty=None, dept=None, cohort=None, office=None):
    u = User(university_id=uni.id if uni else None, faculty_id=faculty.id if faculty else None,
             department_id=dept.id if dept else None, role=role, full_name=name, email=email, phone=phone, code=code,
             cohort=cohort, office=office, password_hash=hash_password(DEMO_PASSWORD))
    db.add(u)
    db.flush()
    return u


def seed(db) -> None:
    rnd = random.Random(42)
    now = utcnow()

    _user(db, None, Role.PLATFORM_ADMIN, "مشرف المنصة", "platform@demo.ly")

    # Demo convenience: MFA enforcement for admins is switched off so that every role can log in
    # during the presentation. Production universities keep the secure default (on).
    uni = University(code="nalut", name="جامعة نالوت", settings={
        "branding": {"display_name": "جامعة نالوت — المنصة الذكية", "primary_color": "#0f5c4d",
                     "accent_color": "#c8a24a"},
        "security": {"require_mfa_for_admins": False},
        "notifications": {"sms_enabled": True},
    })
    db.add(uni)
    db.flush()

    it = Faculty(university_id=uni.id, name="كلية تقنية المعلومات", code="IT", settings={})
    eng = Faculty(university_id=uni.id, name="كلية الهندسة", code="ENG", settings={})
    eco = Faculty(university_id=uni.id, name="كلية الاقتصاد", code="ECO", settings={})
    db.add_all([it, eng, eco])
    db.flush()
    cs = Department(university_id=uni.id, faculty_id=it.id, name="علوم الحاسوب", code="CS")
    is_ = Department(university_id=uni.id, faculty_id=it.id, name="نظم المعلومات", code="IS")
    ce = Department(university_id=uni.id, faculty_id=eng.id, name="الهندسة المدنية", code="CE")
    acc = Department(university_id=uni.id, faculty_id=eco.id, name="المحاسبة", code="ACC")
    db.add_all([cs, is_, ce, acc])
    db.flush()
    term = Term(university_id=uni.id, name="خريف 2026", start_date=date(2026, 9, 1), end_date=date(2027, 1, 20),
                is_current=True)
    db.add(term)

    president = _user(db, uni, Role.UNIVERSITY_ADMIN, "د. عبدالسلام الباروني (إدارة الجامعة)",
                      "president@nalut.edu.ly", "0910000100", "E100")
    dean_it = _user(db, uni, Role.FACULTY_ADMIN, "د. نجاة المدني (عميد تقنية المعلومات)", "dean.it@nalut.edu.ly",
                    "0910000101", "E101", it)
    _user(db, uni, Role.FACULTY_ADMIN, "د. فتحي الزنتاني (عميد الهندسة)", "dean.eng@nalut.edu.ly", "0910000102",
          "E102", eng)
    registrar = _user(db, uni, Role.STAFF, "أ. سعاد الككلي (التسجيل)", "registrar@nalut.edu.ly", "0910000103",
                      "E103", it, office="registrar")
    _user(db, uni, Role.STAFF, "أ. مراد الشيباني (شؤون الطلبة)", "affairs@nalut.edu.ly", "0910000104", "E104", it,
          office="student_affairs")
    t_ahmed = _user(db, uni, Role.TEACHER, "د. أحمد بن عمران", "t.ahmed@nalut.edu.ly", "0910000201", "E201", it, cs)
    t_salma = _user(db, uni, Role.TEACHER, "د. سلمى القاضي", "t.salma@nalut.edu.ly", "0910000202", "E202", it, is_)
    ta_omar = _user(db, uni, Role.ASSISTANT, "م. عمر الجرّاري (معيد)", "ta.omar@nalut.edu.ly", "0910000203", "E203",
                    it, cs)
    t_khaled = _user(db, uni, Role.TEACHER, "د. خالد المهدوي", "t.khaled@nalut.edu.ly", "0910000204", "E204", eng, ce)

    students = []
    for i, name in enumerate(STUDENT_NAMES, start=1):
        dept = cs if i <= 8 else is_
        email = "s.ali@nalut.edu.ly" if i == 1 else f"student{i}@nalut.edu.ly"
        students.append(_user(db, uni, Role.STUDENT, name, email, f"09200000{i:02d}", f"2023{i:03d}", it, dept,
                              cohort="2023"))
    eng_students = [_user(db, uni, Role.STUDENT, n, f"eng{i}@nalut.edu.ly", f"09300000{i:02d}", f"2024{i:03d}", eng,
                          ce, cohort="2024") for i, n in enumerate(ENG_STUDENTS, start=1)]

    def course(code, title, fac, dept, schedule, staff, enrolled, comps=(("أعمال السنة", 40), ("الامتحان النهائي", 60))):
        c = Course(university_id=uni.id, faculty_id=fac.id, department_id=dept.id, term_id=term.id, code=code,
                   title=title, credits=3, schedule=schedule)
        db.add(c)
        db.flush()
        for i, (n, m) in enumerate(comps):
            db.add(AssessmentComponent(course_id=c.id, name=n, max_score=m, position=i))
        for u, r in staff:
            db.add(CourseStaff(course_id=c.id, user_id=u.id, role=r))
        for s in enrolled:
            db.add(Enrollment(course_id=c.id, student_id=s.id))
        db.flush()
        return c

    cs101 = course("CS101", "مقدمة في البرمجة", it, cs,
                   [{"day": 0, "start": "08:30", "end": "10:00", "room": "A101"},
                    {"day": 2, "start": "08:30", "end": "10:00", "room": "A101"}],
                   [(t_ahmed, "instructor"), (ta_omar, "assistant")], students[:10],
                   (("واجبات", 20), ("الامتحان النصفي", 20), ("الامتحان النهائي", 60)))
    cs201 = course("CS201", "هياكل البيانات", it, cs,
                   [{"day": 1, "start": "10:30", "end": "12:00", "room": "Lab-2"},
                    {"day": 3, "start": "10:30", "end": "12:00", "room": "Lab-2"}],
                   [(t_ahmed, "instructor")], students[:8])
    is110 = course("IS110", "مبادئ نظم المعلومات", it, is_,
                   [{"day": 1, "start": "08:30", "end": "10:00", "room": "B204"}],
                   [(t_salma, "instructor")], students[4:12])
    ce101 = course("CE101", "الرسم الهندسي", eng, ce,
                   [{"day": 0, "start": "12:30", "end": "14:00", "room": "E-Hall"}],
                   [(t_khaled, "instructor")], eng_students)

    # ----- grades: IS110 published, CS201 waiting for approval, CS101 draft in progress
    def fill_grades(c, studs, lo=40, hi=98):
        comps = list(db.scalars(select(AssessmentComponent).where(AssessmentComponent.course_id == c.id)))
        teacher = db.scalar(select(User).join(CourseStaff, CourseStaff.user_id == User.id).where(
            CourseStaff.course_id == c.id, CourseStaff.role == "instructor"))
        for s in studs:
            pct = rnd.uniform(lo, hi) / 100
            for comp in comps:
                score = round(min(comp.max_score, max(0, comp.max_score * (pct + rnd.uniform(-0.1, 0.1)))) * 2) / 2
                db.add(GradeEntry(course_id=c.id, student_id=s.id, component_id=comp.id, score=score,
                                  updated_by=teacher.id))
                db.add(GradeChange(course_id=c.id, student_id=s.id, component_id=comp.id, old_score=None,
                                   new_score=score, reason="إدخال أولي", actor_id=teacher.id))

    fill_grades(is110, students[4:12])
    db.add(CourseResult(course_id=is110.id, status="published", submitted_by=t_salma.id,
                        submitted_at=now - timedelta(days=5), approved_by=dean_it.id,
                        approved_at=now - timedelta(days=4), published_by=dean_it.id,
                        published_at=now - timedelta(days=4)))
    fill_grades(cs201, students[:8])
    db.add(CourseResult(course_id=cs201.id, status="submitted", submitted_by=t_ahmed.id,
                        submitted_at=now - timedelta(days=1)))
    db.add(CourseResult(course_id=cs101.id, status="draft"))
    db.add(CourseResult(course_id=ce101.id, status="draft"))
    db.flush()

    # ----- assignments
    a1 = Assignment(university_id=uni.id, course_id=cs101.id, created_by=t_ahmed.id, title="واجب 1: المتغيرات والشروط",
                    description="حل التمارين 1-10 من الفصل الثاني وارفع الحل بصيغة PDF.", kind="homework",
                    open_at=now - timedelta(days=14), due_at=now - timedelta(days=7), max_score=10,
                    allowed_extensions=["pdf", "docx", "jpg", "jpeg", "png"], reminder_sent=True)
    a2 = Assignment(university_id=uni.id, course_id=cs101.id, created_by=t_ahmed.id, title="مشروع: آلة حاسبة بسيطة",
                    description="برنامج آلة حاسبة يدعم العمليات الأساسية مع تقرير قصير يشرح التصميم.", kind="project",
                    open_at=now - timedelta(days=3), due_at=now + timedelta(days=3), max_score=20,
                    allowed_extensions=["pdf", "docx", "zip"])
    a3 = Assignment(university_id=uni.id, course_id=cs201.id, created_by=t_ahmed.id,
                    title="بحث: أشجار البحث الثنائية", description="بحث من 5 صفحات عن أشجار البحث الثنائية وتطبيقاتها.",
                    kind="research", open_at=now - timedelta(days=2), due_at=now + timedelta(days=6), max_score=15,
                    allowed_extensions=["pdf", "docx"])
    a4 = Assignment(university_id=uni.id, course_id=is110.id, created_by=t_salma.id, title="نشاط: تحليل نظام قائم",
                    description="اختر نظاماً معلوماتياً في مؤسسة محلية وحلل مكوناته.", kind="activity",
                    open_at=now - timedelta(days=10), due_at=now - timedelta(days=2), max_score=10,
                    allowed_extensions=["pdf", "docx"], reminder_sent=True)
    db.add_all([a1, a2, a3, a4])
    db.flush()

    def submission(a, student, *, late=False, score=None, release=False, final=True):
        f = files.store(db, owner=student, purpose="submission", filename=f"{student.code}-{a.id}.pdf",
                        data=_pdf(f"Submission {student.code}"), allowed_extensions=["pdf"])
        s = Submission(assignment_id=a.id, student_id=student.id, status="submitted" if final else "in_progress",
                       version=1, submitted_at=(a.due_at + timedelta(hours=5)) if late else a.due_at - timedelta(days=1)
                       if final else None, is_late=late)
        db.add(s)
        db.flush()
        db.add(SubmissionFile(submission_id=s.id, file_id=f.id, version=1))
        db.add(SubmissionEvent(submission_id=s.id, actor_id=student.id, action="submitted" if final else "saved",
                               details={"version": 1}))
        if score is not None:
            teacher = db.get(User, a.created_by)
            s.status, s.score, s.graded_by, s.graded_at = "reviewed", score, teacher.id, now - timedelta(days=3)
            s.feedback = rnd.choice(["عمل جيد، انتبه لتنسيق الشيفرة.", "حل صحيح ومنظم.",
                                     "راجع التمرين 7، توجد أخطاء في الشروط."])
            s.grade_released = release
        return s

    for i, st in enumerate(students[:10]):
        if i in (8, 9):
            continue  # two students did not submit
        submission(a1, st, late=(i == 7), score=round(rnd.uniform(4, 10)), release=True)
    for st in students[1:4]:
        submission(a2, st)
    submission(a2, students[4], final=False)
    for i, st in enumerate(students[4:12]):
        if i < 6:
            submission(a4, st, score=round(rnd.uniform(5, 10)), release=True)

    # ----- attendance history (CS101: 6 past lectures; student #9 often absent)
    for k in range(6, 0, -1):
        start = now - timedelta(days=3 * k, hours=2)
        s = AttendanceSession(university_id=uni.id, faculty_id=it.id, kind="course", course_id=cs101.id,
                              title=f"محاضرة {cs101.title} #{7 - k}", location="A101", latitude=31.8686,
                              longitude=10.9813, radius_m=150, starts_at=start, ends_at=start + timedelta(minutes=90),
                              secret=attendance.new_secret(), created_by=t_ahmed.id)
        db.add(s)
        db.flush()
        for i, st in enumerate(students[:10]):
            roll = rnd.random()
            if i == 8 and k % 3 != 0:
                continue  # frequent absence -> threshold alerts on close
            if roll < 0.08:
                continue
            status = "late" if roll < 0.2 else "present"
            rec = AttendanceRecord(university_id=uni.id, session_id=s.id, user_id=st.id, status=status,
                                   initial_status=status, method="qr",
                                   check_in_at=start + timedelta(minutes=20 if status == "late" else rnd.randint(0, 9)),
                                   device_id=f"demo-device-{st.id}", risk_score=0, risk_flags=[],
                                   created_at=start + timedelta(minutes=5))
            attendance._seal(db, rec)
        attendance.close_session(db, s)

    # ----- staff attendance (yesterday)
    ys = (now - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    staff_session = AttendanceSession(university_id=uni.id, faculty_id=it.id, kind="staff", title="دوام الموظفين — المدخل الرئيسي",
                                      location="المبنى الإداري", starts_at=ys, ends_at=ys + timedelta(hours=8),
                                      secret=attendance.new_secret(), created_by=dean_it.id)
    db.add(staff_session)
    db.flush()
    for u, minutes, hours in ((registrar, 5, 7.5), (t_ahmed, 25, 6), (t_salma, 0, 7)):
        status = "late" if minutes > 15 else "present"
        rec = AttendanceRecord(university_id=uni.id, session_id=staff_session.id, user_id=u.id, status=status,
                               initial_status=status, method="qr", check_in_at=ys + timedelta(minutes=minutes),
                               check_out_at=ys + timedelta(minutes=minutes, hours=hours),
                               device_id=f"demo-device-{u.id}", risk_score=0, risk_flags=[], created_at=ys)
        attendance._seal(db, rec)
    attendance.close_session(db, staff_session)

    # ----- notifications
    notifications.create(db, sender=president, university_id=uni.id, category="announcement", priority="important",
                         title="بدء التسجيل للفصل الربيعي", body="يبدأ التسجيل للفصل الربيعي يوم الأحد القادم عبر المنصة.",
                         target_type="university", target_ids=[], audience="all")
    notifications.create(db, sender=dean_it, university_id=uni.id, category="announcement", priority="normal",
                         title="محاضرة عامة: الأمن السيبراني", body="تدعوكم الكلية لحضور محاضرة عامة يوم الخميس في القاعة الكبرى.",
                         target_type="faculty", target_ids=[it.id], audience="all")
    notifications.create(db, sender=t_ahmed, university_id=uni.id, category="academic_note", priority="normal",
                         title="ملاحظة حول الواجب الأول", body="أحسنت في الواجب الأول، ركز على تمارين الحلقات في المشروع.",
                         target_type="user", target_ids=[students[0].id])

    # ----- a service request and a conversation
    req = ServiceRequest(university_id=uni.id, faculty_id=it.id, requester_id=students[0].id,
                         type="enrollment_certificate", office="registrar", subject="إفادة قيد لتقديمها لجهة العمل",
                         details="أرجو إصدار إفادة قيد باللغة العربية.")
    db.add(req)
    db.flush()
    db.add(ServiceRequestEvent(request_id=req.id, actor_id=students[0].id, action="submitted", status="submitted"))
    conv = Conversation(university_id=uni.id, kind="course", course_id=cs101.id, subject="استفسار عن المشروع",
                        created_by=students[0].id)
    db.add(conv)
    db.flush()
    db.add_all([ConversationParticipant(conversation_id=conv.id, user_id=students[0].id, last_read_at=now),
                ConversationParticipant(conversation_id=conv.id, user_id=t_ahmed.id)])
    db.add(Message(conversation_id=conv.id, sender_id=students[0].id,
                   body="دكتور، هل يمكن تنفيذ المشروع بلغة بايثون؟", created_at=now - timedelta(hours=3)))
    db.add(Message(conversation_id=conv.id, sender_id=t_ahmed.id,
                   body="نعم، بايثون مقبولة. أرفق ملف التشغيل مع التقرير.", created_at=now - timedelta(hours=2)))
    conv.last_message_at = now - timedelta(hours=2)

    # ----- second university (tenant isolation demo)
    other = University(code="demo2", name="جامعة تجريبية ثانية", settings={"security": {"require_mfa_for_admins": False}})
    db.add(other)
    db.flush()
    of = Faculty(university_id=other.id, name="كلية العلوم", code="SCI", settings={})
    db.add(of)
    db.flush()
    od = Department(university_id=other.id, faculty_id=of.id, name="الرياضيات", code="MATH")
    db.add(od)
    db.flush()
    _user(db, other, Role.UNIVERSITY_ADMIN, "إدارة الجامعة الثانية", "admin@demo2.edu.ly", code="X1")
    ot = _user(db, other, Role.TEACHER, "د. أستاذ الجامعة الثانية", "teacher@demo2.edu.ly", code="X2", faculty=of, dept=od)
    ost = _user(db, other, Role.STUDENT, "طالب الجامعة الثانية", "student@demo2.edu.ly", code="2023001", faculty=of,
                dept=od, cohort="2023")
    oc = Course(university_id=other.id, faculty_id=of.id, department_id=od.id, code="MATH101", title="تفاضل وتكامل",
                schedule=[])
    db.add(oc)
    db.flush()
    db.add(CourseStaff(course_id=oc.id, user_id=ot.id))
    db.add(Enrollment(course_id=oc.id, student_id=ost.id))

    audit.record(db, "system.seeded", university_id=uni.id, details={"note": "demo data"})


def main(argv: list[str]) -> None:
    if settings.is_production:
        raise SystemExit("refusing to seed demo data in production")
    if "--reset" in argv:
        Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:
        if db.scalar(select(University.id).where(University.code == "nalut")):
            print("demo data already present (use --reset to recreate)")
            return
        seed(db)
        db.commit()
    finally:
        db.close()
    print("Demo data created. Password for all demo accounts:", DEMO_PASSWORD)
    for email, role in [("platform@demo.ly", "مشرف المنصة"), ("president@nalut.edu.ly", "إدارة الجامعة"),
                        ("dean.it@nalut.edu.ly", "إدارة كلية تقنية المعلومات"), ("registrar@nalut.edu.ly", "موظف التسجيل"),
                        ("t.ahmed@nalut.edu.ly", "عضو هيئة تدريس"), ("ta.omar@nalut.edu.ly", "معيد"),
                        ("s.ali@nalut.edu.ly", "طالب"), ("student@demo2.edu.ly", "طالب في جامعة أخرى")]:
        print(f"  {email:28} {role}")


if __name__ == "__main__":
    main(sys.argv[1:])
