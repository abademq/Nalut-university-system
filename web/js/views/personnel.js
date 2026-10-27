import {
  html, useState, useEffect, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, Modal,
  fmtDate, navigate, ROLE,
} from "../ui.js";
import { api, blobUrl } from "../api.js";

// Staff and faculty members: employment files with their documents (see backend routers/personnel.py).

export const SECTION = {
  staff: { title: "الموظفون", one: "الموظف", hash: "#/staff",
    intro: "الملف الوظيفي لكل موظف وإدارات الكليات: البيانات الوظيفية والشخصية ونسخ المستندات." },
  faculty: { title: "أعضاء هيئة التدريس", one: "عضو هيئة التدريس", hash: "#/faculty-members",
    intro: "الملف الكامل لكل عضو هيئة تدريس ومعيد: الدرجة العلمية والتخصص والمؤهلات والمقررات والمستندات." },
};
const STATUS_KIND = { active: "success", leave: "warning", study_leave: "info", secondment: "info", suspended: "danger",
  retired: "", left: "" };

export function PersonnelList({ section }) {
  const s = SECTION[section];
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const meta = useAsync(() => api.get("/api/personnel/meta"), []);
  const state = useAsync(() => api.get(`/api/personnel?section=${section}&limit=500&q=${encodeURIComponent(q)}&status=${status}`),
    [section, q, status]);
  const choices = meta.data?.choices || {};
  return html`<div><h1>${s.title}</h1>
    <p class="muted">${s.intro} يُسجَّل كل اطلاع أو تعديل أو تنزيل في سجل التدقيق.</p>
    <div class="row" style="margin-bottom:.75rem">
      <input style="max-width:300px" placeholder="بحث بالاسم أو الرقم أو البريد أو الهاتف" value=${q} onInput=${(e) => setQ(e.target.value)} />
      <select style="max-width:200px" value=${status} onChange=${(e) => setStatus(e.target.value)}>
        <option value="">كل الحالات</option>
        ${Object.entries(choices.status || {}).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <${Async} state=${state}>${(d) => d.items.length ? html`<div class="card"><p class="small muted">${d.total} ${s.one}</p>
      <div class="table-wrap"><table>
      <thead><tr><th>الاسم</th><th>${section === "faculty" ? "الدرجة العلمية" : "المسمى الوظيفي"}</th><th>الكلية</th>
        <th>الحالة</th><th class="num">المستندات</th><th>التواصل</th></tr></thead>
      <tbody>${d.items.map((p) => html`<tr style="cursor:pointer" onClick=${() => navigate(`#/personnel/${p.id}`)}>
        <td><a href=${`#/personnel/${p.id}`}>${p.full_name}</a><div class="small muted">${ROLE[p.role] || p.role}${p.code ? ` · ${p.code}` : ""}</div></td>
        <td>${p.title || html`<span class="muted">—</span>`}</td><td>${p.faculty || "—"}</td>
        <td><${Chip} kind=${STATUS_KIND[p.status] || ""}>${(choices.status || {})[p.status] || p.status}<//></td>
        <td class="num">${p.documents}</td><td class="small ltr">${p.phone || p.email || ""}</td></tr>`)}</tbody></table></div></div>`
      : html`<${Empty}>لا يوجد أحد<//>`}<//>
  </div>`;
}

function DocViewer({ doc, onClose }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { blobUrl(`/api/personnel/documents/${doc.id}/file?inline=true`).then(setUrl).catch(setErr); }, [doc.id]);
  const isImage = /image\//.test(doc.file.content_type);
  return html`<${Modal} title=${doc.title} onClose=${() => { if (url) URL.revokeObjectURL(url); onClose(); }}>
    <${ErrorBox} error=${err} />
    ${url ? (isImage ? html`<img class="selfie" src=${url} alt=${doc.title} />`
      : html`<p><a class="btn" href=${url} download=${doc.file.name}>تنزيل ${doc.file.name}</a></p>`) : html`<p class="muted">جارٍ التحميل…</p>`}
    <p class="small muted">تم تسجيل اطلاعك على هذا المستند في سجل التدقيق.</p><//>`;
}

export function PersonnelDetail({ id }) {
  const meta = useAsync(() => api.get("/api/personnel/meta"), []);
  const state = useAsync(() => api.get(id === "me" ? "/api/personnel/me" : `/api/personnel/${id}`), [id]);
  const [viewing, setViewing] = useState(null);
  return html`<${Async} state=${state}>${(d) => {
    const s = SECTION[d.section];
    const m = meta.data;
    const p = d.person;
    const choices = m?.choices || {};
    const fields = m?.sections[d.section].fields || [];
    return html`<div>
      ${id === "me" ? html`<div class="row"><a href="#/profile">← حسابي</a></div>` : html`<div class="row"><a href=${s.hash}>← ${s.title}</a></div>`}
      <h1>${id === "me" ? "ملفي الوظيفي" : p.full_name}</h1>
      <p class="muted">${ROLE[p.role] || p.role}${p.code ? ` · ${p.code}` : ""}${p.faculty ? ` · ${p.faculty}` : ""}${p.department ? ` · ${p.department}` : ""}
        · <span class="ltr">${p.email || ""} ${p.phone || ""}</span>${p.is_active ? "" : " · الحساب موقوف"}</p>
      <div class="grid cols-2">
        ${d.can_manage && m ? html`<${RecordForm} id=${p.id} record=${d.record} fields=${fields} choices=${choices} onSaved=${state.reload} />`
          : html`<${RecordView} record=${d.record} fields=${fields} choices=${choices} />`}
        <div>
          ${d.section === "faculty" ? html`<div class="card"><h3>المقررات (${d.teaching.length})</h3>${d.teaching.length
            ? html`<ul class="list">${d.teaching.map((c) => html`<li class="row between"><span><a href=${`#/courses/${c.id}`}>${c.code} — ${c.title}</a>
                <span class="small muted"> · ${c.term || ""} · ${c.credits} وحدات</span></span>
                ${c.current ? html`<${Chip} kind="success">الفصل الحالي<//>` : null}</li>`)}</ul>`
            : html`<${Empty}>لا توجد مقررات مسندة<//>`}</div>` : null}
          ${d.can_manage && m ? html`<${UploadDoc} id=${p.id} meta=${m} onDone=${state.reload} />` : null}
          <div class="card"><h3>المستندات (${d.documents.length})</h3>${d.documents.length ? html`<ul class="list">${d.documents.map((doc) => html`<li>
            <div class="row between"><strong>${doc.title}</strong><${Chip}>${doc.type_label}<//></div>
            <div class="small muted">${doc.file.name} · أُضيف ${fmtDate(doc.created_at)}${doc.uploaded_by ? ` بواسطة ${doc.uploaded_by}` : ""}</div>
            ${doc.notes ? html`<div class="small">${doc.notes}</div>` : null}
            <div class="row" style="margin-top:.3rem"><button class="small" onClick=${() => setViewing(doc)}>عرض / تنزيل</button>
              ${d.can_manage ? html`<button class="small secondary" onClick=${async () => {
                const reason = prompt("سبب الحذف (يبقى المستند محفوظاً في السجل):");
                if (!reason || reason.trim().length < 3) return;
                await api.post(`/api/personnel/documents/${doc.id}/delete`, { reason }).catch(toastError);
                state.reload();
              }}>حذف</button>` : null}</div></li>`)}</ul>` : html`<${Empty}>لا توجد مستندات<//>`}</div>
        </div>
      </div>
      ${viewing ? html`<${DocViewer} doc=${viewing} onClose=${() => setViewing(null)} />` : null}
    </div>`;
  }}<//>`;
}

const show = (f, value, choices) => {
  if (value === null || value === undefined || value === "") return html`<span class="muted">—</span>`;
  if (choices[f.type]) return choices[f.type][value] || value;
  return f.type === "date" ? fmtDate(value, false) : String(value);
};

function RecordView({ record, fields, choices }) {
  return html`<div class="card"><h3>البيانات</h3><dl class="form-grid">
    <div class="field"><label>الرقم الوطني</label><div>${record.national_id || html`<span class="muted">—</span>`}</div></div>
    ${fields.map((f) => html`<div class="field"><label>${f.label}</label><div>${show(f, record[f.key], choices)}</div></div>`)}</dl>
    <p class="small muted">${record.updated_at ? `آخر تحديث ${fmtDate(record.updated_at)}${record.updated_by ? ` بواسطة ${record.updated_by}` : ""}` : "لم يُعبأ الملف بعد"}</p></div>`;
}

function RecordForm({ id, record, fields, choices, onSaved }) {
  const init = { national_id: record.national_id ?? "" };
  for (const f of fields) init[f.key] = record[f.key] ?? "";
  const [v, bind] = useForm(init);
  const [submit, busy, error] = useSubmit(async () => {
    const data = {};
    for (const f of fields) data[f.key] = v[f.key] === "" ? null : f.type === "number" ? Number(v[f.key]) : v[f.key];
    await api.put(`/api/personnel/${id}/record`, { national_id: v.national_id || null, data });
    toast("تم حفظ الملف");
    onSaved();
  });
  const input = (f) => choices[f.type]
    ? html`<select ...${bind(f.key)}><option value="">—</option>${Object.entries(choices[f.type]).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select>`
    : f.type === "textarea" ? html`<textarea ...${bind(f.key)}></textarea>`
      : html`<input type=${f.type} step=${f.type === "number" ? "0.5" : null} ...${bind(f.key)} />`;
  return html`<form class="card" onSubmit=${submit}><h3>البيانات</h3><${ErrorBox} error=${error} />
    <div class="form-grid"><div class="field"><label>الرقم الوطني (يُحفظ مشفراً)</label><input ...${bind("national_id")} /></div>
      ${fields.filter((f) => f.type !== "textarea").map((f) => html`<div class="field"><label>${f.label}</label>${input(f)}</div>`)}</div>
    ${fields.filter((f) => f.type === "textarea").map((f) => html`<div class="field"><label>${f.label}</label>${input(f)}</div>`)}
    <p class="small muted">${record.updated_at ? `آخر تحديث ${fmtDate(record.updated_at)}${record.updated_by ? ` بواسطة ${record.updated_by}` : ""}` : ""}</p>
    <button disabled=${busy}>حفظ البيانات</button></form>`;
}

function UploadDoc({ id, meta, onDone }) {
  const [v, bind] = useForm({ doc_type: "cv", title: "", notes: "" });
  const [file, setFile] = useState(null);
  const [submit, busy, error] = useSubmit(async (e) => {
    const fd = new FormData();
    Object.entries(v).forEach(([k, x]) => fd.append(k, x));
    fd.append("upload", file);
    await api.form(`/api/personnel/${id}/documents`, fd);
    toast("تمت إضافة المستند");
    e?.target?.reset?.();
    setFile(null);
    onDone();
  });
  return html`<form class="card" onSubmit=${submit}><h3>إضافة مستند</h3><${ErrorBox} error=${error} />
    <div class="field"><label>نوع المستند</label><select ...${bind("doc_type")}>
      ${Object.entries(meta.doc_types).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <div class="field"><label>العنوان (اختياري)</label><input ...${bind("title")} /></div>
    <div class="field"><label>ملاحظات (اختياري)</label><input ...${bind("notes")} /></div>
    <div class="field"><label>الملف: PDF أو صورة أو Word، حتى ${meta.max_file_mb}MB (يُحفظ مشفراً)</label>
      <input type="file" accept=".pdf,.jpg,.jpeg,.png,.docx" onChange=${(e) => setFile(e.target.files[0] || null)} required /></div>
    <button disabled=${busy || !file}>${busy ? "جارٍ الرفع…" : "رفع المستند"}</button></form>`;
}
