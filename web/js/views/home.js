import { html, useAsync, Async, Kpi, Bar, Empty, Chip, StatusChip, RESULT_STATUS, DAYS, fmtDate, fmtRelative, pct, Icon } from "../ui.js";
import { api } from "../api.js";

function Schedule({ slots }) {
  if (!slots.length) return html`<${Empty}>لا يوجد جدول<//>`;
  const days = [...new Set(slots.map((s) => s.day))];
  // Saturday = 0 in the platform's convention
  const today = (new Date().getDay() + 1) % 7;
  return html`<div>${days.map((d) => html`<div class="schedule-day">
    <strong>${DAYS[d]}</strong> ${d === today ? html`<${Chip} kind="primary">اليوم<//>` : null}
    ${slots.filter((s) => s.day === d).map((s) => html`<div class="slot">
      <span>${s.title} <span class="muted small">${s.code}</span></span>
      <span class="ltr small">${s.start}–${s.end} · ${s.room}</span></div>`)}
  </div>`)}</div>`;
}

function StudentHome() {
  const state = useAsync(() => Promise.all([
    api.get("/api/me/insights"), api.get("/api/me/schedule"), api.get("/api/notifications?limit=5"),
    api.get("/api/me/attendance"), api.get("/api/assignments"),
  ]), []);
  return html`<${Async} state=${state}>${([ins, schedule, notes, att, assignments]) => {
    const open = assignments.filter((a) => ["not_started", "in_progress"].includes(a.my_status));
    const worst = att.courses.reduce((m, c) => Math.max(m, c.absence_percent), 0);
    return html`
      <a class="btn big" href="#/attendance/scan" style="margin-bottom:1rem;width:100%"><${Icon} name="camera" size=${18} />تسجيل الحضور بمسح الرمز</a>
      <div class="kpis">
        <${Kpi} label="إشعارات غير مقروءة" value=${notes.unread} />
        <${Kpi} label="مهام مفتوحة" value=${open.length} />
        <${Kpi} label="أعلى نسبة غياب" value=${pct(worst)} />
      </div>
      ${ins.attention.length ? html`<div class="card"><h2>تحتاج إلى اهتمامك</h2><ul class="list">
        ${ins.attention.map((t) => html`<li><strong>${t.course.title}</strong>
          <div class="row">${t.reasons.map((r) => html`<${Chip} kind="warning">${r}<//>`)}</div></li>`)}</ul>
        <p class="small muted">مؤشرات مساعدة لتنظيم وقتك، وليست قرارات رسمية.</p></div>` : null}
      <div class="grid cols-2">
        <div class="card"><div class="card-head"><h2>مواعيد تسليم قريبة</h2><a href="#/assignments">الكل</a></div>
          ${ins.due_soon.length ? html`<ul class="list">${ins.due_soon.map((a) => html`<li>
            <a class="item-link" href=${`#/assignments/${a.id}`}><strong>${a.title}</strong>
            <div class="small muted">${a.course} · ${fmtRelative(a.due_at)}</div></a></li>`)}</ul>`
            : html`<${Empty}>لا توجد مهام مستحقة هذا الأسبوع<//>`}</div>
        <div class="card"><h2>جدولي الدراسي</h2><${Schedule} slots=${schedule} /></div>
      </div>
      <div class="card"><div class="card-head"><h2>آخر الإشعارات</h2><a href="#/notifications">الكل</a></div>
        ${notes.items.length ? html`<ul class="list">${notes.items.map((n) => html`<li>
          <strong>${n.title}</strong> <span class="small muted">${fmtRelative(n.created_at, true)}</span>
          <div class="small">${n.body}</div></li>`)}</ul>` : html`<${Empty} />`}</div>
      <div class="card"><h2>الحضور حسب المقرر</h2>
        <div class="hbars">${att.courses.map((c) => html`<div class="hbar"><span>${c.course.title}</span>
          <${Bar} value=${c.absence_percent} warnAbove=${15} badAbove=${25} /><span class="small">${pct(c.absence_percent)} غياب</span></div>`)}</div>
      </div>`;
  }}<//>`;
}

