import {
  html, useState, useAsync, Async, Empty, Chip, StatusChip, ErrorBox, useSubmit, toast, toastError, Tabs,
  RESULT_STATUS, fmtDate, useCourses, navigate,
} from "../ui.js";
import { api } from "../api.js";

function StudentGrades() {
  const state = useAsync(() => api.get("/api/me/grades"), []);
  return html`<${Async} state=${state}>${(list) => html`<div>
    ${list.map((g) => html`<div class="card">
      <div class="card-head"><h3>${g.course.code} — ${g.course.title}</h3>
        ${g.published ? html`<${Chip} kind=${g.passed ? "success" : "danger"}>${g.letter ? `${g.letter} · ${g.label}` : "غير مكتملة"}<//>`
          : html`<${Chip}>لم تُعتمد بعد<//>`}</div>
      ${g.published ? html`<div class="table-wrap"><table><tbody>
        ${g.components.map((c) => html`<tr><td>${c.name}</td><td class="num">${g.scores[c.id] ?? "—"} / ${c.max_score}</td></tr>`)}
        <tr><th>المجموع</th><th class="num">${g.total} / ${g.max_total} (${g.percent}%)</th></tr></tbody></table></div>`
        : html`<p class="small muted">تظهر النتائج بعد اعتمادها ونشرها رسمياً من إدارة الكلية.</p>`}
    </div>`)}
    ${!list.length ? html`<${Empty} />` : null}</div>`}<//>`;
}

function ImportBox({ courseId, onDone }) {
  const [preview, setPreview] = useState(null);
  const [upload, busy, error] = useSubmit(async (file) => {
    const fd = new FormData();
    fd.append("upload", file);
    setPreview(await api.form(`/api/courses/${courseId}/grades/import`, fd));
  });
  const [commit, busy2, error2] = useSubmit(async () => {
    const r = await api.post(`/api/grade-imports/${preview.id}/commit`);
    toast(`تم استيراد ${r.changed} درجة`);
    setPreview(null);
    onDone();
  });
  return html`<div class="card"><h3>استيراد من CSV أو Excel</h3>
    <p class="small muted">الصف الأول: <span class="mono">student_number</span> ثم أسماء عناصر التقييم كما هي في المقرر. تُفحص البيانات قبل الاعتماد.</p>
    <${ErrorBox} error=${error || error2} />
    <input type="file" accept=".csv,.xlsx" disabled=${busy} onChange=${(e) => e.target.files[0] && upload(e.target.files[0])} />
    ${preview ? html`<div style="margin-top:.75rem">
      <p>${preview.rows.length} صف صالح · ${preview.errors.length} خطأ</p>
      ${preview.errors.length ? html`<div class="alert error"><ul>${preview.errors.map((e) => html`<li>سطر ${e.row}: ${e.error}</li>`)}</ul></div>` : null}
      <button disabled=${!preview.can_commit || busy2} onClick=${commit}>اعتماد الاستيراد</button></div>` : null}
  </div>`;
}

function History({ courseId }) {
  const state = useAsync(() => api.get(`/api/courses/${courseId}/grades/history`), [courseId]);
  return html`<div class="card"><h3>سجل تعديلات الدرجات</h3><${Async} state=${state}>${(rows) => rows.length ? html`
    <div class="table-wrap"><table><thead><tr><th>الوقت</th><th>الطالب</th><th>العنصر</th><th class="num">من</th><th class="num">إلى</th><th>السبب</th><th>بواسطة</th></tr></thead>
    <tbody>${rows.map((r) => html`<tr><td class="small">${fmtDate(r.created_at)}</td><td>${r.student}</td><td>${r.component}</td>
      <td class="num">${r.old ?? "—"}</td><td class="num">${r.new ?? "—"}</td><td class="small">${r.reason}</td><td class="small">${r.actor}</td></tr>`)}</tbody></table></div>`
    : html`<${Empty} />`}<//></div>`;
}

