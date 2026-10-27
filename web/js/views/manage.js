import {
  html, useState, useEffect, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, Modal,
  fmtDate, toLocalInput, navigate, Icon } from "../ui.js";
import { api, blobUrl } from "../api.js";

// ------------------------------------------------------------------ pinned announcements

const LEVEL = { info: ["عادي", "info"], important: ["مهم", "warning"], urgent: ["عاجل", "danger"] };
const AUDIENCE = { all: "الجميع", students: "الطلبة", staff: "الموظفون وهيئة التدريس" };

/** Strip of active pinned announcements shown above every page. */
export function BannerStrip() {
  const state = useAsync(() => api.get("/api/banners"), []);
  useEffect(() => {
    const on = () => state.reload();
    window.addEventListener("nus:banners", on);
    return () => window.removeEventListener("nus:banners", on);
  }, []);
  const [hidden, setHidden] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem("nus-hidden-banners") || "[]"); } catch { return []; }
  });
  const hide = (id) => {
    const next = [...hidden, id];
    setHidden(next);
    try { sessionStorage.setItem("nus-hidden-banners", JSON.stringify(next)); } catch { /* ignore */ }
  };
  const items = (state.data || []).filter((b) => !hidden.includes(b.id));
  if (!items.length) return null;
  return html`<div>${items.map((b) => html`<div class=${`alert ${LEVEL[b.level]?.[1] === "danger" ? "error" : LEVEL[b.level]?.[1] || "info"} banner`}>
    <div class="row between"><strong class="row" style="gap:.4rem"><${Icon} name="pin" size=${18} />${b.title}</strong>
      <button class="ghost small" title="إخفاء حتى إعادة فتح الصفحة" onClick=${() => hide(b.id)}aria-label="إخفاء"><${Icon} name="close" size=${18} /></button></div>
    ${b.body ? html`<div style="white-space:pre-wrap">${b.body}</div>` : null}
    ${b.link ? html`<a href=${b.link} target=${b.link.startsWith("http") ? "_blank" : null} rel="noopener">التفاصيل ←</a>` : null}
  </div>`)}</div>`;
}

