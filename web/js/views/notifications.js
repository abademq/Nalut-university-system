import {
  html, useState, useAsync, Async, Empty, Chip, StatusChip, ErrorBox, useForm, useSubmit, toast, Tabs,
  CATEGORY, PRIORITY, fmtDate, fmtRelative, useCourses,
} from "../ui.js";
import { api } from "../api.js";

const SENDERS = {
  announcement: ["university_admin", "faculty_admin", "teacher", "assistant"],
  academic_note: ["university_admin", "faculty_admin", "teacher", "assistant"],
  official_warning: ["university_admin", "faculty_admin"],
  admin_notice: ["university_admin", "faculty_admin", "staff"],
};

export function NotificationsView({ user }) {
  const [cat, setCat] = useState("");
  const state = useAsync(() => api.get(`/api/notifications?limit=100${cat ? `&category=${cat}` : ""}`), [cat]);
  const canSend = Object.values(SENDERS).some((r) => r.includes(user.role));
  const open = async (n) => {
    if (!n.read_at) {
      await api.post(`/api/notifications/${n.delivery_id}/read`).catch(() => {});
      window.dispatchEvent(new Event("nus:notifications"));
      state.reload();
    }
    if (n.link) location.hash = n.link.replace(/^#/, "#");
  };
  return html`<div>
    <div class="row between"><h1>الإشعارات</h1><div class="row">
      ${canSend ? html`<a class="btn" href="#/notifications/send">+ إرسال</a>` : null}
      <button class="secondary small" onClick=${async () => { await api.post("/api/notifications/read-all"); window.dispatchEvent(new Event("nus:notifications")); state.reload(); }}>تعليم الكل كمقروء</button></div></div>
    <div class="row" style="margin-bottom:.75rem">${[["", "الكل"], ...Object.entries(CATEGORY)].map(([k, l]) => html`
      <button class=${`small ${cat === k ? "" : "secondary"}`} onClick=${() => setCat(k)}>${l}</button>`)}</div>
    <${Async} state=${state}>${(d) => d.items.length ? html`<div class="card"><ul class="list">${d.items.map((n) => html`
      <li class=${`notif ${n.read_at ? "read" : ""} ${n.priority}`} onClick=${() => open(n)} style="cursor:pointer">
        <span class="dot"></span>
        <div style="flex:1">
          <div class="row between"><strong>${n.title}</strong><span class="small muted">${fmtRelative(n.created_at)}</span></div>
          <div class="small" style="white-space:pre-wrap">${n.body}</div>
          <div class="row small" style="margin-top:.25rem"><${Chip} kind=${n.category === "official_warning" ? "danger" : "primary"}>${CATEGORY[n.category]}<//>
            ${n.priority !== "normal" ? html`<${StatusChip} map=${PRIORITY} value=${n.priority} />` : null}
            ${n.sender ? html`<span class="muted">${n.sender}</span>` : null}</div>
        </div></li>`)}</ul></div>` : html`<${Empty}>لا توجد إشعارات<//>`}<//>
  </div>`;
}

function TargetPicker({ user, v, bind, setV }) {
  const courses = useCourses();
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const [q, setQ] = useState("");
  const people = useAsync(() => (q.length >= 2 ? api.get(`/api/users?q=${encodeURIComponent(q)}&limit=20`).then((r) => r.items) : Promise.resolve([])), [q]);
  const fac = structure.data?.faculties || [];
  const myFac = user.role === "university_admin" ? fac : fac.filter((f) => f.id === user.faculty?.id);
  const types = user.role === "teacher" || user.role === "assistant" ? [["course", "طلبة مقرر"], ["users", "طلبة محددون"]]
    : user.role === "staff" ? [["users", "أشخاص محددون"], ["faculty", "الكلية"]]
      : [["users", "أشخاص محددون"], ["course", "مقرر"], ["department", "قسم"], ["faculty", "كلية"], ["cohort", "دفعة"],
        ...(user.role === "university_admin" ? [["university", "الجامعة كاملة"]] : [])];
  const selected = v.users || [];
  return html`<div>
    <div class="field"><label>المستلمون</label><select ...${bind("target_type")}>${types.map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    ${v.target_type === "course" ? html`<div class="field"><select ...${bind("target_id")} required><option value="">اختر المقرر…</option>
      ${(courses.data || []).map((c) => html`<option value=${c.id}>${c.code} — ${c.title}</option>`)}</select></div>` : null}
    ${v.target_type === "faculty" ? html`<div class="field"><select ...${bind("target_id")} required><option value="">اختر الكلية…</option>
      ${(user.role === "staff" ? fac.filter((f) => f.id === user.faculty?.id) : myFac).map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
    ${v.target_type === "department" ? html`<div class="field"><select ...${bind("target_id")} required><option value="">اختر القسم…</option>
      ${myFac.flatMap((f) => f.departments.map((d) => html`<option value=${d.id}>${f.name} — ${d.name}</option>`))}</select></div>` : null}
    ${v.target_type === "cohort" ? html`<div class="field"><input placeholder="سنة الدفعة مثل 2023" ...${bind("target_id")} required /></div>` : null}
    ${v.target_type === "users" ? html`<div class="field">
      <input placeholder="ابحث بالاسم أو رقم القيد…" value=${q} onInput=${(e) => setQ(e.target.value)} />
      ${(people.data || []).filter((p) => !selected.some((s) => s.id === p.id)).slice(0, 8).map((p) => html`
        <button type="button" class="ghost small" onClick=${() => setV({ ...v, users: [...selected, p] })}>+ ${p.full_name} ${p.code ? `(${p.code})` : ""}</button>`)}
      <div class="row" style="margin-top:.4rem">${selected.map((p) => html`<${Chip} kind="primary">${p.full_name}
        <button type="button" class="ghost small" onClick=${() => setV({ ...v, users: selected.filter((x) => x.id !== p.id) })}>✕</button><//>`)}</div></div>` : null}
    ${["department", "faculty", "cohort", "university", "course"].includes(v.target_type) ? html`<div class="field"><label>الفئة</label>
      <select ...${bind("audience")}><option value="students">الطلبة</option><option value="staff">الموظفون وهيئة التدريس</option><option value="all">الجميع</option></select></div>` : null}
  </div>`;
}

export function SendNotification({ user }) {
  const allowed = Object.entries(SENDERS).filter(([, roles]) => roles.includes(user.role)).map(([k]) => k);
  const [v, bind, setV] = useForm({ category: allowed[0], priority: "normal", title: "", body: "",
    target_type: user.role === "teacher" || user.role === "assistant" ? "course" : "users", target_id: "", users: [],
    audience: "students", push: true, sms: false, schedule: false, scheduled_at: "" });
  const sent = useAsync(() => api.get("/api/notifications/sent"), []);
  const [tab, setTab] = useState("new");
  const [submit, busy, error] = useSubmit(async () => {
    const target_ids = v.target_type === "users" ? v.users.map((u) => u.id)
      : v.target_type === "university" ? [] : v.target_type === "cohort" ? [v.target_id] : [Number(v.target_id)];
    const body = { category: v.category, priority: v.priority, title: v.title, body: v.body, target_type: v.target_type,
      target_ids, audience: v.audience, channels: ["inapp", ...(v.push ? ["push"] : []), ...(v.sms ? ["sms"] : [])] };
    if (body.target_type === "users" && target_ids.length === 1) body.target_type = "user";
    if (v.target_type === "course") body.course_id = Number(v.target_id);
    if (v.schedule && v.scheduled_at) body.scheduled_at = new Date(v.scheduled_at).toISOString();
    const r = await api.post("/api/notifications", body);
    toast(r.status === "scheduled" ? "تمت جدولة الإشعار" : `أُرسل إلى ${r.recipients} مستلم`);
    setV({ ...v, title: "", body: "", users: [] });
    sent.reload();
  });
  return html`<div><h1>إرسال إشعار</h1>
    <${Tabs} value=${tab} onChange=${setTab} tabs=${[["new", "إشعار جديد"], ["sent", "المرسلة"]]} />
    ${tab === "new" ? html`<form class="card" onSubmit=${submit}><${ErrorBox} error=${error} />
      <div class="form-grid">
        <div class="field"><label>النوع</label><select ...${bind("category")}>${allowed.map((k) => html`<option value=${k}>${CATEGORY[k]}</option>`)}</select></div>
        <div class="field"><label>الأولوية</label><select ...${bind("priority")}>${Object.entries(PRIORITY).map(([k, [l]]) => html`<option value=${k}>${l}</option>`)}</select></div>
      </div>
      ${v.category === "official_warning" ? html`<div class="alert warning">التحذير الرسمي إجراء إداري يُسجَّل في سجل التدقيق ويصل للطلبة فقط، ولا يمكن للطالب كتمه.</div>` : null}
      <${TargetPicker} user=${user} v=${v} bind=${bind} setV=${setV} />
      <div class="field"><label>العنوان</label><input ...${bind("title")} required maxlength="200" /></div>
      <div class="field"><label>النص</label><textarea ...${bind("body")} required></textarea></div>
      <div class="row"><label class="check"><input type="checkbox" ...${bind("push", "checkbox")} /> إشعار فوري على الهاتف</label>
        <label class="check"><input type="checkbox" ...${bind("sms", "checkbox")} /> رسالة SMS (للعاجل والتحذيرات عند تفعيلها)</label>
        <label class="check"><input type="checkbox" ...${bind("schedule", "checkbox")} /> جدولة</label></div>
      ${v.schedule ? html`<div class="field" style="max-width:280px"><input type="datetime-local" ...${bind("scheduled_at")} /></div>` : null}
      <button disabled=${busy}>${v.schedule ? "جدولة" : "إرسال"}</button></form>` : null}
    ${tab === "sent" ? html`<div class="card"><${Async} state=${sent}>${(rows) => rows.length ? html`<div class="table-wrap"><table>
      <thead><tr><th>العنوان</th><th>النوع</th><th>الحالة</th><th class="num">المستلمون</th><th class="num">قُرئ</th><th>الوقت</th><th></th></tr></thead>
      <tbody>${rows.map((n) => html`<tr><td>${n.title}</td><td>${CATEGORY[n.category]}</td>
        <td>${n.status === "sent" ? html`<${Chip} kind="success">أُرسل<//>` : n.status === "scheduled" ? html`<${Chip} kind="info">مجدول<//>` : html`<${Chip}>ملغى<//>`}</td>
        <td class="num">${n.recipients}</td><td class="num">${n.read}</td><td class="small">${fmtDate(n.scheduled_at || n.created_at)}</td>
        <td>${n.status === "scheduled" ? html`<button class="small secondary" onClick=${async () => { await api.post(`/api/notifications/${n.id}/cancel`); sent.reload(); }}>إلغاء</button>` : null}</td></tr>`)}
      </tbody></table></div>` : html`<${Empty} />`}<//></div>` : null}
  </div>`;
}