function InstructorHome() {
  const state = useAsync(() => Promise.all([
    api.get("/api/courses"), api.get("/api/assignments"), api.get("/api/attendance/review-queue"),
    api.get("/api/me/schedule"),
  ]), []);
  return html`<${Async} state=${state}>${([courses, assignments, queue, schedule]) => {
    const toReview = assignments.reduce((n, a) => n + (a.stats.submitted - a.stats.reviewed), 0);
    return html`
      <div class="kpis">
        <${Kpi} label="مقرراتي" value=${courses.length} />
        <${Kpi} label="تسليمات بانتظار التقييم" value=${toReview} />
        <${Kpi} label="تسجيلات حضور للمراجعة" value=${queue.length} />
      </div>
      <div class="row" style="margin-bottom:1rem">
        <a class="btn" href="#/attendance"><${Icon} name="camera" size=${18} />بدء جلسة حضور</a>
        <a class="btn secondary" href="#/assignments"><${Icon} name="assignments" size=${18} />إنشاء مهمة</a>
        <a class="btn secondary" href="#/notifications/send"><${Icon} name="megaphone" size=${18} />إرسال إعلان</a>
      </div>
      <div class="grid cols-2">
        <div class="card"><h2>مقرراتي</h2><ul class="list">${courses.map((c) => html`<li>
          <a class="item-link" href=${`#/courses/${c.id}`}><strong>${c.code} — ${c.title}</strong>
          <div class="small muted">${c.students_count} طالب</div></a></li>`)}</ul></div>
        <div class="card"><h2>جدول المحاضرات</h2><${Schedule} slots=${schedule} /></div>
      </div>
      <div class="card"><div class="card-head"><h2>المهام الحالية</h2><a href="#/assignments">الكل</a></div>
        ${assignments.length ? html`<ul class="list">${assignments.slice(0, 6).map((a) => html`<li>
          <a class="item-link" href=${`#/assignments/${a.id}`}><div class="row between"><strong>${a.title}</strong>
          <span class="small muted">${a.course_code} · ${fmtDate(a.due_at)}</span></div>
          <div class="small muted">سلّم ${a.stats.submitted} من ${a.stats.enrolled} · قُيّم ${a.stats.reviewed}</div></a></li>`)}</ul>`
          : html`<${Empty} />`}</div>`;
  }}<//>`;
}

function AdminHome({ user }) {
  const state = useAsync(() => api.get("/api/reports/overview"), []);
  return html`<${Async} state=${state}>${(r) => html`
    <div class="kpis">
      <${Kpi} label="الطلبة" value=${r.people.students} />
      <${Kpi} label="هيئة التدريس" value=${r.people.teaching} />
      <${Kpi} label="الموظفون والإدارة" value=${r.people.staff} />
      <${Kpi} label="المقررات" value=${r.totals.courses} />
      <${Kpi} label="نسبة الحضور (30 يوماً)" value=${pct(r.totals.attendance_rate)} />
      <${Kpi} label="نسبة تسليم المهام" value=${pct(r.totals.submission_rate)} />
    </div>
    <div class="row" style="margin-bottom:1rem">
      <a class="btn" href="#/notifications/send"><${Icon} name="megaphone" size=${18} />إرسال إعلان أو تحذير</a>
      <a class="btn secondary" href="#/results"><${Icon} name="results" size=${18} />نتائج بانتظار الاعتماد (${r.results_awaiting_approval})</a>
      <a class="btn secondary" href="#/attendance"><${Icon} name="search" size=${18} />مراجعات الحضور (${r.pending_attendance_reviews})</a>
      <a class="btn secondary" href="#/requests"><${Icon} name="requests" size=${18} />طلبات مفتوحة (${r.open_requests ?? 0})</a>
    </div>
    ${r.breakdown.length ? html`<div class="card"><h2>${user.role === "university_admin" ? "مقارنة الكليات" : "مقارنة الأقسام"}</h2>
      <div class="table-wrap"><table><thead><tr><th>${user.role === "university_admin" ? "الكلية" : "القسم"}</th>
        <th class="num">الطلبة</th><th class="num">المقررات</th><th>الحضور</th><th>تسليم المهام</th></tr></thead>
        <tbody>${r.breakdown.map((b) => html`<tr><td>${b.name}</td><td class="num">${b.students}</td><td class="num">${b.courses}</td>
          <td><div class="row"><div style="flex:1"><${Bar} value=${b.attendance_rate} warnBelow=${80} badBelow=${65} /></div><span class="small">${pct(b.attendance_rate)}</span></div></td>
          <td><div class="row"><div style="flex:1"><${Bar} value=${b.submission_rate} warnBelow=${75} badBelow=${50} /></div><span class="small">${pct(b.submission_rate)}</span></div></td></tr>`)}
        </tbody></table></div></div>` : null}
    <div class="card"><div class="card-head"><h2>المقررات</h2><a href="#/reports">التقارير التفصيلية</a></div>
      <div class="table-wrap"><table><thead><tr><th>المقرر</th><th class="num">الطلبة</th><th class="num">الحضور</th>
        <th class="num">التسليم</th><th class="num">متوسط الدرجات</th><th>النتائج</th></tr></thead>
        <tbody>${r.courses.map((c) => html`<tr><td>${c.course.code} — ${c.course.title}</td><td class="num">${c.enrolled}</td>
          <td class="num">${pct(c.attendance_rate)}</td><td class="num">${pct(c.submission_rate)}</td><td class="num">${pct(c.avg_score_percent)}</td>
          <td><${StatusChip} map=${RESULT_STATUS} value=${c.result_status} /></td></tr>`)}
        </tbody></table></div></div>`}<//>`;
}

function StaffHome() {
  const state = useAsync(() => Promise.all([api.get("/api/requests?scope=office"), api.get("/api/notifications?limit=5")]), []);
  return html`<${Async} state=${state}>${([reqs, notes]) => {
    const open = reqs.filter((r) => !["approved", "rejected"].includes(r.status));
    return html`
      <a class="btn big" href="#/attendance/scan" style="margin-bottom:1rem;width:100%"><${Icon} name="camera" size=${18} />تسجيل الدوام (دخول / انصراف)</a>
      <div class="kpis"><${Kpi} label="طلبات مفتوحة في مكتبي" value=${open.length} /><${Kpi} label="إشعارات غير مقروءة" value=${notes.unread} /></div>
      <div class="card"><div class="card-head"><h2>أحدث الطلبات</h2><a href="#/requests">الكل</a></div>
        ${open.length ? html`<ul class="list">${open.slice(0, 8).map((r) => html`<li><a class="item-link" href=${`#/requests/${r.id}`}>
          <div class="row between"><strong>${r.type_label}: ${r.subject}</strong><${Chip} kind="warning">${r.status_label}<//></div>
          <div class="small muted">${r.requester.full_name} · ${fmtRelative(r.created_at, true)}</div></a></li>`)}</ul>` : html`<${Empty} />`}</div>`;
  }}<//>`;
}

export function Home({ user }) {
  const r = user.role;
  if (r === "platform_admin") {
    return html`<div class="card"><h2>مرحباً ${user.full_name}</h2>
      <p>يدير مشرف المنصة الجامعات المشتركة وحالتها فقط، ولا يطّلع على البيانات الأكاديمية داخل كل جامعة.</p>
      <a class="btn" href="#/universities">إدارة الجامعات</a></div>`;
  }
  return html`<div>
    <h1>مرحباً، ${user.full_name.split(" (")[0]}</h1>
    ${r === "student" ? html`<${StudentHome} />` : null}
    ${r === "teacher" || r === "assistant" ? html`<${InstructorHome} />` : null}
    ${r === "faculty_admin" || r === "university_admin" ? html`<${AdminHome} user=${user} />` : null}
    ${r === "staff" ? html`<${StaffHome} />` : null}
  </div>`;
}

