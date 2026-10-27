import {
  html, useState, useAsync, Async, Empty, Chip, StatusChip, ErrorBox, useForm, useSubmit, toast, toastError, Modal,
  ASSIGNMENT_STATUS, KIND, fmtDate, fmtRelative, fmtSize, toLocalInput, useCourses, Icon } from "../ui.js";
import { api, downloadFile } from "../api.js";

const isStudent = (u) => u.role === "student";

function CreateAssignment({ onCreated }) {
  const courses = useCourses();
  const [v, bind] = useForm({ course_id: "", title: "", description: "", kind: "homework",
    due_at: toLocalInput(Date.now() + 7 * 86400000), max_score: 10, allow_late: true, exts: "pdf, docx, jpg, png", max_file_mb: 10 });
  const [submit, busy, error] = useSubmit(async () => {
    await api.post(`/api/courses/${v.course_id}/assignments`, {
      title: v.title, description: v.description, kind: v.kind, due_at: new Date(v.due_at).toISOString(),
      max_score: Number(v.max_score), allow_late: v.allow_late, max_file_mb: Number(v.max_file_mb),
      allowed_extensions: v.exts.split(/[\s,،]+/).filter(Boolean),
    });
    toast("تم نشر المهمة وإشعار الطلبة");
    onCreated();
  });
  return html`<form class="card" onSubmit=${submit}><h3>مهمة جديدة</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>المقرر</label><select ...${bind("course_id")} required><option value="">اختر…</option>
        ${(courses.data || []).map((c) => html`<option value=${c.id}>${c.code} — ${c.title}</option>`)}</select></div>
      <div class="field"><label>النوع</label><select ...${bind("kind")}>${Object.entries(KIND).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
      <div class="field"><label>العنوان</label><input ...${bind("title")} required /></div>
      <div class="field"><label>موعد التسليم</label><input type="datetime-local" ...${bind("due_at")} required /></div>
      <div class="field"><label>الدرجة القصوى</label><input type="number" min="1" step="0.5" ...${bind("max_score")} /></div>
      <div class="field"><label>الصيغ المسموحة</label><input class="ltr" ...${bind("exts")} /></div>
      <div class="field"><label>الحجم الأقصى (MB)</label><input type="number" min="1" max="100" ...${bind("max_file_mb")} /></div>
    </div>
    <div class="field"><label>الوصف والتعليمات</label><textarea ...${bind("description")}></textarea></div>
    <label class="check"><input type="checkbox" ...${bind("allow_late", "checkbox")} /> السماح بالتسليم المتأخر (يُعلَّم كمتأخر)</label>
    <button disabled=${busy}>نشر المهمة</button></form>`;
}

