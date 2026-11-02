// The complaints and suggestions box: anyone sends (optionally anonymous), the faculty or the
// university administration answers ("complaints.manage").
import { html, useState, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, Tabs, fmtDate, navigate } from "../ui.js";
import { api, downloadFile } from "../api.js";

const KIND = { new: "info", in_review: "warning", resolved: "success", rejected: "" };
const STATUS_LABEL = { new: "جديدة", in_review: "قيد المعالجة", resolved: "تمت المعالجة", rejected: "مرفوضة" };
const can = (u, k) => (u.can || []).includes(k);

function NewComplaint({ onSent }) {
  const meta = useAsync(() => api.get("/api/complaints/categories"), []);
  const [v, bind, setV] = useForm({ category: "services", subject: "", body: "", anonymous: false, to_university: false });
  const [file, setFile] = useState(null);
  const [submit, busy, error] = useSubmit(async () => {
    const fd = new FormData();
    Object.entries(v).forEach(([k, x]) => fd.append(k, typeof x === "boolean" ? String(x) : x));
    if (file) fd.append("upload", file);
    const c = await api.form("/api/complaints", fd);
    toast(`أُرسلت الشكوى، رقمها ${c.ref}`);
    setV({ ...v, subject: "", body: "" });
    setFile(null);
    onSent(c);
  });
  if (!meta.data) return null;
  const sensitive = meta.data.university_only.includes(v.category);
  return html`<form class="card" onSubmit=${submit}><h3>شكوى أو اقتراح جديد</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>النوع</label><select ...${bind("category")}>
        ${Object.entries(meta.data.categories).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
      <div class="field"><label>الموضوع</label><input ...${bind("subject")} required minlength="3" maxlength="200" /></div></div>
    <div class="field"><label>التفاصيل</label><textarea ...${bind("body")} required minlength="10" maxlength="5000"
      placeholder="ماذا حدث، أين ومتى، وما الذي تقترحه"></textarea></div>
    <div class="field"><label>مرفق (اختياري: صورة أو مستند أو تسجيل صوتي)</label>
      <input type="file" accept=".pdf,.jpg,.jpeg,.png,.docx,.mp3,.m4a" onChange=${(e) => setFile(e.target.files[0] || null)} /></div>
    <label class="check"><input type="checkbox" ...${bind("anonymous", "checkbox")} /> إخفاء اسمي عن الإدارة (شكوى مجهولة)</label>
    ${sensitive ? html`<p class="small">هذا النوع يصل مباشرة إلى إدارة الجامعة.</p>`
      : html`<label class="check"><input type="checkbox" ...${bind("to_university", "checkbox")} /> إرسالها إلى إدارة الجامعة بدل إدارة الكلية</label>`}
    ${v.anonymous ? html`<p class="small muted">لن يظهر اسمك لمن يعالج الشكوى ولا في سجل التدقيق، وتتابع الردود من حسابك.
      اذكر ما يكفي من التفاصيل، لأن الإدارة لن تستطيع سؤالك خارج المنصة.</p>` : null}
    <button disabled=${busy}>إرسال</button></form>`;
}

function List({ rows, inbox }) {
  return rows.length ? html`<div class="table-wrap"><table><thead><tr><th>الرقم</th><th>الموضوع</th><th>النوع</th>
    ${inbox ? html`<th>المرسل</th>` : html`<th>إلى</th>`}<th>الحالة</th><th>آخر تحديث</th></tr></thead>
    <tbody>${rows.map((c) => html`<tr style="cursor:pointer" onClick=${() => navigate(`#/complaints/${c.id}`)}>
      <td class="mono">${c.ref}</td><td>${c.subject}</td><td class="small">${c.category_label.split(" (")[0]}</td>
      <td class="small">${inbox ? (c.author ? c.author.full_name : html`<${Chip}>مجهول<//>`) : c.to}</td>
      <td><${Chip} kind=${KIND[c.status]}>${c.status_label}<//></td><td class="small">${fmtDate(c.updated_at)}</td></tr>`)}</tbody></table></div>`
    : html`<${Empty}>لا توجد شكاوى<//>`;
}

