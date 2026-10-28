import { html, useState, useAsync, Async, Empty, Chip, Kpi, Bar, Tabs, StatusChip, RESULT_STATUS, pct, toastError } from "../ui.js";
import { api, request } from "../api.js";

function Overview({ user }) {
  const state = useAsync(() => api.get("/api/reports/overview"), []);
  return html`<${Async} state=${state}>${(r) => html`<div>
    <div class="kpis">
      ${user.role !== "teacher" && user.role !== "assistant" ? html`<${Kpi} label="الطلبة" value=${r.people.students} />` : null}
      <${Kpi} label="المقررات" value=${r.totals.courses} /><${Kpi} label="تسجيلات الطلبة في المقررات" value=${r.totals.enrolments} />
      <${Kpi} label="نسبة الحضور" value=${pct(r.totals.attendance_rate)} hint="آخر 30 يوماً" />
      <${Kpi} label="نسبة تسليم المهام" value=${pct(r.totals.submission_rate)} />
      <${Kpi} label="متوسط درجات المهام" value=${pct(r.totals.avg_score_percent)} />
    </div>
    ${r.breakdown.length ? html`<div class="card"><h3>${user.role === "university_admin" ? "الحضور حسب الكلية" : "الحضور حسب القسم"}</h3>
      <div class="hbars">${r.breakdown.map((b) => html`<div class="hbar"><span>${b.name}</span><${Bar} value=${b.attendance_rate} warnBelow=${80} badBelow=${65} /><span>${pct(b.attendance_rate)}</span></div>`)}</div></div>` : null}
    <div class="card"><h3>المقررات</h3><div class="table-wrap"><table>
      <thead><tr><th>المقرر</th><th class="num">الطلبة</th><th class="num">المحاضرات</th><th class="num">نسبة الحضور</th>
        <th class="num">مرات التأخير</th><th class="num">مرات الغياب</th><th class="num">نسبة التسليم</th><th class="num">متوسط الدرجات</th><th>النتائج</th></tr></thead>
      <tbody>${r.courses.map((c) => html`<tr><td>${c.course.code} — ${c.course.title}</td><td class="num">${c.enrolled}</td><td class="num">${c.sessions}</td>
        <td class="num">${pct(c.attendance_rate)}</td><td class="num">${c.late}</td><td class="num">${c.absent}</td><td class="num">${pct(c.submission_rate)}</td>
        <td class="num">${pct(c.avg_score_percent)}</td><td><${StatusChip} map=${RESULT_STATUS} value=${c.result_status} /></td></tr>`)}</tbody></table></div>
      <p class="small muted">مرات الغياب والتأخير مجموعة على كل المحاضرات وكل الطلبة (مثلاً 10 طلبة × 7 محاضرات = 70 حالة حضور).
        التسجيلات = مجموع تسجيل الطلبة في المقررات: الطالب المسجل في 3 مقررات يُحسب 3 مرات.</p></div>
  </div>`}<//>`;
}

function AtRisk() {
  const state = useAsync(() => api.get("/api/reports/at-risk"), []);
  return html`<div class="card"><h3>طلبة يحتاجون إلى متابعة</h3>
    <p class="small muted">مؤشرات وفق معايير المؤسسة (الغياب، المهام غير المسلمة، انخفاض الدرجات) لمساعدة المرشد الأكاديمي. لا تترتب عليها أي عقوبة تلقائية.</p>
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="table-wrap"><table>
      <thead><tr><th>الطالب</th><th>المقرر</th><th>المؤشرات</th><th></th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td>${r.student.full_name}<div class="small muted mono">${r.student.code}</div></td><td>${r.course.code}</td>
        <td><div class="row">${r.reasons.map((x) => html`<${Chip} kind="warning">${x}<//>`)}</div></td>
        <td><a class="btn small secondary" href="#/notifications/send">إرسال ملاحظة</a></td></tr>`)}</tbody></table></div>` : html`<${Empty}>لا توجد حالات<//>`}<//></div>`;
}