export function AssignmentsView({ user }) {
  const state = useAsync(() => api.get("/api/assignments"), []);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("open");
  return html`<div>
    <div class="row between"><h1>المهام والواجبات</h1>
      ${!isStudent(user) ? html`<button onClick=${() => setCreating(!creating)}>${creating ? "إلغاء" : "+ مهمة جديدة"}</button>` : null}</div>
    ${creating ? html`<${CreateAssignment} onCreated=${() => { setCreating(false); state.reload(); }} />` : null}
    ${isStudent(user) ? html`<div class="row" style="margin-bottom:.75rem">
      ${[["open", "المطلوبة"], ["done", "المسلمة"], ["all", "الكل"]].map(([k, l]) => html`
        <button class=${`small ${filter === k ? "" : "secondary"}`} onClick=${() => setFilter(k)}>${l}</button>`)}</div>` : null}
    <${Async} state=${state}>${(list) => {
      let items = list;
      if (isStudent(user) && filter === "open") items = list.filter((a) => ["not_started", "in_progress"].includes(a.my_status) || (a.my_status === "late" && a.allow_late));
      if (isStudent(user) && filter === "done") items = list.filter((a) => ["submitted", "reviewed"].includes(a.my_status));
      return items.length ? html`<div class="card"><ul class="list">${items.map((a) => html`<li>
        <a class="item-link" href=${`#/assignments/${a.id}`}>
          <div class="row between"><strong>${a.title}</strong>
            ${isStudent(user) ? html`<${StatusChip} map=${ASSIGNMENT_STATUS} value=${a.my_status} />`
              : html`<${Chip} kind="primary">سلّم ${a.stats.submitted}/${a.stats.enrolled}<//>`}</div>
          <div class="small muted">${KIND[a.kind]} · ${a.course_code} ${a.course_title} · التسليم ${fmtDate(a.due_at)} (${fmtRelative(a.due_at)})
            ${a.my_score !== null && a.my_score !== undefined ? html` · الدرجة ${a.my_score}/${a.max_score}` : null}</div>
        </a></li>`)}</ul></div>` : html`<${Empty}>لا توجد مهام<//>`;
    }}<//>
  </div>`;
}

function FilesList({ files }) {
  if (!files?.length) return null;
  return html`<ul class="list">${files.map((f) => html`<li class="row between">
    <span class="row" style="gap:.35rem;display:inline-flex"><${Icon} name="attach" size=${16} />${f.name} <span class="small muted">${fmtSize(f.size)} · نسخة ${f.version}</span>
      ${f.scan_status !== "clean" ? html` <${Chip} kind="warning">قيد الفحص<//>` : null}</span>
    <button class="small secondary" onClick=${() => downloadFile(f.id, f.name).catch(toastError)}>تنزيل</button></li>`)}</ul>`;
}

function SubmitForm({ a, onDone }) {
  const [files, setFiles] = useState([]);
  const [note, setNote] = useState(a.submission?.note || "");
  const send = (final) => async (e) => {
    e?.preventDefault();
    const fd = new FormData();
    fd.append("final", final ? "true" : "false");
    fd.append("note", note);
    for (const f of files) fd.append("upload", f);
    await api.form(`/api/assignments/${a.id}/submission`, fd);
    toast(final ? "تم التسليم بنجاح" : "تم حفظ المسودة");
    setFiles([]);
    onDone();
  };
  const [submit, busy, error] = useSubmit(send(true));
  const [save, busy2] = useSubmit(send(false));
  const accept = a.allowed_extensions.map((e) => "." + e).join(",");
  return html`<form class="card" onSubmit=${submit}><h3>${a.submission?.status === "submitted" ? "إعادة التسليم" : "تسليم المهمة"}</h3>
    <${ErrorBox} error=${error} />
    <div class="field"><label>الملفات (${a.allowed_extensions.join("، ")} — حتى ${a.max_file_mb}MB للملف)</label>
      <input type="file" multiple accept=${accept} onChange=${(e) => setFiles([...e.target.files])} /></div>
    <div class="field"><label>ملاحظة للأستاذ (اختياري)</label><textarea value=${note} onInput=${(e) => setNote(e.target.value)}></textarea></div>
    <div class="row"><button disabled=${busy || busy2}>${busy ? "جارٍ الرفع…" : "تسليم نهائي"}</button>
      <button type="button" class="secondary" disabled=${busy || busy2} onClick=${save}>حفظ كمسودة</button></div>
    ${new Date(a.due_at) < new Date() ? html`<p class="small" style="color:var(--danger)">انتهى الموعد؛ سيُسجل التسليم كمتأخر.</p>` : null}
  </form>`;
}

function GradeModal({ a, row, onClose, onSaved }) {
  const s = row.submission;
  const [v, bind] = useForm({ score: s.score ?? "", feedback: s.feedback || "", release: false, reason: "" });
  const [submit, busy, error] = useSubmit(async () => {
    await api.post(`/api/submissions/${s.id}/grade`, { score: Number(v.score), feedback: v.feedback, release: v.release, reason: v.reason });
    toast("تم حفظ التقييم");
    onSaved();
  });
  return html`<${Modal} title=${`تقييم: ${row.student.full_name}`} onClose=${onClose}>
    <${FilesList} files=${s.files} />
    ${s.note ? html`<div class="alert info">ملاحظة الطالب: ${s.note}</div>` : null}
    <form onSubmit=${submit}><${ErrorBox} error=${error} />
      <div class="field"><label>الدرجة (من ${a.max_score})</label><input type="number" min="0" max=${a.max_score} step="0.25" ...${bind("score")} required /></div>
      <div class="field"><label>الملاحظات والتغذية الراجعة</label><textarea ...${bind("feedback")}></textarea></div>
      ${s.score !== null ? html`<div class="field"><label>سبب تعديل الدرجة</label><input ...${bind("reason")} /></div>` : null}
      <label class="check"><input type="checkbox" ...${bind("release", "checkbox")} /> نشر الدرجة للطالب الآن</label>
      <button disabled=${busy}>حفظ</button></form>
  <//>`;
}

export function AssignmentDetail({ id, user }) {
  const state = useAsync(() => api.get(`/api/assignments/${id}`), [id]);
  const [grading, setGrading] = useState(null);
  return html`<${Async} state=${state}>${(a) => html`<div>
    <div class="row between"><h1>${a.title}</h1>${a.my_status ? html`<${StatusChip} map=${ASSIGNMENT_STATUS} value=${a.my_status} />` : null}</div>
    <div class="card">
      <div class="row"><${Chip}>${KIND[a.kind]}<//><span class="muted">${a.course_code} — ${a.course_title}</span></div>
      <p style="white-space:pre-wrap">${a.description || "—"}</p>
      <div class="small muted">التسليم حتى: <strong>${fmtDate(a.due_at)}</strong> (${fmtRelative(a.due_at)}) · الدرجة القصوى ${a.max_score}
        ${a.allow_late ? " · يُقبل التسليم المتأخر" : " · لا يُقبل التسليم المتأخر"}</div>
    </div>
    ${isStudent(user) ? html`
      ${a.submission ? html`<div class="card"><h3>تسليمي</h3>
        <div class="small muted">الحالة: ${a.submission.status === "in_progress" ? "مسودة" : `سُلّم ${fmtDate(a.submission.submitted_at)}`}
          ${a.submission.is_late ? " (متأخر)" : ""}</div>
        <${FilesList} files=${a.submission.files} />
        ${a.submission.grade_released ? html`<div class="alert success"><strong>الدرجة: ${a.submission.score} / ${a.max_score}</strong>
          ${a.submission.feedback ? html`<div>ملاحظات الأستاذ: ${a.submission.feedback}</div>` : null}</div>`
          : a.submission.status === "reviewed" ? html`<p class="muted">تمت المراجعة، وستظهر الدرجة عند نشرها.</p>` : null}
      </div>` : null}
      ${a.submission?.status !== "reviewed" && (a.allow_late || new Date(a.due_at) > new Date())
        ? html`<${SubmitForm} a=${a} onDone=${state.reload} />` : null}` : null}
    ${a.submissions ? html`<div class="card"><div class="card-head"><h3>التسليمات</h3>
      <button class="small" onClick=${async () => { const r = await api.post(`/api/assignments/${a.id}/release-grades`); toast(`نُشرت ${r.released} درجة`); state.reload(); }}>نشر الدرجات المقيّمة</button></div>
      <div class="table-wrap"><table><thead><tr><th>الطالب</th><th>الحالة</th><th>وقت التسليم</th><th class="num">الدرجة</th><th></th></tr></thead>
      <tbody>${a.submissions.map((row) => html`<tr>
        <td>${row.student.full_name}<div class="small muted mono">${row.student.code}</div></td>
        <td><${StatusChip} map=${ASSIGNMENT_STATUS} value=${row.status} />${row.submission?.grade_released ? html` <${Chip} kind="success">منشورة<//>` : null}</td>
        <td class="small">${row.submission?.submitted_at ? fmtDate(row.submission.submitted_at) : "—"}</td>
        <td class="num">${row.submission?.score ?? "—"}</td>
        <td>${row.submission && row.submission.status !== "in_progress" ? html`<button class="small" onClick=${() => setGrading(row)}>فتح وتقييم</button>` : null}</td>
      </tr>`)}</tbody></table></div></div>` : null}
    ${grading ? html`<${GradeModal} a=${a} row=${grading} onClose=${() => setGrading(null)} onSaved=${() => { setGrading(null); state.reload(); }} />` : null}
  </div>`}<//>`;
}
