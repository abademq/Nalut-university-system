import {
  html, useState, useEffect, useAsync, Async, Empty, Chip, Tabs, ErrorBox, useForm, useSubmit, toast, toastError,
  Modal, fmtDate, toLocalInput, Icon } from "../ui.js";
import { api, blobUrl } from "../api.js";

// Lecture timetables (image or PDF) and image announcements, for everyone; publishing for
// the administrations (and staff when the permission matrix allows it).

const KIND = { schedule: "جداول المحاضرات", poster: "الإعلانات المصورة" };
const AUDIENCE = { all: "الجميع", students: "الطلبة", staff: "الموظفون وهيئة التدريس" };

function useFileUrl(fileId) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let u = null;
    blobUrl(`/api/files/${fileId}`).then((x) => { u = x; setUrl(x); }).catch(() => {});
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [fileId]);
  return url;
}

function Item({ p, onOpen }) {
  const url = useFileUrl(p.file.id);
  return html`<div class="card pub" onClick=${() => onOpen(p)} role="button" tabindex="0">
    ${p.is_image ? (url ? html`<img src=${url} alt=${p.title} />` : html`<div class="pub-ph">…</div>`)
      : html`<div class="pub-ph"><${Icon} name="file" size=${28} /> PDF</div>`}
    <h3>${p.title}</h3>
    ${p.body ? html`<p class="small">${p.body}</p>` : null}
    <div class="small muted">${[p.faculty_name, p.department_name, p.cohort && `دفعة ${p.cohort}`].filter(Boolean).join(" · ") || "الجامعة كاملة"} · ${fmtDate(p.starts_at, false)}</div>
  </div>`;
}

function Viewer({ p, onClose }) {
  const url = useFileUrl(p.file.id);
  return html`<${Modal} title=${p.title} onClose=${onClose}>
    ${p.body ? html`<p>${p.body}</p>` : null}
    ${!url ? html`<p class="muted">جارٍ التحميل…</p>` : p.is_image ? html`<img src=${url} alt=${p.title} style="width:100%;border-radius:12px" />`
      : html`<p><a class="btn" href=${url} target="_blank" rel="noopener">فتح الملف</a> <a class="btn secondary" href=${url} download=${p.file.name}>تنزيل</a></p>`}<//>`;
}