export function ComplaintsView({ user }) {
  const handler = can(user, "complaints.manage");
  const [tab, setTab] = useState(handler ? "inbox" : "mine");
  const [status, setStatus] = useState("");
  const mine = useAsync(() => api.get("/api/complaints"), []);
  const inbox = useAsync(() => (handler ? api.get(`/api/complaints?box=inbox${status ? `&status=${status}` : ""}`) : Promise.resolve([])), [status]);
  const tabs = [["mine", "شكاواي"], ["new", "شكوى جديدة"]];
  if (handler) tabs.unshift(["inbox", "الوارد"]);
  return html`<div><h1>صندوق الشكاوى والمقترحات</h1>
    <${Tabs} value=${tab} onChange=${setTab} tabs=${tabs} />
    ${tab === "new" ? html`<${NewComplaint} onSent=${() => { mine.reload(); setTab("mine"); }} />` : null}
    ${tab === "mine" ? html`<div class="card"><${Async} state=${mine}>${(rows) => html`<${List} rows=${rows} />`}<//></div>` : null}
    ${tab === "inbox" ? html`<div class="card"><div class="field" style="max-width:220px"><select value=${status} onChange=${(e) => setStatus(e.target.value)}>
      <option value="">كل الحالات</option><option value="new">جديدة</option><option value="in_review">قيد المعالجة</option>
      <option value="resolved">تمت المعالجة</option><option value="rejected">مرفوضة</option></select></div>
      <${Async} state=${inbox}>${(rows) => html`<${List} rows=${rows} inbox />`}<//></div>` : null}
  </div>`;
}

export function ComplaintDetail({ id }) {
  const state = useAsync(() => api.get(`/api/complaints/${id}`), [id]);
  const [v, bind, setV] = useForm({ body: "", status: "" });
  const [submit, busy, error] = useSubmit(async () => {
    await api.post(`/api/complaints/${id}/replies`, { body: v.body, ...(v.status ? { status: v.status } : {}) });
    setV({ body: "", status: "" });
    state.reload();
  });
  return html`<${Async} state=${state}>${(c) => html`<div>
    <div class="row between"><h1>${c.subject}</h1><a class="btn secondary small" href="#/complaints">← الصندوق</a></div>
    <p class="muted"><span class="mono">${c.ref}</span> · ${c.category_label} · إلى ${c.to} · ${fmtDate(c.created_at)}
      · <${Chip} kind=${KIND[c.status]}>${c.status_label}<//></p>
    <div class="card"><div class="small muted">${c.author ? `${c.author.full_name}${c.author.code ? ` (${c.author.code})` : ""}` : "مرسل مجهول"}</div>
      <p style="white-space:pre-wrap">${c.body}</p>
      ${c.file ? html`<button class="secondary small" onClick=${() => downloadFile(c.file.id, c.file.name).catch(toastError)}>${c.file.name}</button>` : null}</div>
    ${c.replies.map((r) => html`<div class="card" style=${r.from_handler ? "" : "border-inline-start:4px solid var(--accent, #888)"}>
      <div class="small muted">${r.author} · ${fmtDate(r.created_at)}${r.status ? ` · ${STATUS_LABEL[r.status]}` : ""}</div>
      <p style="white-space:pre-wrap">${r.body}</p></div>`)}
    ${(c.can_handle && !c.mine) || !["resolved", "rejected"].includes(c.status) ? html`<form class="card" onSubmit=${submit}><${ErrorBox} error=${error} />
      <div class="field"><label>${c.can_handle && !c.mine ? "الرد" : "إضافة توضيح"}</label><textarea ...${bind("body")} required minlength="2"></textarea></div>
      ${c.can_handle && !c.mine ? html`<div class="field" style="max-width:260px"><label>الحالة</label><select ...${bind("status")}>
        <option value="">${c.status === "new" ? "قيد المعالجة" : "دون تغيير"}</option><option value="in_review">قيد المعالجة</option>
        <option value="resolved">تمت المعالجة</option><option value="rejected">مرفوضة</option></select></div>` : null}
      <button disabled=${busy}>إرسال</button></form>` : null}
  </div>`}<//>`;
}
