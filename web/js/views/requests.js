import { html, useState, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, Tabs, fmtDate, fmtRelative } from "../ui.js";
import { api, downloadFile } from "../api.js";

const handler = (u) => ["staff", "faculty_admin", "university_admin"].includes(u.role);
const STATUS_KIND = { submitted: "info", in_review: "warning", needs_documents: "danger", forwarded: "info", approved: "success", rejected: "danger" };

function NewRequest({ onDone }) {
  const types = useAsync(() => api.get("/api/requests/types"), []);
  const [v, bind] = useForm({ type: "enrollment_certificate", subject: "", details: "" });
  const [file, setFile] = useState(null);
  const [submit, busy, error] = useSubmit(async () => {
    const fd = new FormData();
    Object.entries(v).forEach(([k, x]) => fd.append(k, x));
    if (file) fd.append("upload", file);
    await api.form("/api/requests", fd);
    toast("تم تقديم الطلب");
    onDone();
  });
  return html`<form class="card" onSubmit=${submit}><h3>طلب جديد</h3><${ErrorBox} error=${error} />
    <div class="field"><label>نوع الطلب</label><select ...${bind("type")}>
      ${Object.entries(types.data?.types || {}).map(([k, t]) => html`<option value=${k}>${t.label}</option>`)}</select></div>
    <div class="field"><label>الموضوع</label><input ...${bind("subject")} required /></div>
    <div class="field"><label>التفاصيل</label><textarea ...${bind("details")}></textarea></div>
    <div class="field"><label>مستند مرفق (PDF أو صورة، اختياري)</label><input type="file" accept=".pdf,.jpg,.jpeg,.png,.docx" onChange=${(e) => setFile(e.target.files[0])} /></div>
    <button disabled=${busy}>تقديم</button></form>`;
}

function RequestList({ rows }) {
  return rows.length ? html`<div class="card"><ul class="list">${rows.map((r) => html`<li><a class="item-link" href=${`#/requests/${r.id}`}>
    <div class="row between"><strong>${r.type_label}: ${r.subject}</strong><${Chip} kind=${STATUS_KIND[r.status]}>${r.status_label}<//></div>
    <div class="small muted">${r.requester.full_name} · ${r.office_label} · ${fmtRelative(r.updated_at, true)}</div></a></li>`)}</ul></div>`
    : html`<${Empty}>لا توجد طلبات<//>`;
}

export function RequestsView({ user }) {
  const [tab, setTab] = useState(handler(user) ? "office" : "mine");
  const state = useAsync(() => api.get(`/api/requests?scope=${tab}`), [tab]);
  const [creating, setCreating] = useState(false);
  return html`<div>
    <div class="row between"><h1>الطلبات والمعاملات</h1><button onClick=${() => setCreating(!creating)}>${creating ? "إلغاء" : "+ طلب جديد"}</button></div>
    ${creating ? html`<${NewRequest} onDone=${() => { setCreating(false); setTab("mine"); state.reload(); }} />` : null}
    ${handler(user) ? html`<${Tabs} value=${tab} onChange=${setTab} tabs=${[["office", "الواردة لاختصاصي"], ["mine", "طلباتي"]]} />` : null}
    <${Async} state=${state}>${(rows) => html`<${RequestList} rows=${rows} />`}<//>
  </div>`;
}

export function RequestDetail({ id, user }) {
  const state = useAsync(() => api.get(`/api/requests/${id}`), [id]);
  const types = useAsync(() => api.get("/api/requests/types"), []);
  const [v, bind] = useForm({ action: "in_review", comment: "", office: "registrar" });
  const [file, setFile] = useState(null);
  const [act, busy, error] = useSubmit(async () => {
    await api.post(`/api/requests/${id}/actions`, v);
    toast("تم تحديث الطلب");
    state.reload();
  });
  const [upload, busy2, error2] = useSubmit(async () => {
    const fd = new FormData();
    fd.append("upload", file);
    await api.form(`/api/requests/${id}/documents`, fd);
    toast("تم إرفاق المستند");
    state.reload();
  });
  return html`<${Async} state=${state}>${(r) => html`<div>
    <div class="row"><a href="#/requests">← الطلبات</a></div>
    <div class="row between"><h1>${r.type_label}: ${r.subject}</h1><${Chip} kind=${STATUS_KIND[r.status]}>${r.status_label}<//></div>
    <div class="card"><p style="white-space:pre-wrap">${r.details || "—"}</p>
      <div class="small muted">مقدم الطلب: ${r.requester.full_name} ${r.requester.code ? `(${r.requester.code})` : ""} · الجهة: ${r.office_label} · ${fmtDate(r.created_at)}</div></div>
    <div class="card"><h3>مسار المعاملة</h3><ul class="list">${r.events.map((e) => html`<li>
      <div class="row between"><strong>${e.actor}</strong><span class="small muted">${fmtDate(e.created_at)}</span></div>
      <div class="small">${types.data?.statuses?.[e.status] || e.status}${e.comment ? ` — ${e.comment}` : ""}</div>
      ${e.file ? html`<button class="ghost small" onClick=${() => downloadFile(e.file.id, e.file.name).catch(toastError)}>📎 ${e.file.name}</button>` : null}</li>`)}</ul></div>
    ${r.requester.id === user.id && !["approved", "rejected"].includes(r.status) ? html`<form class="card" onSubmit=${upload}>
      <h3>إرفاق مستند</h3><${ErrorBox} error=${error2} /><input type="file" accept=".pdf,.jpg,.jpeg,.png,.docx" onChange=${(e) => setFile(e.target.files[0])} required />
      <button style="margin-top:.5rem" disabled=${busy2 || !file}>إرفاق</button></form>` : null}
    ${handler(user) && r.requester.id !== user.id ? html`<form class="card" onSubmit=${act}><h3>إجراء</h3><${ErrorBox} error=${error} />
      <div class="form-grid"><div class="field"><select ...${bind("action")}>
        <option value="in_review">بدء المراجعة</option><option value="needs_documents">طلب استكمال مستندات</option>
        <option value="forwarded">إحالة لجهة أخرى</option><option value="approved">اعتماد</option><option value="rejected">رفض</option>
        <option value="comment">إضافة ملاحظة</option></select></div>
        ${v.action === "forwarded" ? html`<div class="field"><select ...${bind("office")}>
          ${Object.entries(types.data?.offices || {}).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>` : null}</div>
      <div class="field"><label>ملاحظة (إلزامية عند الرفض أو طلب مستندات)</label><textarea ...${bind("comment")}></textarea></div>
      <button disabled=${busy}>تنفيذ</button></form>` : null}
  </div>`}<//>`;
}