function PublishForm({ user, onDone }) {
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const [file, setFile] = useState(null);
  const [v, bind] = useForm({ kind: "schedule", title: "", body: "", audience: "students", faculty_id: user.faculty?.id || "",
    department_id: "", cohort: "", starts_at: toLocalInput(Date.now()), ends_at: "", notify: true });
  const [submit, busy, error] = useSubmit(async () => {
    if (!file) throw new Error("اختر صورة أو ملف PDF");
    const fd = new FormData();
    for (const k of ["kind", "title", "body", "audience", "cohort"]) fd.append(k, v[k]);
    if (v.faculty_id) fd.append("faculty_id", v.faculty_id);
    if (v.department_id) fd.append("department_id", v.department_id);
    fd.append("starts_at", new Date(v.starts_at).toISOString());
    if (v.ends_at) fd.append("ends_at", new Date(v.ends_at).toISOString());
    fd.append("notify", v.notify ? "true" : "false");
    fd.append("upload", file);
    const r = await api.form("/api/publications", fd);
    toast(r.notified === false ? "نُشر (تعذر إرسال الإشعار لهذا النطاق)" : "نُشر");
    onDone();
  });
  const faculties = structure.data?.faculties || [];
  const fac = faculties.find((f) => String(f.id) === String(v.faculty_id));
  return html`<form class="card" onSubmit=${submit}><h3>نشر جديد</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>النوع</label><select ...${bind("kind")}><option value="schedule">جدول محاضرات</option><option value="poster">إعلان مصور</option></select></div>
      <div class="field"><label>العنوان</label><input ...${bind("title")} required /></div>
      <div class="field"><label>وصف (اختياري)</label><input ...${bind("body")} /></div>
      <div class="field"><label>يظهر لـ</label><select ...${bind("audience")}>${Object.entries(AUDIENCE).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
      ${user.role === "university_admin" ? html`<div class="field"><label>الكلية</label><select ...${bind("faculty_id")}><option value="">الجامعة كاملة</option>
        ${faculties.map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
      <div class="field"><label>القسم</label><select ...${bind("department_id")}><option value="">كل الأقسام</option>
        ${(fac?.departments || []).map((d) => html`<option value=${d.id}>${d.name}</option>`)}</select></div>
      <div class="field"><label>الدفعة (اختياري، مثل 2023)</label><input ...${bind("cohort")} /></div>
      <div class="field"><label>يظهر من</label><input type="datetime-local" ...${bind("starts_at")} required /></div>
      <div class="field"><label>يختفي في (اختياري)</label><input type="datetime-local" ...${bind("ends_at")} /></div>
      <div class="field"><label>الملف: صورة (JPG/PNG) أو PDF، حتى 10 ميغابايت</label>
        <input type="file" accept=".jpg,.jpeg,.png,.pdf" onChange=${(e) => setFile(e.target.files[0] || null)} required /></div>
    </div>
    <label class="check"><input type="checkbox" ...${bind("notify", "checkbox")} /> إرسال إشعار للمستهدفين</label>
    <button disabled=${busy}>${busy ? "جارٍ الرفع…" : "نشر"}</button></form>`;
}

function Manage({ user }) {
  const state = useAsync(() => api.get("/api/publications/manage"), []);
  const [creating, setCreating] = useState(false);
  const toggle = async (p) => { await api.patch(`/api/publications/${p.id}`, { is_active: !p.is_active }).catch(toastError); state.reload(); };
  const remove = async (p) => { if (confirm(`حذف «${p.title}»؟`)) { await api.del(`/api/publications/${p.id}`).catch(toastError); state.reload(); } };
  const now = new Date();
  const status = (p) => !p.is_active ? ["موقوف", ""] : new Date(p.starts_at) > now ? ["مجدول", "info"]
    : p.ends_at && new Date(p.ends_at) <= now ? ["منتهي", ""] : ["ظاهر الآن", "success"];
  return html`<div>
    <div class="row between"><h2>إدارة المنشورات</h2><button onClick=${() => setCreating(!creating)}>${creating ? "إلغاء" : "+ نشر"}</button></div>
    ${creating ? html`<${PublishForm} user=${user} onDone=${() => { setCreating(false); state.reload(); }} />` : null}
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>العنوان</th><th>النوع</th><th>يظهر لـ</th><th>الحالة</th><th></th></tr></thead>
      <tbody>${rows.map((p) => html`<tr><td>${p.title}</td><td>${KIND[p.kind]}</td>
        <td class="small">${AUDIENCE[p.audience]} · ${[p.faculty_name, p.department_name, p.cohort && `دفعة ${p.cohort}`].filter(Boolean).join(" · ") || "الجامعة كاملة"}</td>
        <td><${Chip} kind=${status(p)[1]}>${status(p)[0]}<//></td>
        <td><div class="row"><button class="small secondary" onClick=${() => toggle(p)}>${p.is_active ? "إيقاف" : "تفعيل"}</button>
          <button class="small secondary" onClick=${() => remove(p)}>حذف</button></div></td></tr>`)}</tbody></table></div></div>`
      : html`<${Empty}>لا توجد منشورات بعد<//>`}<//>
  </div>`;
}

export function PublicationsView({ user, id }) {
  const [kind, setKind] = useState("schedule");
  const state = useAsync(() => api.get("/api/publications"), []);
  const [open, setOpen] = useState(null);
  const canPublish = (user.can || []).includes("publications.manage");
  useEffect(() => {
    if (id && state.data) setOpen(state.data.find((p) => String(p.id) === String(id)) || null);
  }, [id, state.data]);
  return html`<div><h1>الجداول والإعلانات المصورة</h1>
    <${Tabs} tabs=${Object.entries(KIND)} value=${kind} onChange=${setKind} />
    <${Async} state=${state}>${(rows) => {
      const items = rows.filter((p) => p.kind === kind);
      return items.length ? html`<div class="pub-grid">${items.map((p) => html`<${Item} key=${p.id} p=${p} onOpen=${setOpen} />`)}</div>`
        : html`<${Empty}>${kind === "schedule" ? "لا توجد جداول منشورة لك" : "لا توجد إعلانات مصورة"}<//>`;
    }}<//>
    ${canPublish ? html`<${Manage} user=${user} />` : null}
    ${open ? html`<${Viewer} p=${open} onClose=${() => setOpen(null)} />` : null}
  </div>`;
}