function AttendanceTrend() {
  const courses = useAsync(() => api.get("/api/courses"), []);
  const [course, setCourse] = useState("");
  const [period, setPeriod] = useState("day");
  const qs = `period=${period}&days=90${course ? `&course_id=${course}` : ""}`;
  const state = useAsync(() => api.get(`/api/reports/attendance?${qs}`), [qs]);
  const exportCsv = async () => {
    try {
      const res = await request("GET", `/api/reports/attendance?${qs}&format=csv`, { raw: true });
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "attendance-report.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 3000);
    } catch (e) { toastError(e); }
  };
  return html`<div class="card"><div class="card-head"><h3>تقرير الحضور</h3><button class="small secondary" onClick=${exportCsv}>تصدير CSV</button></div>
    <div class="row" style="margin-bottom:.75rem">
      <select style="max-width:260px" value=${course} onChange=${(e) => setCourse(e.target.value)}><option value="">كل المقررات</option>
        ${(courses.data || []).map((c) => html`<option value=${c.id}>${c.code} — ${c.title}</option>`)}</select>
      <select style="max-width:160px" value=${period} onChange=${(e) => setPeriod(e.target.value)}>
        <option value="day">يومي</option><option value="week">أسبوعي</option><option value="month">شهري</option></select></div>
    <${Async} state=${state}>${(rows) => rows.length ? html`<div>
      <div class="vbars" role="img" aria-label="نسبة الحضور حسب الفترة">${rows.map((r) => html`<div class="col" title=${`${r.period}: ${pct(r.rate)}`}>
        <small>${pct(r.rate)}</small><span class="b" style=${`height:${(r.rate || 0) * 1.2}px`}></span><small class="ltr">${r.period.slice(5)}</small></div>`)}</div>
      <div class="table-wrap"><table><thead><tr><th>الفترة</th><th class="num">حضور</th><th class="num">تأخير</th><th class="num">غياب</th><th class="num">بعذر</th><th class="num">مراجعة</th><th class="num">النسبة</th></tr></thead>
        <tbody>${rows.map((r) => html`<tr><td class="ltr">${r.period}</td><td class="num">${r.present}</td><td class="num">${r.late}</td><td class="num">${r.absent}</td>
          <td class="num">${r.excused}</td><td class="num">${r.pending}</td><td class="num">${pct(r.rate)}</td></tr>`)}</tbody></table></div></div>` : html`<${Empty} />`}<//></div>`;
}

function StaffAttendance() {
  const state = useAsync(() => api.get("/api/reports/staff-attendance?days=30"), []);
  return html`<div class="card"><h3>دوام الموظفين (30 يوماً)</h3><${Async} state=${state}>${(rows) => rows.length ? html`<div class="table-wrap"><table>
    <thead><tr><th>الموظف</th><th class="num">أيام الحضور</th><th class="num">التأخير</th><th class="num">ساعات العمل</th></tr></thead>
    <tbody>${rows.map((r) => html`<tr><td>${r.user.full_name}</td><td class="num">${r.days}</td><td class="num">${r.late}</td><td class="num">${r.hours}</td></tr>`)}</tbody></table></div>`
    : html`<${Empty} />`}<//></div>`;
}

export function ReportsView({ user }) {
  const admin = (user.can || []).includes("attendance.staff");
  const [tab, setTab] = useState("overview");
  const tabs = [["overview", "نظرة عامة"], ["risk", "متابعة الطلبة"], ["attendance", "الحضور"], ...(admin ? [["staff", "دوام الموظفين"]] : [])];
  return html`<div><h1>التقارير والإحصائيات</h1><${Tabs} value=${tab} onChange=${setTab} tabs=${tabs} />
    ${tab === "overview" ? html`<${Overview} user=${user} />` : null}
    ${tab === "risk" ? html`<${AtRisk} />` : null}
    ${tab === "attendance" ? html`<${AttendanceTrend} />` : null}
    ${tab === "staff" ? html`<${StaffAttendance} />` : null}</div>`;
}
