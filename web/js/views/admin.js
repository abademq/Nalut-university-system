import { html, useState, useEffect, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, Modal, ROLE, fmtDate } from "../ui.js";
import { api, setActing } from "../api.js";

const CREATABLE = {
  university_admin: ["student", "teacher", "assistant", "staff", "faculty_admin"],
  faculty_admin: ["student", "teacher", "assistant", "staff"],
};
// roles this account may create or edit (the platform administrator also manages university admins)
function creatable(user) {
  if (user.acting) return [...CREATABLE.university_admin, "university_admin"];
  if (user.role === "faculty_admin" && !(user.can || []).includes("users.manage")) return [];
  return CREATABLE[user.role] || [];
}
const OFFICES = { registrar: "التسجيل", student_affairs: "شؤون الطلبة", exams: "الامتحانات" };

function TempPassword({ value, onClose }) {
  return html`<${Modal} title="كلمة المرور المؤقتة" onClose=${onClose}>
    <p>سلّم كلمة المرور التالية للمستخدم عبر قناة آمنة. لن تظهر مرة أخرى، وسيُطلب منه تغييرها عند أول دخول.</p>
    <p class="qr-code mono" style="text-align:center">${value}</p>
    <button onClick=${onClose}>تم</button><//>`;
}

function CreateUser({ user, structure, onCreated }) {
  const [v, bind] = useForm({ full_name: "", role: "student", email: "", phone: "", code: "", cohort: "", office: "",
    faculty_id: user.faculty?.id || "", department_id: "" });
  const [submit, busy, error] = useSubmit(async () => {
    const body = { ...v, faculty_id: v.faculty_id ? Number(v.faculty_id) : null, department_id: v.department_id ? Number(v.department_id) : null };
    for (const k of ["email", "phone", "code", "cohort", "office"]) if (!body[k]) body[k] = null;
    const r = await api.post("/api/users", body);
    onCreated(r.temporary_password);
  });
  const fac = (structure.faculties || []).find((f) => String(f.id) === String(v.faculty_id));
  return html`<form class="card" onSubmit=${submit}><h3>مستخدم جديد</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>الاسم الكامل</label><input ...${bind("full_name")} required /></div>
      <div class="field"><label>الدور</label><select ...${bind("role")}>${creatable(user).map((r) => html`<option value=${r}>${ROLE[r]}</option>`)}</select></div>
      <div class="field"><label>البريد الإلكتروني</label><input type="email" class="ltr" ...${bind("email")} /></div>
      <div class="field"><label>رقم الهاتف</label><input class="ltr" ...${bind("phone")} /></div>
      <div class="field"><label>${v.role === "student" ? "رقم القيد" : "الرقم الوظيفي"}</label><input class="ltr" ...${bind("code")} /></div>
      ${user.role === "university_admin" ? html`<div class="field"><label>الكلية</label><select ...${bind("faculty_id")}><option value="">—</option>
        ${(structure.faculties || []).map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
      <div class="field"><label>القسم</label><select ...${bind("department_id")}><option value="">—</option>
        ${(fac?.departments || []).map((d) => html`<option value=${d.id}>${d.name}</option>`)}</select></div>
      ${v.role === "student" ? html`<div class="field"><label>الدفعة</label><input ...${bind("cohort")} /></div>` : null}
      ${v.role === "staff" ? html`<div class="field"><label>المكتب</label><select ...${bind("office")}><option value="">—</option>
        ${Object.entries(OFFICES).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>` : null}
    </div>
    <p class="small muted">تُجمع البيانات الضرورية فقط. يُشترط البريد أو الهاتف لتسجيل الدخول.</p>
    <button disabled=${busy}>إنشاء الحساب</button></form>`;
}

export function UsersView({ user }) {
  const [filters, setFilters] = useState({ role: "", q: "" });
  const state = useAsync(() => api.get(`/api/users?limit=200&role=${filters.role}&q=${encodeURIComponent(filters.q)}`), [filters.role, filters.q]);
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const [creating, setCreating] = useState(false);
  const [temp, setTemp] = useState(null);
  const toggle = async (u) => {
    if (!confirm(u.is_active ? "إيقاف الحساب؟" : "تفعيل الحساب؟")) return;
    await api.patch(`/api/users/${u.id}`, { is_active: !u.is_active }).catch(toastError);
    state.reload();
  };
  const reset = async (u) => {
    if (!confirm(`إعادة تعيين كلمة مرور ${u.full_name}؟`)) return;
    const r = await api.post(`/api/users/${u.id}/reset-password`).catch(toastError);
    if (r) setTemp(r.temporary_password);
  };
  const facName = (id) => structure.data?.faculties.find((f) => f.id === id)?.name || "";
  const [editing, setEditing] = useState(null);
  return html`<div>
    <div class="row between"><h1>المستخدمون</h1>${creatable(user).length ? html`<button onClick=${() => setCreating(!creating)}>${creating ? "إلغاء" : "+ مستخدم"}</button>` : null}</div>
    ${creating && structure.data ? html`<${CreateUser} user=${user} structure=${structure.data} onCreated=${(pw) => { setCreating(false); setTemp(pw); state.reload(); }} />` : null}
    <div class="row" style="margin-bottom:.75rem">
      <input style="max-width:280px" placeholder="بحث بالاسم أو الرقم أو البريد أو الهاتف" value=${filters.q} onInput=${(e) => setFilters({ ...filters, q: e.target.value })} />
      <select style="max-width:200px" value=${filters.role} onChange=${(e) => setFilters({ ...filters, role: e.target.value })}>
        <option value="">كل الأدوار</option>${Object.entries(ROLE).filter(([k]) => k !== "platform_admin").map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <${Async} state=${state}>${(d) => html`<div class="card"><p class="small muted">${d.total} مستخدم</p><div class="table-wrap"><table>
      <thead><tr><th>الاسم</th><th>الدور</th><th>الرقم</th><th>الكلية</th><th>التواصل</th><th>الحالة</th><th></th></tr></thead>
      <tbody>${d.items.map((u) => html`<tr><td>${u.full_name}</td><td>${ROLE[u.role]}</td><td class="mono">${u.code || ""}</td>
        <td class="small">${facName(u.faculty_id)}</td><td class="small ltr">${u.email || u.phone || ""}</td>
        <td>${u.is_active ? html`<${Chip} kind="success">نشط<//>` : html`<${Chip} kind="danger">موقوف<//>`} ${u.mfa_enabled ? html`<${Chip} kind="info">2FA<//>` : null}</td>
        <td>${u.id !== user.id && creatable(user).includes(u.role) ? html`<div class="row">
          <button class="small secondary" onClick=${() => setEditing(u)}>تعديل</button>
          <button class="small secondary" onClick=${() => toggle(u)}>${u.is_active ? "إيقاف" : "تفعيل"}</button>
          <button class="small secondary" onClick=${() => reset(u)}>كلمة مرور</button></div>` : null}</td></tr>`)}</tbody></table></div></div>`}<//>
    ${temp ? html`<${TempPassword} value=${temp} onClose=${() => setTemp(null)} />` : null}
    ${editing ? html`<${EditUser} user=${user} target=${editing} structure=${structure.data} onClose=${() => setEditing(null)}
      onSaved=${() => { setEditing(null); state.reload(); }} />` : null}
  </div>`;
}

function EditUser({ user, target, structure, onClose, onSaved }) {
  const [v, bind] = useForm({ full_name: target.full_name, role: target.role, email: target.email || "", phone: target.phone || "",
    code: target.code || "", cohort: target.cohort || "", office: target.office || "", faculty_id: target.faculty_id || "",
    department_id: target.department_id || "" });
  const [submit, busy, error] = useSubmit(async () => {
    const body = { ...v, faculty_id: v.faculty_id ? Number(v.faculty_id) : null, department_id: v.department_id ? Number(v.department_id) : null };
    for (const k of ["email", "phone", "code", "cohort", "office"]) if (!body[k]) body[k] = null;
    if (user.role !== "university_admin") delete body.faculty_id;
    await api.patch(`/api/users/${target.id}`, body);
    toast("تم حفظ التعديلات");
    onSaved();
  });
  const fac = (structure?.faculties || []).find((f) => String(f.id) === String(v.faculty_id || user.faculty?.id));
  return html`<${Modal} title=${`تعديل: ${target.full_name}`} onClose=${onClose}><form onSubmit=${submit}><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>الاسم الكامل</label><input ...${bind("full_name")} required /></div>
      <div class="field"><label>الدور</label><select ...${bind("role")}>${creatable(user).map((r) => html`<option value=${r}>${ROLE[r]}</option>`)}</select></div>
      <div class="field"><label>البريد الإلكتروني</label><input type="email" class="ltr" ...${bind("email")} /></div>
      <div class="field"><label>الهاتف</label><input class="ltr" ...${bind("phone")} /></div>
      <div class="field"><label>رقم القيد / الرقم الوظيفي</label><input class="ltr" ...${bind("code")} /></div>
      ${user.role === "university_admin" ? html`<div class="field"><label>الكلية</label><select ...${bind("faculty_id")}><option value="">—</option>
        ${(structure?.faculties || []).map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
      <div class="field"><label>القسم</label><select ...${bind("department_id")}><option value="">—</option>
        ${(fac?.departments || []).map((d) => html`<option value=${d.id}>${d.name}</option>`)}</select></div>
      ${v.role === "student" ? html`<div class="field"><label>الدفعة</label><input ...${bind("cohort")} /></div>` : null}
      ${v.role === "staff" ? html`<div class="field"><label>المكتب</label><select ...${bind("office")}><option value="">—</option>
        ${Object.entries(OFFICES).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>` : null}
    </div>
    <${UserMfa} target=${target} />
    <button disabled=${busy}>حفظ</button></form><//>`;
}

// Second factor of one account: make it mandatory, or reset it (lost phone).
function UserMfa({ target }) {
  const state = useAsync(() => api.get(`/api/users/${target.id}`), [target.id]);
  const [info, setInfo] = useState(null);
  const d = info || state.data;
  const change = async (body) => {
    const r = await api.post(`/api/users/${target.id}/mfa`, body).catch(toastError);
    if (r) { setInfo({ ...d, ...r }); toast("تم الحفظ"); }
  };
  if (!d) return null;
  return html`<div class="card" style="margin:.75rem 0"><h4>التحقق الثنائي</h4>
    <p class="small">${d.mfa_enabled ? `مفعّل ${d.mfa_method === "sms" ? "برسالة نصية" : "بتطبيق المصادقة"}` : "غير مفعّل"}
      ${d.mfa_required ? " · إلزامي لهذا الحساب" : ""}</p>
    <label class="check"><input type="checkbox" checked=${!!d.mfa_forced} onChange=${(ev) => change({ required: ev.target.checked })} />
      إلزام هذا الحساب تحديداً بالتحقق الثنائي</label>
    ${d.mfa_enabled ? html`<button type="button" class="small secondary" onClick=${() => confirm("إعادة تعيين التحقق؟ سيُطلب من المستخدم إعداده من جديد عند الدخول.") && change({ reset: true })}>
      إعادة تعيين (فقد هاتفه)</button>` : null}
  </div>`;
}

function EditModal({ title, fields, initial, onSave, onClose }) {
  const [v, bind] = useForm(initial);
  const [submit, busy, error] = useSubmit(async () => { await onSave(v); onClose(); });
  return html`<${Modal} title=${title} onClose=${onClose}><form onSubmit=${submit}><${ErrorBox} error=${error} />
    ${fields.map(([k, label, type = "text", extra = {}]) => type === "checkbox"
      ? html`<label class="check"><input type="checkbox" ...${bind(k, "checkbox")} /> ${label}</label>`
      : type === "select" ? html`<div class="field"><label>${label}</label><select ...${bind(k)}>
          ${extra.options.map(([val, l]) => html`<option value=${val}>${l}</option>`)}</select></div>`
        : html`<div class="field"><label>${label}</label><input type=${type} ...${bind(k)} ...${extra} /></div>`)}
    <button disabled=${busy}>حفظ</button></form><//>`;
}

export function StructureView({ user }) {
  const state = useAsync(() => api.get("/api/org/structure"), []);
  const [fac, bindFac, setFac] = useForm({ name: "", code: "" });
  const [dep, bindDep, setDep] = useForm({ faculty_id: user.faculty?.id || "", name: "", code: "" });
  const [term, bindTerm] = useForm({ name: "", start_date: "", end_date: "", is_current: true });
  const [edit, setEdit] = useState(null);
  const [addFac, b1, e1] = useSubmit(async () => { await api.post("/api/org/faculties", fac); setFac({ name: "", code: "" }); toast("تمت الإضافة"); state.reload(); });
  const [addDep, b2, e2] = useSubmit(async () => { await api.post("/api/org/departments", { ...dep, faculty_id: Number(dep.faculty_id || user.faculty?.id) }); setDep({ ...dep, name: "", code: "" }); toast("تمت الإضافة"); state.reload(); });
  const [addTerm, b3, e3] = useSubmit(async () => { await api.post("/api/org/terms", term); toast("تمت الإضافة"); state.reload(); });
  const uni = user.role === "university_admin";
  const remove = async (path, label) => {
    if (!confirm(`حذف ${label}؟ يُسمح بالحذف فقط إذا لم يكن مرتبطاً بمستخدمين أو مقررات.`)) return;
    try { await api.del(path); toast("تم الحذف"); state.reload(); } catch (e) { toastError(e); }
  };
  const save = (path, msg = "تم الحفظ") => async (v) => { await api.patch(path, v); toast(msg); state.reload(); };
  return html`<div><h1>الهيكل التنظيمي</h1>
    ${!uni ? html`<p class="muted">تظهر هنا كليتك وأقسامها فقط. إدارة الكليات الأخرى من صلاحيات إدارة الجامعة.</p>` : null}
    <${Async} state=${state}>${(s) => html`<div class="grid cols-2">
      <div class="card"><h3>${uni ? "الكليات والأقسام" : "الكلية والأقسام"}</h3>${s.faculties.map((f) => html`<div style="margin-bottom:.9rem">
        <div class="row between"><span><strong>${f.name}</strong> <span class="small muted mono">${f.code}</span></span>
          ${uni ? html`<span class="row"><button class="ghost small" onClick=${() => setEdit({ title: "تعديل الكلية", path: `/api/org/faculties/${f.id}`,
            initial: { name: f.name, code: f.code }, fields: [["name", "الاسم"], ["code", "الرمز"]] })}>تعديل</button>
            <button class="ghost small" onClick=${() => remove(`/api/org/faculties/${f.id}`, f.name)}>حذف</button></span>` : null}</div>
        <ul class="list">${f.departments.map((d) => html`<li class="row between" style="padding:.35rem 0">
          <span>${d.name} <span class="small muted mono">${d.code}</span></span>
          <span class="row"><button class="ghost small" onClick=${() => setEdit({ title: "تعديل القسم", path: `/api/org/departments/${d.id}`,
            initial: { name: d.name, code: d.code }, fields: [["name", "الاسم"], ["code", "الرمز"]] })}>تعديل</button>
            <button class="ghost small" onClick=${() => remove(`/api/org/departments/${d.id}`, d.name)}>حذف</button></span></li>`)}</ul></div>`)}</div>
      <div class="card"><h3>الفصول الدراسية</h3>${s.terms.length ? html`<ul class="list">${s.terms.map((t) => html`<li>
        <div class="row between"><span><strong>${t.name}</strong> ${t.is_current ? html`<${Chip} kind="success">الحالي<//>` : null}</span>
          ${uni ? html`<span class="row"><button class="ghost small" onClick=${() => setEdit({ title: "تعديل الفصل الدراسي", path: `/api/org/terms/${t.id}`,
            initial: { name: t.name, start_date: t.start_date, end_date: t.end_date, is_current: t.is_current },
            fields: [["name", "الاسم"], ["start_date", "البداية", "date"], ["end_date", "النهاية", "date"], ["is_current", "الفصل الحالي", "checkbox"]] })}>تعديل</button>
            <button class="ghost small" onClick=${() => remove(`/api/org/terms/${t.id}`, t.name)}>حذف</button></span>` : null}</div>
        <div class="small muted ltr" style="text-align:right">${t.start_date} → ${t.end_date}</div></li>`)}</ul>` : html`<${Empty} />`}</div>
    </div>`}<//>
    <div class="grid cols-3">
      ${uni ? html`<form class="card" onSubmit=${addFac}><h3>كلية جديدة</h3><${ErrorBox} error=${e1} />
        <div class="field"><label>الاسم</label><input ...${bindFac("name")} required /></div>
        <div class="field"><label>الرمز</label><input class="ltr" ...${bindFac("code")} required /></div><button disabled=${b1}>إضافة</button></form>` : null}
      <form class="card" onSubmit=${addDep}><h3>قسم جديد</h3><${ErrorBox} error=${e2} />
        ${uni ? html`<div class="field"><label>الكلية</label><select ...${bindDep("faculty_id")} required><option value="">—</option>
          ${(state.data?.faculties || []).map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
        <div class="field"><label>الاسم</label><input ...${bindDep("name")} required /></div>
        <div class="field"><label>الرمز</label><input class="ltr" ...${bindDep("code")} required /></div><button disabled=${b2}>إضافة</button></form>
      ${uni ? html`<form class="card" onSubmit=${addTerm}><h3>فصل دراسي</h3><${ErrorBox} error=${e3} />
        <div class="field"><label>الاسم</label><input ...${bindTerm("name")} required /></div>
        <div class="form-grid"><div class="field"><label>البداية</label><input type="date" ...${bindTerm("start_date")} required /></div>
        <div class="field"><label>النهاية</label><input type="date" ...${bindTerm("end_date")} required /></div></div>
        <label class="check"><input type="checkbox" ...${bindTerm("is_current", "checkbox")} /> الفصل الحالي</label><button disabled=${b3}>إضافة</button></form>` : null}
    </div>
    ${edit ? html`<${EditModal} title=${edit.title} fields=${edit.fields} initial=${edit.initial} onSave=${save(edit.path)} onClose=${() => setEdit(null)} />` : null}
  </div>`;
}

// Delivery status for the administration: is push / SMS configured, last 24 hours, last errors,
// and a test push to the administrator's own phones (one per priority, each with its tone).
function NotificationStatus() {
  const state = useAsync(() => api.get("/api/notifications/health"), []);
  const [busy, setBusy] = useState(null);
  const test = async (priority) => {
    setBusy(priority);
    const r = await api.post("/api/notifications/test-push", { priority }).catch(toastError);
    setBusy(null);
    if (!r) return;
    if (r.provider === "logpush" || r.provider === "log") toast("الإشعارات الفورية غير مفعلة على الخادم (ملف Firebase غير موجود)", "error");
    else if (!r.devices) toast("لا يوجد هاتف مسجل لحسابك: سجّل الدخول من تطبيق الهاتف واسمح بالإشعارات", "error");
    else if (!r.sent) toast(`رفض Firebase الإرسال: ${r.error || "سبب غير معروف"}`, "error");
    else toast(`أُرسل إلى ${r.sent} من ${r.devices} جهاز (النغمة: ${r.tone})`, "success");
    state.reload();
  };
  const PUSH = { sent: "وصل", failed: "فشل", no_device: "بلا هاتف مسجل", pending: "قيد الإرسال", skipped: "لم يُرسل" };
  const SMS = { sent: "أُرسلت", failed: "فشلت", no_phone: "بلا رقم", skipped: "لم تُرسل", pending: "قيد الإرسال" };
  const counts = (obj, names) => Object.entries(obj || {}).map(([k, n]) => `${names[k] || k}: ${n}`).join(" · ") || "لا شيء";
  return html`<div class="card"><h3>حالة الإشعارات والرسائل</h3>
    <p class="small muted">إعدادات الإشعارات تديرها الإدارة من هنا فقط، ولا يغيّرها المستخدمون من التطبيق.</p>
    <${Async} state=${state}>${(h) => html`
      <ul class="list">
        <li>${h.push_ready ? "✅" : "❌"} الإشعارات الفورية (Firebase) — ${h.push_ready ? "مفعلة" : "غير مفعلة: ملف /etc/nus/firebase.json غير موجود"} · هواتف مسجلة: ${h.users_with_devices}</li>
        <li>${h.sms_ready ? "✅" : "❌"} الرسائل النصية — ${h.sms_ready ? `المزود: ${h.sms_provider}` : "غير مفعلة: أضف SMS_PROVIDER=resala في /etc/nus/nus.env"}</li>
        <li class="small">آخر 24 ساعة — إشعارات: ${counts(h.last_24h.push, PUSH)}<br />رسائل: ${counts(h.last_24h.sms, SMS)}</li>
        ${h.last_push_error ? html`<li class="small">آخر خطأ Firebase (${fmtDate(h.last_push_error_at)}): <span class="ltr">${h.last_push_error}</span></li>` : null}
        ${h.last_sms_error ? html`<li class="small">آخر خطأ رسائل: <strong>${h.last_sms_error.summary || h.last_sms_error.message}</strong></li>` : null}
      </ul>`}<//>
    <h4>تجربة على هاتفي</h4>
    <div class="row">
      <button type="button" class="secondary small" disabled=${!!busy} onClick=${() => test("normal")}>عادي</button>
      <button type="button" class="secondary small" disabled=${!!busy} onClick=${() => test("important")}>مهم</button>
      <button type="button" class="secondary small" disabled=${!!busy} onClick=${() => test("urgent")}>عاجل</button>
    </div></div>`;
}

// Sends one SMS to the administrator's own phone and shows exactly what the provider answered.
function SmsCheck() {
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (kind) => {
    setBusy(true);
    setRes(await api.post("/api/notifications/test-sms", { kind }).catch((e) => ({ ok: false, error_message: e.message })));
    setBusy(false);
  };
  return html`<div class="card"><h3>فحص الرسائل النصية</h3>
    <p class="small muted">يرسل رسالة واحدة إلى رقم هاتف حسابك ويعرض رد مزود الرسائل كما هو.</p>
    <div class="row"><button type="button" class="secondary small" disabled=${busy} onClick=${() => run("otp")}>رمز تحقق تجريبي</button>
      <button type="button" class="secondary small" disabled=${busy} onClick=${() => run("template")}>رسالة إشعار تجريبية</button></div>
    ${res ? html`<div class=${`alert ${res.ok ? "success" : "error"}`} style="margin-top:.75rem">
      <strong>${res.ok ? "✅ " : "❌ "}${res.summary || (res.ok ? "تم القبول" : res.error_message || "فشل الإرسال")}</strong>
      <details style="margin-top:.4rem"><summary class="small">التفاصيل التقنية</summary>
        <div class="small ltr" style="white-space:pre-wrap;margin-top:.4rem">${JSON.stringify(res, null, 1)}</div></details></div>` : null}
  </div>`;
}

export function SettingsView({ user }) {
  const state = useAsync(() => api.get("/api/settings"), []);
  const acting = !!user?.acting;
  return html`<div><h1>إعدادات المؤسسة</h1><${Async} state=${state}>${(d) => html`
    ${acting ? html`<div class="alert info">شاشة بداية التطبيق ونغمة التشغيل ونغمات الإشعارات في صفحة مستقلة: <a href="#/launch">شاشة البداية والنغمات</a></div>` : null}
    <${SettingsForm} data=${d} acting=${acting} onSaved=${state.reload} />`}<//>
    <${NotificationStatus} /><${SmsCheck} /></div>`;
}

/** Launch screen, start-up sound and notification tones on their own page (platform administrator). */
export function LaunchView({ user }) {
  const state = useAsync(() => api.get("/api/settings"), []);
  if (!user?.acting) {
    return html`<div><h1>شاشة البداية والنغمات</h1><div class="alert info">يحددها مشرف المنصة فقط: سجّل الدخول بحساب مشرف المنصة.</div></div>`;
  }
  return html`<div><h1>شاشة البداية والنغمات</h1><${Async} state=${state}>${(d) => html`
    <${LaunchSettings} data=${d} universityId=${user.university?.id} onSaved=${state.reload} />
    <${ToneSettings} data=${d} onSaved=${state.reload} />`}<//></div>`;
}

/** The tone each kind of notification plays on phones; saved on its own. */
function ToneSettings({ data, onSaved }) {
  const toneInfo = useAsync(() => api.get("/api/notifications/tones"), []);
  const [tones, setTones] = useState(data.effective.notifications.tones || {});
  const [submit, busy, error] = useSubmit(async () => {
    await api.put("/api/settings", { settings: { notifications: { ...data.effective.notifications, tones } } });
    toast("حُفظت نغمات الإشعارات");
    onSaved();
  });
  return html`<form onSubmit=${submit}><${ErrorBox} error=${error} /><div class="card"><h3>نغمات الإشعارات</h3>
    <p class="small muted">نغمة كل نوع على الهواتف، وتصل كما هي لكل المستخدمين. اضغط ▶ للاستماع.</p>
    ${toneInfo.data ? html`<div class="form-grid">${toneInfo.data.slots.map((s) => html`<div class="field"><label>${s.label}</label>
      <div class="row"><select value=${tones[s.slot] || s.tone} onChange=${(ev) => setTones({ ...tones, [s.slot]: ev.target.value })}>
        ${toneInfo.data.library.map((t) => html`<option value=${t.name}>${t.label}</option>`)}</select>
      <button type="button" class="small secondary" aria-label="تشغيل النغمة" onClick=${() => playSound(tones[s.slot] || s.tone)}>▶</button></div></div>`)}</div>`
      : html`<p class="small muted">جارٍ التحميل…</p>`}
    <button disabled=${busy}>حفظ النغمات</button></div></form>`;
}

const playSound = (name) => { if (name && name !== "none") new Audio(`/static/tones/tone_${name}.wav`).play().catch(() => {}); };

/** The app's launch screen and start-up sound: platform administrator only (acting as the university). */
function LaunchSettings({ data, universityId, onSaved }) {
  const l = data.effective.launch;
  const [v, bind] = useForm({ enabled: l.enabled, seconds: l.duration_ms / 1000, title: l.title, subtitle: l.subtitle,
    background: l.background, foreground: l.foreground, accent: l.accent, show_loader: l.show_loader, sound: l.sound });
  const sounds = useAsync(() => api.get("/api/app/sounds"), []);
  const info = useAsync(() => api.get(`/api/app/launch?u=${universityId}`), [universityId]);
  const [imgUrl, setImgUrl] = useState(null);
  const version = info.data?.image_version;
  useEffect(() => { setImgUrl(version ? `/api/app/launch/image?u=${universityId}&v=${version}` : null); }, [version]);
  const [submit, busy, error] = useSubmit(async () => {
    await api.put("/api/settings", { settings: { launch: {
      enabled: v.enabled, duration_ms: Math.round(Number(v.seconds) * 1000), title: v.title, subtitle: v.subtitle,
      background: v.background, foreground: v.foreground, accent: v.accent, show_loader: v.show_loader, sound: v.sound } } });
    toast("حُفظت شاشة البداية، وتظهر في التطبيق من التشغيل التالي");
    onSaved();
  });
  const upload = async (ev) => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("upload", file);
    try { await api.form("/api/app/launch/image", fd); toast("رُفعت الصورة"); info.reload(); } catch (e) { toastError(e); }
  };
  const removeImage = async () => {
    try { await api.del("/api/app/launch/image"); toast("عادت صورة الشعار الافتراضية"); info.reload(); } catch (e) { toastError(e); }
  };
  return html`<form onSubmit=${submit}><${ErrorBox} error=${error} />
    <div class="card"><h3>شاشة البداية ونغمة التشغيل (مشرف المنصة)</h3>
      <p class="small muted">تظهر عند فتح التطبيق قبل تسجيل الدخول. يحفظها الهاتف ويحدّثها في الخلفية، فيظهر التعديل من التشغيل التالي للتطبيق.</p>
      <div class="row" style="align-items:flex-start;gap:1.25rem;flex-wrap:wrap">
        <div style=${{ background: v.background, color: v.foreground, width: "190px", height: "340px", borderRadius: "22px",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "14px", textAlign: "center",
          boxShadow: "0 4px 18px rgba(0,0,0,.18)" }} aria-label="معاينة شاشة البداية">
          <img src=${imgUrl || "/static/icon.svg"} alt="" style=${{ maxWidth: "120px", maxHeight: "120px", objectFit: "contain" }}
            onError=${(e) => { e.target.style.visibility = "hidden"; }} />
          <strong style=${{ marginTop: "12px", fontSize: "15px" }}>${v.title}</strong>
          <span style=${{ color: v.accent, fontSize: "12px", marginTop: "4px" }}>${v.subtitle || data.university.name}</span>
          ${v.show_loader ? html`<span style=${{ marginTop: "18px", width: "16px", height: "16px", borderRadius: "50%",
            border: `2px solid ${v.accent}`, borderTopColor: "transparent" }}></span>` : null}
        </div>
        <div style="flex:1;min-width:240px">
          <label class="check"><input type="checkbox" ...${bind("enabled", "checkbox")} /> عرض شاشة البداية عند فتح التطبيق</label>
          <div class="form-grid">
            <div class="field"><label>المدة (ثانية)</label><input type="number" min="0" max="6" step="0.1" ...${bind("seconds")} /></div>
            <div class="field"><label>العنوان</label><input maxlength="60" ...${bind("title")} /></div>
            <div class="field"><label>السطر الثاني (فارغ = اسم الجامعة)</label><input maxlength="80" ...${bind("subtitle")} /></div>
            <div class="field"><label>لون الخلفية</label><input type="color" ...${bind("background")} /></div>
            <div class="field"><label>لون العنوان</label><input type="color" ...${bind("foreground")} /></div>
            <div class="field"><label>لون السطر الثاني والمؤشر</label><input type="color" ...${bind("accent")} /></div>
          </div>
          <label class="check"><input type="checkbox" ...${bind("show_loader", "checkbox")} /> إظهار مؤشر التحميل</label>
          <div class="field"><label>نغمة التشغيل</label><div class="row">
            <select ...${bind("sound")}>
              <option value="none">بدون صوت</option>
              ${sounds.data ? html`<optgroup label="نغمات التشغيل">${sounds.data.launch.map((t) => html`<option value=${t.name}>${t.label}</option>`)}</optgroup>
                <optgroup label="نغمات الإشعارات">${sounds.data.tones.map((t) => html`<option value=${t.name}>${t.label}</option>`)}</optgroup>` : null}
            </select>
            <button type="button" class="small secondary" aria-label="تشغيل النغمة" onClick=${() => playSound(v.sound)}>▶</button></div></div>
          <div class="field"><label>الصورة (PNG أو JPG حتى 2 ميغابايت، يفضّل خلفية شفافة)</label>
            <div class="row"><input type="file" accept="image/png,image/jpeg" onChange=${upload} />
              ${version ? html`<button type="button" class="small secondary" onClick=${removeImage}>إرجاع الشعار الافتراضي</button>` : null}</div></div>
        </div>
      </div>
      <button disabled=${busy}>حفظ شاشة البداية</button>
    </div></form>`;
}

const HINTS = {
  due_reminder_hours: "قبل كم ساعة من موعد التسليم يُرسل تذكير تلقائي للطلبة الذين لم يسلّموا.",
  late_after_minutes: "إذا سجّل الطالب حضوره بعد هذه المدة من بداية المحاضرة يُعلَّم «متأخر» بدل «حاضر».",
  rotation_seconds: "كل كم ثانية يتغير رمز QR المعروض. كلما قلّت المدة صعُب تمرير صورة الرمز لطالب غائب (15 ثانية مناسبة).",
  warning_absence_percent: "عند بلوغ نسبة غياب الطالب في مقرر هذه القيمة يصله تنبيه تحذيري.",
  limit_absence_percent: "الحد الأقصى المعتمد للغياب. عند تجاوزه يُنبَّه الطالب وأستاذ المقرر وإدارة الكلية لاتخاذ الإجراء وفق اللوائح (بقرار بشري، لا تلقائياً).",
  review_threshold: "كل تسجيل حضور يحصل على نقاط مخاطر من مؤشرات مثل: خارج نطاق القاعة (50)، جهاز مشترك مع طالب آخر (60)، جهاز استُخدم لحساب آخر مؤخراً (30)، جهاز جديد (15). إذا بلغ المجموع هذه القيمة لا يُعتمد الحضور تلقائياً ويُحال «للمراجعة» ليقبله أو يرفضه الأستاذ. قيمة أقل = تشدد أكثر.",
  selfie_retention_days: "بعد هذه المدة تُحذف صور التحقق الحية تلقائياً من الخادم حمايةً للخصوصية.",
  pass_mark: "النسبة الدنيا للنجاح في المقرر.",
  low_performance_percent: "إذا قلّ متوسط درجات الطالب في مهام مقرر عن هذه النسبة يظهر ضمن «طلبة يحتاجون متابعة».",
};

function SettingsForm({ data, acting, onSaved }) {
  const e = data.effective;
  const [v, bind] = useForm({
    display_name: e.branding.display_name || data.university.name, primary_color: e.branding.primary_color, accent_color: e.branding.accent_color,
    require_mfa: e.security.require_mfa_for_admins, first_login_otp: e.security.first_login_otp !== false, sms_enabled: e.notifications.sms_enabled, due_reminder_hours: e.notifications.due_reminder_hours,
    late_after_minutes: e.attendance.late_after_minutes, rotation_seconds: e.attendance.rotation_seconds,
    warning_absence_percent: e.attendance.warning_absence_percent, limit_absence_percent: e.attendance.limit_absence_percent,
    review_threshold: e.attendance.review_threshold, selfie_retention_days: e.attendance.selfie_retention_days,
    pass_mark: e.grading.pass_mark, low_performance_percent: e.grading.low_performance_percent,
  });
  const n = (k) => Number(v[k]);
  const [mfaMethods, setMfaMethods] = useState(e.security.mfa_methods || ["totp", "sms"]);
  const [mfaRoles, setMfaRoles] = useState(e.security.mfa_required_roles || []);
  const [mfaCaps, setMfaCaps] = useState(e.security.mfa_required_capabilities || []);
  const caps = useAsync(() => api.get("/api/permissions"), []);
  const toneInfo = useAsync(() => api.get("/api/notifications/tones"), []);
  const [tones, setTones] = useState(e.notifications.tones || {});
  const flip = (list, set, k) => set(list.includes(k) ? list.filter((x) => x !== k) : [...list, k]);
  const [submit, busy, error] = useSubmit(async () => {
    await api.put("/api/settings", { settings: {
      branding: { display_name: v.display_name, primary_color: v.primary_color, accent_color: v.accent_color },
      security: { ...e.security, require_mfa_for_admins: v.require_mfa, first_login_otp: v.first_login_otp, mfa_methods: mfaMethods,
        mfa_required_roles: mfaRoles, mfa_required_capabilities: mfaCaps },
      notifications: { ...e.notifications, sms_enabled: v.sms_enabled, due_reminder_hours: n("due_reminder_hours"),
        tones: acting ? tones : e.notifications.tones },
      attendance: { ...e.attendance, late_after_minutes: n("late_after_minutes"), rotation_seconds: n("rotation_seconds"),
        warning_absence_percent: n("warning_absence_percent"), limit_absence_percent: n("limit_absence_percent"),
        review_threshold: n("review_threshold"), selfie_retention_days: n("selfie_retention_days") },
      grading: { ...e.grading, pass_mark: n("pass_mark"), low_performance_percent: n("low_performance_percent") },
    } });
    toast("تم حفظ الإعدادات");
    onSaved();
  });
  const num = (k, label, extra = {}) => html`<div class="field"><label>${label}</label><input type="number" ...${bind(k)} ...${extra} />
    ${HINTS[k] ? html`<div class="small muted" style="margin-top:.2rem">${HINTS[k]}</div>` : null}</div>`;
  return html`<form onSubmit=${submit}><${ErrorBox} error=${error} />
    <div class="card"><h3>الهوية البصرية</h3><div class="form-grid">
      <div class="field"><label>الاسم المعروض</label><input ...${bind("display_name")} /></div>
      <div class="field"><label>اللون الأساسي</label><input type="color" ...${bind("primary_color")} /></div>
      <div class="field"><label>اللون الثانوي</label><input type="color" ...${bind("accent_color")} /></div></div></div>
    <div class="card"><h3>التحقق الثنائي</h3>
      <p class="small muted">رمز إضافي بعد كلمة المرور. يكفي سبب واحد ليصبح إلزامياً للحساب، ويمكن أيضاً إلزام حساب بعينه من صفحة المستخدمين.</p>
      <label class="check"><input type="checkbox" ...${bind("first_login_otp", "checkbox")} /> رمز برسالة نصية عند أول دخول لكل حساب جديد (يتأكد أن رقم الهاتف لصاحبه)</label>
      <p class="small muted">يُطلب مرة واحدة فقط، للحسابات التي أنشأتها الإدارة بكلمة مرور مؤقتة ولها رقم هاتف. أوقفه إذا كانت خدمة الرسائل متوقفة.</p>
      <h4>الطرق المتاحة للمستخدمين</h4>
      <label class="check"><input type="checkbox" checked=${mfaMethods.includes("sms")} onChange=${() => flip(mfaMethods, setMfaMethods, "sms")} /> رسالة نصية إلى هاتف الحساب</label>
      <label class="check"><input type="checkbox" checked=${mfaMethods.includes("totp")} onChange=${() => flip(mfaMethods, setMfaMethods, "totp")} /> تطبيق المصادقة (Google Authenticator وما يشبهه)</label>
      <h4>إلزامي لـ</h4>
      <label class="check"><input type="checkbox" ...${bind("require_mfa", "checkbox")} /> كل الحسابات الإدارية (إدارة الجامعة وإدارة الكلية)</label>
      ${["staff", "teacher", "assistant", "student"].map((r) => html`<label class="check"><input type="checkbox" checked=${mfaRoles.includes(r)}
        onChange=${() => flip(mfaRoles, setMfaRoles, r)} /> كل حسابات: ${ROLE[r]}</label>`)}
      <h4>ولكل من يملك صلاحية</h4>
      ${caps.data ? caps.data.capabilities.map((c) => html`<label class="check"><input type="checkbox" checked=${mfaCaps.includes(c.key)}
        onChange=${() => flip(mfaCaps, setMfaCaps, c.key)} /> ${c.label}</label>`) : html`<p class="small muted">جارٍ التحميل…</p>`}
    </div>
    <div class="card"><h3>نغمات الإشعارات على الهواتف</h3>
      <p class="small muted">${acting ? "تحدد نغمة كل نوع، وتصل كما هي لكل المستخدمين." : "يحددها مشرف المنصة، وتصل كما هي لكل المستخدمين."} اضغط ▶ لسماع النغمة.</p>
      ${toneInfo.data ? html`<div class="form-grid">${toneInfo.data.slots.map((s) => html`<div class="field"><label>${s.label}</label>
        <div class="row"><select disabled=${!acting} value=${tones[s.slot] || s.tone} onChange=${(ev) => setTones({ ...tones, [s.slot]: ev.target.value })}>
          ${toneInfo.data.library.map((t) => html`<option value=${t.name}>${t.label}</option>`)}</select>
        <button type="button" class="small secondary" aria-label="تشغيل النغمة"
          onClick=${() => new Audio(`/static/tones/tone_${tones[s.slot] || s.tone}.wav`).play().catch(() => {})}>▶</button></div></div>`)}</div>`
        : html`<p class="small muted">جارٍ التحميل…</p>`}
    </div>
    <div class="card"><h3>الإشعارات</h3>
      <label class="check"><input type="checkbox" ...${bind("sms_enabled", "checkbox")} /> تفعيل الرسائل النصية SMS للإشعارات العاجلة</label>
      <div class="form-grid">${num("due_reminder_hours", "التذكير قبل موعد التسليم (ساعة)")}</div></div>
    <div class="card"><h3>سياسة الحضور</h3><div class="form-grid">
      ${num("late_after_minutes", "يعتبر متأخراً بعد (دقيقة)")}${num("rotation_seconds", "مدة صلاحية رمز QR (ثانية)", { min: 5, max: 120 })}
      ${num("warning_absence_percent", "نسبة غياب للتنبيه %")}${num("limit_absence_percent", "حد الغياب المعتمد %")}
      ${num("review_threshold", "درجة المخاطر للمراجعة البشرية")}${num("selfie_retention_days", "مدة الاحتفاظ بالصور (يوم)")}</div></div>
    <div class="card"><h3>التقييم</h3><div class="form-grid">${num("pass_mark", "درجة النجاح %")}${num("low_performance_percent", "حد الأداء الضعيف %")}</div>
      <p class="small muted">سلم التقديرات: ${e.grading.scale.map(([m, l, a]) => `${l} (${a}) ≥ ${m}`).join(" · ")}</p></div>
    <button disabled=${busy}>حفظ الإعدادات</button></form>`;
}

export function AuditView() {
  const [action, setAction] = useState("");
  const state = useAsync(() => api.get(`/api/audit?limit=200${action ? `&action=${action}` : ""}`), [action]);
  const [verify, setVerify] = useState(null);
  return html`<div>
    <div class="row between"><h1>سجل التدقيق</h1>
      <button class="secondary" onClick=${() => api.get("/api/audit/verify").then(setVerify).catch(toastError)}>التحقق من سلامة السجل</button></div>
    ${verify ? html`<div class=${`alert ${verify.ok ? "success" : "error"}`}>${verify.ok ? `السجل سليم ومتسلسل (${verify.checked} عملية)` : `تم اكتشاف تعديل عند العملية #${verify.broken_at}`}</div>` : null}
    <div class="row" style="margin-bottom:.75rem"><select style="max-width:260px" value=${action} onChange=${(e) => setAction(e.target.value)}>
      <option value="">كل العمليات</option><option value="auth">الدخول والحسابات</option><option value="user">إدارة المستخدمين</option>
      <option value="grade">الدرجات</option><option value="results">النتائج</option><option value="attendance">الحضور</option>
      <option value="notification">الإشعارات</option><option value="warning">التحذيرات</option><option value="file">الملفات</option></select></div>
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>الوقت</th><th>العملية</th><th>المنفذ</th><th>الهدف</th><th>تفاصيل</th><th>IP</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td class="small">${fmtDate(r.created_at)}</td><td class="mono small">${r.action}</td>
        <td class="small">${r.actor || "النظام"}</td><td class="small mono">${r.target_type || ""} ${r.target_id || ""}</td>
        <td class="small mono" style="max-width:320px;overflow-wrap:anywhere">${JSON.stringify(r.details)}</td><td class="small mono">${r.ip || ""}</td></tr>`)}
      </tbody></table></div></div>` : html`<${Empty} />`}<//></div>`;
}

export function AbuseReportsView() {
  const state = useAsync(() => api.get("/api/message-reports"), []);
  const act = async (id, action) => {
    await api.post(`/api/message-reports/${id}`, { action }).then(() => toast("تم")).catch(toastError);
    state.reload();
  };
  return html`<div><h1>بلاغات الرسائل</h1><${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><ul class="list">
    ${rows.map((r) => html`<li><div class="row between"><strong>${r.sender.full_name} (${ROLE[r.sender.role]})</strong>
      <${Chip} kind=${r.status === "open" ? "warning" : ""}>${r.status === "open" ? "مفتوح" : r.status === "actioned" ? "أُخفيت الرسالة" : "مرفوض"}<//></div>
      <div class="alert info" style="margin:.4rem 0">${r.message.body}</div>
      <div class="small">سبب البلاغ: ${r.reason} — المُبلِّغ: ${r.reporter.full_name} · ${fmtDate(r.created_at)}</div>
      ${r.status === "open" ? html`<div class="row" style="margin-top:.4rem"><button class="small danger" onClick=${() => act(r.id, "hide")}>إخفاء الرسالة</button>
        <button class="small secondary" onClick=${() => act(r.id, "dismiss")}>رفض البلاغ</button></div>` : null}</li>`)}</ul></div>`
    : html`<${Empty}>لا توجد بلاغات<//>`}<//></div>`;
}

// Finds any account in any university by name, email, code or phone (any format: 09…, 218…, +218…).
function AccountFinder() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  const search = async (ev) => {
    ev.preventDefault();
    if (q.trim().length < 3) return;
    const r = await api.get(`/api/users?limit=50&q=${encodeURIComponent(q.trim())}`).catch(toastError);
    if (r) setRows(r.items);
  };
  return html`<div class="card"><h3>البحث عن حساب في كل الجامعات</h3>
    <form class="row" onSubmit=${search}><input style="max-width:320px" placeholder="الاسم أو البريد أو الهاتف أو الرقم"
      value=${q} onInput=${(e) => setQ(e.target.value)} /><button class="secondary">بحث</button></form>
    ${rows ? (rows.length ? html`<div class="table-wrap" style="margin-top:.75rem"><table>
      <thead><tr><th>الاسم</th><th>الدور</th><th>الجامعة</th><th>البريد</th><th>الهاتف</th><th>الحالة</th></tr></thead>
      <tbody>${rows.map((u) => html`<tr><td>${u.full_name}</td><td>${ROLE[u.role] || u.role}</td><td>${u.university || "—"}</td>
        <td class="ltr">${u.email || "—"}</td><td class="ltr">${u.phone || "—"}</td>
        <td>${u.is_active ? "مفعل" : html`<${Chip} kind="danger">موقوف<//>`}</td></tr>`)}</tbody></table></div>`
      : html`<p class="muted" style="margin-top:.75rem">لا يوجد حساب مطابق.</p>`) : null}
  </div>`;
}

export function UniversitiesView() {
  const state = useAsync(() => api.get("/api/universities"), []);
  const [v, bind, setV] = useForm({ code: "", name: "", admin_name: "", admin_email: "" });
  const [temp, setTemp] = useState(null);
  const [submit, busy, error] = useSubmit(async () => {
    const r = await api.post("/api/universities", v);
    setTemp(r.temporary_password);
    setV({ code: "", name: "", admin_name: "", admin_email: "" });
    state.reload();
  });
  const toggle = async (u) => { await api.patch(`/api/universities/${u.id}`, { is_active: !u.is_active }).catch(toastError); state.reload(); };
  return html`<div><h1>الجامعات المشتركة</h1>
    <p class="muted">كل جامعة معزولة ببياناتها بالكامل. زر «إدارة» يفتح الجامعة بصلاحيات إدارتها الكاملة
      (المستخدمون بمن فيهم مدراء الجامعة، الهيكل، الإعدادات، الصلاحيات...) وكل ما تفعله يُسجَّل باسمك في سجل التدقيق.</p>
    <${Async} state=${state}>${(rows) => html`<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>الجامعة</th><th>الرمز</th><th class="num">المستخدمون</th><th>الحالة</th><th></th></tr></thead>
      <tbody>${rows.map((u) => html`<tr><td>${u.name}</td><td class="mono">${u.code}</td><td class="num">${u.users}</td>
        <td>${u.is_active ? html`<${Chip} kind="success">مفعلة<//>` : html`<${Chip} kind="danger">موقوفة<//>`}</td>
        <td><div class="row"><button class="small" onClick=${() => { setActing(u.id); location.hash = "#/"; }}>إدارة</button>
          <button class="small secondary" onClick=${() => toggle(u)}>${u.is_active ? "إيقاف" : "تفعيل"}</button></div></td></tr>`)}</tbody></table></div></div>`}<//>
    <${AccountFinder} />
    <form class="card" onSubmit=${submit}><h3>إضافة جامعة</h3><${ErrorBox} error=${error} /><div class="form-grid">
      <div class="field"><label>اسم الجامعة</label><input ...${bind("name")} required /></div>
      <div class="field"><label>الرمز (حروف لاتينية صغيرة)</label><input class="ltr" ...${bind("code")} required pattern="[a-z0-9-]+" /></div>
      <div class="field"><label>اسم مسؤول الجامعة</label><input ...${bind("admin_name")} required /></div>
      <div class="field"><label>بريد مسؤول الجامعة</label><input type="email" class="ltr" ...${bind("admin_email")} required /></div></div>
      <button disabled=${busy}>إنشاء</button></form>
    ${temp ? html`<${TempPassword} value=${temp} onClose=${() => setTemp(null)} />` : null}</div>`;
}

const PERM_ROLES = ["faculty_admin", "staff", "teacher", "assistant"];

export function PermissionsView() {
  const state = useAsync(() => api.get("/api/permissions"), []);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  if (!state.data) return html`<${Async} state=${state}>${() => null}<//>`;
  const { capabilities, current, editable } = state.data;
  const m = draft || current;
  const has = (k, r) => (m[k] || []).includes(r);
  const flip = (k, r) => setDraft({ ...m, [k]: has(k, r) ? m[k].filter((x) => x !== r) : [...(m[k] || []), r] });
  const save = async () => {
    setBusy(true);
    try {
      await api.put("/api/settings", { settings: { permissions: m } });
      toast("حُفظت الصلاحيات", "success");
      setDraft(null);
      state.reload();
    } catch (e) { toastError(e); } finally { setBusy(false); }
  };
  const groups = [...new Set(capabilities.map((c) => c.group))];
  return html`<div><h1>الصلاحيات</h1>
    <p class="muted">من يملك كل صلاحية في هذه الجامعة. إدارة الجامعة تملك كل الصلاحيات دائماً حتى لا تُقفل الإدارة،
      وتبقى حدود النطاق كما هي (إدارة الكلية لكليتها، الأستاذ لمقرراته). ${editable ? "" : "يعدّلها مشرف المنصة فقط."}</p>
    ${groups.map((g) => html`<div class="card"><h3>${g}</h3><div class="table-wrap"><table>
      <thead><tr><th>الصلاحية</th><th>${ROLE.university_admin}</th>${PERM_ROLES.map((r) => html`<th>${ROLE[r]}</th>`)}</tr></thead>
      <tbody>${capabilities.filter((c) => c.group === g).map((c) => html`<tr><td>${c.label}</td><td>✔</td>
        ${PERM_ROLES.map((r) => html`<td>${c.options.includes(r)
          ? html`<input type="checkbox" checked=${has(c.key, r)} disabled=${!editable} onChange=${() => flip(c.key, r)}
              aria-label=${`${c.label} — ${ROLE[r]}`} />`
          : html`<span class="muted">—</span>`}</td>`)}</tr>`)}</tbody></table></div></div>`)}
    ${editable ? html`<div class="row"><button disabled=${busy || !draft} onClick=${save}>حفظ الصلاحيات</button>
      ${draft ? html`<button class="secondary" onClick=${() => setDraft(null)}>تراجع</button>` : null}
      <button class="secondary" onClick=${() => setDraft(Object.fromEntries(capabilities.map((c) => [c.key, c.default])))}>استعادة الافتراضي</button></div>` : null}
    <${PermissionGroups} capabilities=${capabilities} editable=${editable} />
  </div>`;
}