function BannerForm({ user, initial, onDone, onCancel }) {
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const b = initial || {};
  const [v, bind] = useForm({
    title: b.title || "", body: b.body || "", link: b.link || "", level: b.level || "info", audience: b.audience || "all",
    faculty_id: b.faculty_id || "", starts_at: toLocalInput(b.starts_at || Date.now()),
    ends_at: b.ends_at ? toLocalInput(b.ends_at) : "", is_active: b.is_active ?? true,
  });
  const [submit, busy, error] = useSubmit(async () => {
    const body = { title: v.title, body: v.body, link: v.link || null, level: v.level, audience: v.audience,
      starts_at: new Date(v.starts_at).toISOString(), ends_at: v.ends_at ? new Date(v.ends_at).toISOString() : null,
      is_active: v.is_active };
    if (user.role === "university_admin") body.faculty_id = v.faculty_id ? Number(v.faculty_id) : null;
    if (b.id) await api.patch(`/api/banners/${b.id}`, body);
    else await api.post("/api/banners", body);
    window.dispatchEvent(new Event("nus:banners"));
    toast("تم الحفظ");
    onDone();
  });
  return html`<form class="card" onSubmit=${submit}><h3>${b.id ? "تعديل إعلان مثبت" : "إعلان مثبت جديد"}</h3><${ErrorBox} error=${error} />
    <div class="field"><label>العنوان</label><input ...${bind("title")} required maxlength="200" /></div>
    <div class="field"><label>النص (اختياري)</label><textarea ...${bind("body")}></textarea></div>
    <div class="form-grid">
      <div class="field"><label>الأهمية</label><select ...${bind("level")}>${Object.entries(LEVEL).map(([k, [l]]) => html`<option value=${k}>${l}</option>`)}</select></div>
      <div class="field"><label>يظهر لـ</label><select ...${bind("audience")}>${Object.entries(AUDIENCE).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
      ${user.role === "university_admin" ? html`<div class="field"><label>النطاق</label><select ...${bind("faculty_id")}>
        <option value="">الجامعة كاملة</option>${(structure.data?.faculties || []).map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
      <div class="field"><label>يظهر من</label><input type="datetime-local" ...${bind("starts_at")} required /></div>
      <div class="field"><label>يختفي في (اتركه فارغاً ليبقى حتى الإيقاف)</label><input type="datetime-local" ...${bind("ends_at")} /></div>
      <div class="field"><label>رابط (اختياري) مثل #/grades أو https://…</label><input class="ltr" ...${bind("link")} /></div>
    </div>
    <label class="check"><input type="checkbox" ...${bind("is_active", "checkbox")} /> مفعّل</label>
    <div class="row"><button disabled=${busy}>حفظ</button>${onCancel ? html`<button type="button" class="secondary" onClick=${onCancel}>إلغاء</button>` : null}</div>
  </form>`;
}

export function BannersView({ user }) {
  const state = useAsync(() => api.get("/api/banners/manage"), []);
  const [editing, setEditing] = useState(null); // null | {} (new) | banner
  const now = Date.now();
  const stateOf = (b) => {
    if (!b.is_active) return ["موقوف", ""];
    if (new Date(b.starts_at) > now) return ["مجدول", "info"];
    if (b.ends_at && new Date(b.ends_at) <= now) return ["منتهي", ""];
    return ["ظاهر الآن", "success"];
  };
  const remove = async (b) => {
    if (!confirm(`حذف "${b.title}"؟`)) return;
    await api.del(`/api/banners/${b.id}`).catch(toastError);
    state.reload();
  };
  return html`<div>
    <div class="row between"><h1>الإعلانات المثبتة</h1><button onClick=${() => setEditing({})}>+ إعلان مثبت</button></div>
    <p class="muted">تظهر في أعلى التطبيق ولوحة التحكم للفئة المحددة بين وقت الظهور ووقت الاختفاء، ثم تختفي تلقائياً.</p>
    ${editing ? html`<${BannerForm} user=${user} initial=${editing.id ? editing : null}
      onDone=${() => { setEditing(null); state.reload(); }} onCancel=${() => setEditing(null)} />` : null}
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><ul class="list">${rows.map((b) => {
      const [label, kind] = stateOf(b);
      return html`<li><div class="row between"><strong>${b.title}</strong>
        <div class="row"><${Chip} kind=${LEVEL[b.level]?.[1]}>${LEVEL[b.level]?.[0]}<//><${Chip} kind=${kind}>${label}<//></div></div>
        <div class="small muted">${AUDIENCE[b.audience]} · ${b.faculty_name || "الجامعة كاملة"} · من ${fmtDate(b.starts_at)} ${b.ends_at ? `إلى ${fmtDate(b.ends_at)}` : "بدون نهاية"}</div>
        <div class="row" style="margin-top:.4rem"><button class="small secondary" onClick=${() => setEditing(b)}>تعديل</button>
          <button class="small secondary" onClick=${async () => { await api.patch(`/api/banners/${b.id}`, { is_active: !b.is_active }); state.reload(); }}>${b.is_active ? "إيقاف" : "تفعيل"}</button>
          <button class="small danger" onClick=${() => remove(b)}>حذف</button></div></li>`;
    })}</ul></div>` : html`<${Empty}>لا توجد إعلانات مثبتة<//>`}<//>
  </div>`;
}

// ------------------------------------------------------------------ student archive

export function ArchiveView() {
  const [q, setQ] = useState("");
  const state = useAsync(() => api.get(`/api/archive/students?limit=200&q=${encodeURIComponent(q)}`), [q]);
  return html`<div><h1>أرشيف الطلبة</h1>
    <p class="muted">الملف الشخصي لكل طالب ونسخ مستنداته. يُسجَّل كل اطلاع أو تنزيل أو تعديل في سجل التدقيق.</p>
    <input style="max-width:320px;margin-bottom:.75rem" placeholder="بحث بالاسم أو رقم القيد" value=${q} onInput=${(e) => setQ(e.target.value)} />
    <${Async} state=${state}>${(d) => html`<div class="card"><p class="small muted">${d.total} طالب</p><div class="table-wrap"><table>
      <thead><tr><th>الطالب</th><th>رقم القيد</th><th>القسم</th><th>الدفعة</th><th class="num">المستندات</th><th>الملف</th></tr></thead>
      <tbody>${d.items.map((s) => html`<tr style="cursor:pointer" onClick=${() => navigate(`#/archive/${s.id}`)}>
        <td><a href=${`#/archive/${s.id}`}>${s.full_name}</a></td><td class="mono">${s.code || ""}</td><td>${s.department || ""}</td>
        <td>${s.cohort || ""}</td><td class="num">${s.documents}</td>
        <td>${s.has_record ? html`<${Chip} kind="success">مكتمل جزئياً<//>` : html`<${Chip}>لا يوجد<//>`}</td></tr>`)}</tbody></table></div></div>`}<//>
  </div>`;
}

const RECORD_FIELDS = [
  ["national_id", "الرقم الوطني", "text"], ["birth_date", "تاريخ الميلاد", "date"], ["birth_place", "مكان الميلاد", "text"],
  ["nationality", "الجنسية", "text"], ["gender", "الجنس", "gender"], ["address", "العنوان", "text"],
  ["guardian_name", "اسم ولي الأمر", "text"], ["guardian_relation", "صلة القرابة", "text"], ["guardian_phone", "هاتف ولي الأمر", "text"],
  ["high_school", "المدرسة الثانوية", "text"], ["high_school_year", "سنة الحصول على الثانوية", "text"],
  ["high_school_score", "نسبة الثانوية %", "number"], ["admission_date", "تاريخ القبول", "date"], ["status", "حالة القيد", "status"],
];

function DocViewer({ doc, onClose }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    blobUrl(`/api/archive/documents/${doc.id}/file?inline=true`).then(setUrl).catch(setErr);
  }, [doc.id]);
  const isImage = /image\//.test(doc.file.content_type);
  return html`<${Modal} title=${doc.title} onClose=${() => { if (url) URL.revokeObjectURL(url); onClose(); }}>
    <${ErrorBox} error=${err} />
    ${url ? (isImage ? html`<img class="selfie" src=${url} alt=${doc.title} />`
      : html`<p><a class="btn" href=${url} download=${doc.file.name}>تنزيل ${doc.file.name}</a></p>`) : html`<p class="muted">جارٍ التحميل…</p>`}
    <p class="small muted">تم تسجيل اطلاعك على هذا المستند في سجل التدقيق.</p><//>`;
}

export function ArchiveDetail({ id }) {
  const meta = useAsync(() => api.get("/api/archive/meta"), []);
  const state = useAsync(() => api.get(`/api/archive/students/${id}`), [id]);
  const [viewing, setViewing] = useState(null);
  return html`<${Async} state=${state}>${(d) => html`<div>
    <div class="row"><a href="#/archive">← أرشيف الطلبة</a></div>
    <h1>${d.student.full_name}</h1>
    <p class="muted"><span class="mono">${d.student.code}</span> · ${d.student.department || ""} · دفعة ${d.student.cohort || "—"}
      · <span class="ltr">${d.student.email || d.student.phone || ""}</span></p>
    <div class="grid cols-2">
      <${RecordForm} id=${id} record=${d.record} statuses=${meta.data?.statuses || {}} onSaved=${state.reload} />
      <div>
        <${UploadDoc} id=${id} meta=${meta.data} onDone=${state.reload} />
        <div class="card"><h3>المستندات (${d.documents.length})</h3>${d.documents.length ? html`<ul class="list">${d.documents.map((doc) => html`<li>
          <div class="row between"><strong>${doc.title}</strong><${Chip}>${doc.type_label}<//></div>
          <div class="small muted">${doc.file.name} · أُضيف ${fmtDate(doc.created_at)} بواسطة ${doc.uploaded_by || ""}</div>
          ${doc.notes ? html`<div class="small">${doc.notes}</div>` : null}
          <div class="row" style="margin-top:.3rem"><button class="small" onClick=${() => setViewing(doc)}>عرض / تنزيل</button>
            <button class="small secondary" onClick=${async () => {
              const reason = prompt("سبب الحذف (يبقى المستند محفوظاً في السجل):");
              if (!reason || reason.trim().length < 3) return;
              await api.post(`/api/archive/documents/${doc.id}/delete`, { reason }).catch(toastError);
              state.reload();
            }}>حذف</button></div></li>`)}</ul>` : html`<${Empty}>لا توجد مستندات<//>`}</div>
      </div>
    </div>
    ${viewing ? html`<${DocViewer} doc=${viewing} onClose=${() => setViewing(null)} />` : null}
  </div>`}<//>`;
}

function RecordForm({ id, record, statuses, onSaved }) {
  const init = {};
  for (const [k] of RECORD_FIELDS) init[k] = record[k] ?? "";
  const [v, bind] = useForm(init);
  const [submit, busy, error] = useSubmit(async () => {
    const body = {};
    for (const [k, , type] of RECORD_FIELDS) {
      const val = v[k];
      body[k] = val === "" ? null : type === "number" ? Number(val) : val;
    }
    if (!body.status) body.status = "active";
    await api.put(`/api/archive/students/${id}/record`, body);
    toast("تم حفظ الملف");
    onSaved();
  });
  return html`<form class="card" onSubmit=${submit}><h3>البيانات الشخصية</h3><${ErrorBox} error=${error} />
    <div class="form-grid">${RECORD_FIELDS.map(([k, label, type]) => html`<div class="field"><label>${label}</label>
      ${type === "gender" ? html`<select ...${bind(k)}><option value="">—</option><option value="male">ذكر</option><option value="female">أنثى</option></select>`
        : type === "status" ? html`<select ...${bind(k)}>${Object.entries(statuses).map(([s, l]) => html`<option value=${s}>${l}</option>`)}</select>`
          : html`<input type=${type} step=${type === "number" ? "0.01" : null} ...${bind(k)} />`}</div>`)}</div>
    <div class="field"><label>ملاحظات</label><textarea ...${bind("notes")}></textarea></div>
    <p class="small muted">الرقم الوطني يُحفظ مشفراً. ${record.updated_at ? `آخر تحديث ${fmtDate(record.updated_at)} بواسطة ${record.updated_by || ""}` : ""}</p>
    <button disabled=${busy}>حفظ البيانات</button></form>`;
}

function UploadDoc({ id, meta, onDone }) {
  const [v, bind] = useForm({ doc_type: "national_id", title: "", notes: "" });
  const [file, setFile] = useState(null);
  const [submit, busy, error] = useSubmit(async (e) => {
    const fd = new FormData();
    Object.entries(v).forEach(([k, x]) => fd.append(k, x));
    fd.append("upload", file);
    await api.form(`/api/archive/students/${id}/documents`, fd);
    toast("تمت إضافة المستند");
    e?.target?.reset?.();
    setFile(null);
    onDone();
  });
  return html`<form class="card" onSubmit=${submit}><h3>إضافة مستند</h3><${ErrorBox} error=${error} />
    <div class="field"><label>نوع المستند</label><select ...${bind("doc_type")}>
      ${Object.entries(meta?.doc_types || {}).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <div class="field"><label>العنوان (اختياري)</label><input ...${bind("title")} /></div>
    <div class="field"><label>ملاحظات (اختياري)</label><input ...${bind("notes")} /></div>
    <div class="field"><label>الملف: PDF أو صورة، حتى ${meta?.max_file_mb || 10}MB (يُحفظ مشفراً)</label>
      <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange=${(e) => setFile(e.target.files[0] || null)} required /></div>
    <button disabled=${busy || !file}>${busy ? "جارٍ الرفع…" : "رفع المستند"}</button></form>`;
}
