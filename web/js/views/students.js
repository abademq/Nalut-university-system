import { PlanCard, StandingManager } from "./plan.js";
import { TranscriptCard } from "./transcript.js";
import { AcademicSummary } from "./courses.js";
import { html, useState, useAsync, Async, Empty, Chip, Kpi, navigate } from "../ui.js";
import { api } from "../api.js";

// Students section: the students one may follow and, for each, their study situation per course.
// The personal file and document copies stay in the student archive (archive.access).

const pct = (v) => (v === null || v === undefined ? "—" : `${v}%`);

export function StudentsList() {
  const [q, setQ] = useState("");
  const [cohort, setCohort] = useState("");
  const state = useAsync(() => api.get(`/api/students?limit=1000&q=${encodeURIComponent(q)}&cohort=${encodeURIComponent(cohort)}`), [q, cohort]);
  return html`<div><h1>الطلبة</h1>
    <p class="muted">قائمة الطلبة ووضع كل طالب الدراسي: الحضور والمهام والدرجات في كل مقرر.</p>
    <div class="row" style="margin-bottom:.75rem">
      <input style="max-width:300px" placeholder="بحث بالاسم أو رقم القيد أو البريد أو الهاتف" value=${q} onInput=${(e) => setQ(e.target.value)} />
      ${state.data?.cohorts?.length ? html`<select style="max-width:160px" value=${cohort} onChange=${(e) => setCohort(e.target.value)}>
        <option value="">كل الدفعات</option>${state.data.cohorts.map((c) => html`<option value=${c}>دفعة ${c}</option>`)}</select>` : null}</div>
    <${Async} state=${state}>${(d) => d.items.length ? html`<div class="card"><p class="small muted">${d.total} طالب</p>
      <div class="table-wrap"><table>
      <thead><tr><th>الطالب</th><th>رقم القيد</th><th>الكلية</th><th>القسم</th><th>الدفعة</th><th class="num">المقررات</th><th>التواصل</th></tr></thead>
      <tbody>${d.items.map((s) => html`<tr style="cursor:pointer" onClick=${() => navigate(`#/students/${s.id}`)}>
        <td><a href=${`#/students/${s.id}`}>${s.full_name}</a>${s.is_active ? null : html` <${Chip} kind="danger">موقوف<//>`}</td>
        <td class="mono">${s.code || ""}</td><td>${s.faculty || "—"}</td><td>${s.department || "—"}</td><td>${s.cohort || "—"}</td>
        <td class="num">${s.courses}</td><td class="small ltr">${s.phone || s.email || ""}</td></tr>`)}</tbody></table></div></div>`
      : html`<${Empty}>لا يوجد طلبة<//>`}<//>
  </div>`;
}

export function StudentDetail({ id, user }) {
  const state = useAsync(() => api.get(`/api/reports/person/${id}`), [id]);
  const archive = (user.can || []).includes("archive.access");
  return html`<${Async} state=${state}>${(d) => {
    const s = d.summary;
    return html`<div>
      <div class="row"><a href="#/students">← الطلبة</a></div>
      <div class="row between"><h1>${d.user.full_name}</h1>
        ${archive ? html`<a class="btn secondary small" href=${`#/archive/${d.user.id}`}>الملف الشخصي والمستندات</a>` : null}</div>
      <p class="muted">${d.user.code ? html`<span class="mono">${d.user.code}</span>` : null}</p>
      ${d.contact ? html`<div class="card"><h3>التواصل</h3><div class="row" style="flex-wrap:wrap">
        ${d.contact.can_message ? html`<a class="btn small" href=${`#/messages?to=${d.user.id}`}>مراسلة في المنصة</a>` : null}
        ${d.contact.phone ? html`<a class="btn small secondary ltr" href=${`tel:${d.contact.phone}`}>${d.contact.phone}</a>` : null}
        ${d.contact.email ? html`<a class="btn small secondary ltr" href=${`mailto:${d.contact.email}`}>${d.contact.email}</a>` : null}</div>
        <p class="small muted">${[d.contact.faculty, d.contact.department, d.contact.cohort ? `دفعة ${d.contact.cohort}` : null].filter(Boolean).join(" · ")}
          ${d.contact.guardian_phone ? html` · ولي الأمر: ${d.contact.guardian_name || ""} ${d.contact.guardian_relation ? `(${d.contact.guardian_relation})` : ""}
            <a class="ltr" href=${`tel:${d.contact.guardian_phone}`}>${d.contact.guardian_phone}</a>` : null}</p></div>` : null}
      <div class="kpis">
        <${Kpi} label="المقررات" value=${s.courses} />
        <${Kpi} label="متوسط الغياب" value=${pct(s.absence_percent)} />
        <${Kpi} label="نسبة تسليم المهام" value=${pct(s.submission_rate)} />
        <${Kpi} label="متوسط درجات المهام" value=${pct(s.avg_score_percent)} />
        <${Kpi} label="تنبيهات" value=${s.alerts} />
      </div>
      <h3>الخطة الدراسية</h3><${StudentPlan} id=${d.user.id} />
      ${d.transcript ? html`<h3>النتائج والمعدل</h3><${TranscriptCard} t=${d.transcript} />` : null}
      ${d.academic ? html`<h3>المقررات والوحدات</h3><${AcademicSummary} a=${d.academic} />` : null}
      <div class="card"><h3>المتابعة في كل مقرر</h3>${d.courses.length ? html`<div class="table-wrap"><table>
        <thead><tr><th>المقرر</th><th class="num">الغياب</th><th class="num">مرات التأخير</th><th class="num">المهام المسلّمة</th>
          <th class="num">متوسط المهام</th><th>النتيجة</th><th>تنبيهات</th></tr></thead>
        <tbody>${d.courses.map((c) => html`<tr><td>${c.course.code} — ${c.course.title}</td>
          <td class="num">${pct(c.absence_percent)} <span class="small muted">(${c.sessions} محاضرة)</span></td>
          <td class="num">${c.late}</td><td class="num">${c.submitted} من ${c.due}</td><td class="num">${pct(c.avg_score_percent)}</td>
          <td>${c.grade ? html`<strong>${c.grade.letter}</strong> <span class="small muted">${pct(c.grade.percent)}</span>`
            : c.running_percent !== null && c.running_percent !== undefined ? html`<span class="small muted">جارٍ: ${pct(c.running_percent)} (لم تُنشر)</span>` : "—"}</td>
          <td>${c.alerts.length ? c.alerts.map((a) => html`<${Chip} kind="warning">${a}<//> `) : html`<span class="muted">—</span>`}</td></tr>`)}</tbody></table></div>`
        : html`<${Empty}>غير مسجل في أي مقرر<//>`}
        <p class="small muted">الغياب نسبة من محاضرات المقرر. النتيجة تظهر بعد اعتمادها ونشرها، وقبل ذلك المجموع الجاري للمختصين فقط.</p></div>
    </div>`;
  }}<//>`;
}

function StudentPlan({ id }) {
  const state = useAsync(() => api.get(`/api/students/${id}/plan`), [id]);
  return html`<${Async} state=${state}>${(p) => html`<${PlanCard} p=${p} />
    ${p.can_manage && p.program ? html`<${StandingManager} studentId=${id} plan=${p} onChange=${state.reload} />` : null}`}<//>`;
}