// Named sets of capabilities for chosen people (e.g. "شؤون الموظفين"), on top of what their role holds.
function PermissionGroups({ capabilities, editable }) {
  const state = useAsync(() => api.get("/api/permission-groups"), []);
  const [edit, setEdit] = useState(null);
  const label = Object.fromEntries(capabilities.map((c) => [c.key, c.label]));
  const remove = async (g) => {
    if (!confirm(`حذف مجموعة «${g.name}»؟ يفقد أعضاؤها صلاحياتها.`)) return;
    await api.del(`/api/permission-groups/${g.id}`).catch(toastError);
    state.reload();
  };
  return html`<div class="card"><div class="row between"><h3>مجموعات الصلاحيات</h3>
      ${editable ? html`<button class="small" onClick=${() => setEdit({ name: "", description: "", capabilities: [], members: [] })}>+ مجموعة</button>` : null}</div>
    <p class="small muted">مجموعة = اسم + صلاحيات تُعطى لأشخاص بعينهم فوق صلاحيات أدوارهم، مثل «شؤون الموظفين» أو «الإعلام الجامعي».
      تعمل الصلاحية لعضو المجموعة إذا كان دوره من الأدوار التي تقبلها (الظاهرة بجانب كل صلاحية).</p>
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="table-wrap"><table>
      <thead><tr><th>المجموعة</th><th>الصلاحيات</th><th>الأعضاء</th><th></th></tr></thead>
      <tbody>${rows.map((g) => html`<tr><td><strong>${g.name}</strong><div class="small muted">${g.description}</div></td>
        <td class="small">${g.capabilities.map((k) => label[k] || k).join("، ") || "—"}</td>
        <td class="small">${g.members.map((m) => m.full_name).join("، ") || "—"}</td>
        <td>${editable ? html`<div class="row"><button class="small secondary" onClick=${() => setEdit(g)}>تعديل</button>
          <button class="small danger" onClick=${() => remove(g)}>حذف</button></div>` : null}</td></tr>`)}</tbody></table></div>`
      : html`<p class="muted">لا توجد مجموعات بعد.</p>`}<//>
    ${edit ? html`<${GroupEditor} group=${edit} capabilities=${capabilities}
      onClose=${() => setEdit(null)} onSaved=${() => { setEdit(null); state.reload(); }} />` : null}
  </div>`;
}

function GroupEditor({ group, capabilities, onClose, onSaved }) {
  const [v, bind] = useForm({ name: group.name, description: group.description || "" });
  const [caps, setCaps] = useState(group.capabilities || []);
  const [members, setMembers] = useState(group.members || []);
  const [q, setQ] = useState("");
  const [found, setFound] = useState([]);
  const search = async () => {
    if (q.trim().length < 2) return;
    const r = await api.get(`/api/users?limit=20&q=${encodeURIComponent(q.trim())}`).catch(toastError);
    if (r) setFound(r.items.filter((u) => PERM_ROLES.includes(u.role) && !members.some((m) => m.id === u.id)));
  };
  const [submit, busy, error] = useSubmit(async () => {
    const body = { name: v.name, description: v.description, capabilities: caps };
    const g = group.id ? await api.patch(`/api/permission-groups/${group.id}`, body)
      : await api.post("/api/permission-groups", body);
    await api.put(`/api/permission-groups/${g.id}/members`, { user_ids: members.map((m) => m.id) });
    toast("حُفظت المجموعة", "success");
    onSaved();
  });
  const groups = [...new Set(capabilities.map((c) => c.group))];
  const flip = (k) => setCaps(caps.includes(k) ? caps.filter((x) => x !== k) : [...caps, k]);
  return html`<${Modal} title=${group.id ? `تعديل «${group.name}»` : "مجموعة صلاحيات جديدة"} onClose=${onClose}>
    <form onSubmit=${submit}><${ErrorBox} error=${error} />
      <div class="form-grid"><div class="field"><label>الاسم</label><input ...${bind("name")} required minlength="2" /></div>
        <div class="field"><label>الوصف</label><input ...${bind("description")} /></div></div>
      <h4>الصلاحيات</h4>
      ${groups.map((gname) => html`<div style="margin-bottom:.5rem"><strong class="small">${gname}</strong>
        ${capabilities.filter((c) => c.group === gname).map((c) => html`<label class="check"><input type="checkbox"
          checked=${caps.includes(c.key)} onChange=${() => flip(c.key)} /> ${c.label}
          <span class="small muted">(${c.options.map((r) => ROLE[r]).join("، ")})</span></label>`)}</div>`)}
      <h4>الأعضاء</h4>
      ${members.length ? html`<ul class="list">${members.map((m) => html`<li class="row between"><span>${m.full_name}
        <span class="small muted">${ROLE[m.role] || m.role}${m.code ? ` · ${m.code}` : ""}</span></span>
        <button type="button" class="small ghost" onClick=${() => setMembers(members.filter((x) => x.id !== m.id))}>إزالة</button></li>`)}</ul>`
        : html`<p class="small muted">لا يوجد أعضاء.</p>`}
      <div class="row"><input style="max-width:260px" placeholder="ابحث عن موظف أو أستاذ" value=${q}
        onInput=${(e) => setQ(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }} />
        <button type="button" class="secondary small" onClick=${search}>بحث</button></div>
      ${found.map((u) => html`<div class="row between small" style="margin-top:.3rem"><span>${u.full_name} — ${ROLE[u.role]}</span>
        <button type="button" class="small secondary" onClick=${() => { setMembers([...members, u]); setFound(found.filter((x) => x.id !== u.id)); }}>إضافة</button></div>`)}
      <div class="row" style="margin-top:1rem"><button disabled=${busy}>حفظ</button>
        <button type="button" class="secondary" onClick=${onClose}>إلغاء</button></div>
    </form><//>`;
}