function CourseGrades({ courseId }) {
  const state = useAsync(() => api.get(`/api/courses/${courseId}/grades`), [courseId]);
  const [edits, setEdits] = useState({});
  const [reason, setReason] = useState("");
  const [tab, setTab] = useState("grid");
  const [save, busy, error] = useSubmit(async () => {
    const entries = Object.entries(edits).map(([k, v]) => {
      const [student_id, component_id] = k.split(":").map(Number);
      return { student_id, component_id, score: v === "" ? null : Number(v) };
    });
    const r = await api.put(`/api/courses/${courseId}/grades`, { entries, reason });
    toast(`تم حفظ ${r.changed} تعديل`);
    setEdits({});
    setReason("");
    state.reload();
  });
  const submitForApproval = async () => {
    if (!confirm("رفع النتائج لإدارة الكلية للاعتماد؟ لن تتمكن من التعديل بعدها إلا إذا أُعيدت إليك.")) return;
    await api.post(`/api/courses/${courseId}/results/submit`, {}).catch(toastError);
    state.reload();
  };
  return html`<${Async} state=${state}>${(g) => {
    const editable = g.result.status === "draft";
    return html`<div>
      <div class="row between"><h2>${g.course.code} — ${g.course.title}</h2><${StatusChip} map=${RESULT_STATUS} value=${g.result.status} /></div>
      ${g.result.note ? html`<div class="alert info">ملاحظة: ${g.result.note}</div>` : null}
      <${Tabs} value=${tab} onChange=${setTab} tabs=${[["grid", "رصد الدرجات"], ["import", "استيراد"], ["history", "سجل التعديلات"]]} />
      ${tab === "grid" ? html`<div class="card">
        <${ErrorBox} error=${error} />
        <div class="table-wrap"><table><thead><tr><th>الطالب</th>${g.components.map((c) => html`<th class="num">${c.name}<div class="small">/${c.max_score}</div></th>`)}
          <th class="num">المجموع</th><th>التقدير</th></tr></thead>
        <tbody>${g.students.map((s) => html`<tr><td>${s.full_name}<div class="small muted mono">${s.code}</div></td>
          ${g.components.map((c) => {
            const key = `${s.id}:${c.id}`;
            const val = key in edits ? edits[key] : (s.scores[c.id] ?? "");
            return html`<td class="num"><input type="number" min="0" max=${c.max_score} step="0.25" disabled=${!editable}
              value=${val} onInput=${(e) => setEdits({ ...edits, [key]: e.target.value })} aria-label=${`${c.name} ${s.full_name}`} /></td>`;
          })}
          <td class="num">${s.total} <span class="small muted">(${s.percent}%)</span></td>
          <td>${s.letter ? html`<${Chip} kind=${s.passed ? "success" : "danger"}>${s.letter}<//>` : "—"}</td></tr>`)}</tbody></table></div>
        ${editable ? html`<div class="row" style="margin-top:.75rem">
          <input style="max-width:340px" placeholder="سبب التعديل (إلزامي عند تغيير درجة مرصودة)" value=${reason} onInput=${(e) => setReason(e.target.value)} />
          <button disabled=${busy || !Object.keys(edits).length} onClick=${save}>حفظ التعديلات</button>
          <span class="spacer"></span>
          <button class="secondary" onClick=${submitForApproval}>رفع للاعتماد</button></div>`
          : html`<p class="small muted">النتائج مقفلة للتعديل في هذه المرحلة.</p>`}
      </div>` : null}
      ${tab === "import" ? (editable ? html`<${ImportBox} courseId=${courseId} onDone=${state.reload} />` : html`<div class="card muted">الاستيراد متاح في حالة المسودة فقط.</div>`) : null}
      ${tab === "history" ? html`<${History} courseId=${courseId} />` : null}
    </div>`;
  }}<//>`;
}

export function GradesView({ user, courseId }) {
  const courses = useCourses();
  if (user.role === "student") return html`<div><h1>درجاتي ونتائجي</h1><${StudentGrades} /></div>`;
  const selected = courseId || courses.data?.[0]?.id;
  return html`<div><h1>الدرجات والنتائج</h1>
    <div class="field" style="max-width:420px"><select value=${selected || ""} onChange=${(e) => navigate(`#/grades/${e.target.value}`)}>
      <option value="">اختر المقرر…</option>${(courses.data || []).map((c) => html`<option value=${c.id}>${c.code} — ${c.title}</option>`)}</select></div>
    ${selected ? html`<${CourseGrades} courseId=${selected} />` : null}</div>`;
}

export function ResultsApproval() {
  const state = useAsync(() => api.get("/api/results/pending"), []);
  const act = async (courseId, action, needNote) => {
    let note = "";
    if (needNote) {
      note = prompt("اذكر السبب أو الملاحظات:") || "";
      if (note.trim().length < 3) return;
    }
    try {
      await api.post(`/api/courses/${courseId}/results/${action}`, { note });
      toast("تم");
      state.reload();
    } catch (e) { toastError(e); }
  };
  return html`<div><h1>اعتماد ونشر النتائج</h1>
    <p class="muted">لا تظهر النتائج للطلبة إلا بعد المرور بمراحل: رفع الأستاذ ← اعتماد الإدارة ← النشر.</p>
    <${Async} state=${state}>${(rows) => html`<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>المقرر</th><th>الحالة</th><th>آخر تحديث</th><th></th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td><a href=${`#/grades/${r.course.id}`}>${r.course.code} — ${r.course.title}</a></td>
        <td><${StatusChip} map=${RESULT_STATUS} value=${r.status} /></td>
        <td class="small">${fmtDate(r.published_at || r.approved_at || r.submitted_at)}</td>
        <td><div class="row">
          ${r.status === "submitted" ? html`<button class="small" onClick=${() => act(r.course.id, "approve")}>اعتماد</button>` : null}
          ${r.status === "approved" ? html`<button class="small" onClick=${() => act(r.course.id, "publish")}>نشر للطلبة</button>` : null}
          ${r.status !== "draft" ? html`<button class="small secondary" onClick=${() => act(r.course.id, "return", true)}>${r.status === "published" ? "إعادة فتح" : "إرجاع للأستاذ"}</button>` : null}
        </div></td></tr>`)}</tbody></table></div></div>`}<//></div>`;
}
