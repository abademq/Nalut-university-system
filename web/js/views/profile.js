import { html, useState, useAsync, Async, ErrorBox, useForm, useSubmit, toast, toastError, ROLE, CATEGORY, fmtDate } from "../ui.js";
import { api } from "../api.js";
import { MfaSetup } from "./login.js";

function ChangePassword() {
  const [v, bind, setV] = useForm({ current_password: "", new_password: "", confirm: "" });
  const [submit, busy, error] = useSubmit(async () => {
    if (v.new_password !== v.confirm) throw new Error("كلمتا المرور غير متطابقتين");
    await api.post("/api/auth/password/change", { current_password: v.current_password, new_password: v.new_password });
    setV({ current_password: "", new_password: "", confirm: "" });
    toast("تم تغيير كلمة المرور. سجّل الدخول مجدداً على أجهزتك الأخرى.");
    setTimeout(() => location.reload(), 1200);
  });
  return html`<form class="card" onSubmit=${submit}><h3>تغيير كلمة المرور</h3><${ErrorBox} error=${error} />
    <div class="field"><label>كلمة المرور الحالية</label><input type="password" autocomplete="current-password" ...${bind("current_password")} required /></div>
    <div class="field"><label>كلمة المرور الجديدة (10 أحرف على الأقل، حروف وأرقام)</label><input type="password" autocomplete="new-password" ...${bind("new_password")} required /></div>
    <div class="field"><label>تأكيد كلمة المرور</label><input type="password" autocomplete="new-password" ...${bind("confirm")} required /></div>
    <button disabled=${busy}>تغيير</button></form>`;
}

function Mfa({ user }) {
  const [setup, setSetup] = useState(false);
  const [enabled, setEnabled] = useState(user.mfa_enabled);
  const sms = user.mfa_method === "sms";
  const disable = async () => {
    const password = prompt("كلمة المرور الحالية:");
    if (!password) return;
    if (sms && !(await api.post("/api/auth/mfa/sms/start").catch(toastError))) return;
    const code = prompt(sms ? "الرمز المرسل برسالة نصية:" : "رمز التحقق من التطبيق:");
    if (!code) return;
    await api.post("/api/auth/mfa/disable", { password, code }).then(() => { setEnabled(false); toast("تم إيقاف المصادقة الثنائية"); }).catch(toastError);
  };
  return html`<div class="card"><h3>المصادقة الثنائية</h3>
    ${enabled ? html`<p>✅ مفعلة على حسابك ${sms ? "برسالة نصية" : "بتطبيق المصادقة"}.</p>${!user.mfa_required ? html`<button class="secondary" onClick=${disable}>إيقاف</button>` : html`<p class="small muted">إلزامية لحسابك. لتغيير الطريقة اطلب من الإدارة إعادة تعيينها.</p>`}`
      : setup ? html`<${MfaSetup} onDone=${() => { setEnabled(true); setSetup(false); toast("تم تفعيل المصادقة الثنائية"); }} />`
        : html`<p class="muted">أضف طبقة حماية: رمز برسالة نصية أو من تطبيق المصادقة عند تسجيل الدخول.</p><button onClick=${() => setSetup(true)}>تفعيل</button>`}</div>`;
}

// Sends a test push to the user's own phones, one per tone, and says what happened.
function PushTest() {
  const [busy, setBusy] = useState(null);
  const test = async (priority) => {
    setBusy(priority);
    const r = await api.post("/api/notifications/test-push", { priority }).catch(toastError);
    setBusy(null);
    if (!r) return;
    if (r.provider === "logpush") toast("الإشعارات الفورية غير مفعلة على الخادم (ملف Firebase غير موجود)", "error");
    else if (!r.devices) toast("لا يوجد هاتف مسجل لحسابك. سجّل الدخول من تطبيق الهاتف واسمح بالإشعارات", "error");
    else if (!r.sent) toast("فشل الإرسال إلى هاتفك، أعد تسجيل الدخول من التطبيق", "error");
    else toast(`أُرسل إلى ${r.sent} من ${r.devices} جهاز`, "success");
  };
  return html`<div class="card"><h3>تجربة الإشعارات على هاتفي</h3>
    <p class="small muted">لكل نوع نغمة مختلفة في تطبيق الهاتف، ويمكن تغييرها من «الإشعارات والنغمات» في التطبيق.</p>
    <div class="row">
      <button class="secondary small" disabled=${!!busy} onClick=${() => test("normal")}>عادي</button>
      <button class="secondary small" disabled=${!!busy} onClick=${() => test("important")}>مهم</button>
      <button class="secondary small" disabled=${!!busy} onClick=${() => test("urgent")}>عاجل</button>
    </div></div>`;
}

function Prefs({ user }) {
  const p = user.notification_prefs || {};
  const [v, bind] = useForm({ push: p.push !== false, sms: p.sms !== false });
  const [muted, setMuted] = useState(p.muted_categories || []);
  const [submit, busy, error] = useSubmit(async () => {
    await api.put("/api/me/notification-prefs", { push: v.push, sms: v.sms, muted_categories: muted });
    toast("تم حفظ التفضيلات");
  });
  const toggle = (k) => setMuted(muted.includes(k) ? muted.filter((x) => x !== k) : [...muted, k]);
  return html`<form class="card" onSubmit=${submit}><h3>تفضيلات الإشعارات</h3><${ErrorBox} error=${error} />
    <label class="check"><input type="checkbox" ...${bind("push", "checkbox")} /> إشعارات فورية على الهاتف</label>
    <label class="check"><input type="checkbox" ...${bind("sms", "checkbox")} /> رسائل SMS</label>
    <p class="small muted">كتم التنبيهات الفورية لـ (تبقى في صندوق الإشعارات):</p>
    ${["announcement", "academic_note", "admin_notice"].map((k) => html`<label class="check"><input type="checkbox" checked=${muted.includes(k)} onChange=${() => toggle(k)} /> ${CATEGORY[k]}</label>`)}
    <p class="small muted">التحذيرات الرسمية والإشعارات العاجلة تصل دائماً.</p>
    <button disabled=${busy}>حفظ</button></form>`;
}

function Sessions() {
  const state = useAsync(() => api.get("/api/me/sessions"), []);
  const revoke = async () => {
    if (!confirm("تسجيل الخروج من جميع الأجهزة؟")) return;
    await api.post("/api/me/sessions/revoke-all");
    location.reload();
  };
  return html`<div class="card"><h3>الجلسات النشطة</h3><${Async} state=${state}>${(rows) => html`<ul class="list">${rows.map((s) => html`<li class="small">
    ${fmtDate(s.created_at)} · <span class="mono">${s.ip || ""}</span><div class="muted">${(s.user_agent || "").slice(0, 90)}</div></li>`)}</ul>`}<//>
    <button class="secondary" onClick=${revoke}>تسجيل الخروج من كل الأجهزة</button></div>`;
}

export function ProfileView({ user }) {
  return html`<div><h1>حسابي</h1>
    <div class="card"><ul class="list">
      <li><strong>${user.full_name}</strong> — ${ROLE[user.role]}</li>
      ${user.code ? html`<li>الرقم: <span class="mono">${user.code}</span></li>` : null}
      <li>البريد: <span class="ltr">${user.email || "—"}</span> · الهاتف: <span class="ltr">${user.phone || "—"}</span></li>
      ${user.university ? html`<li>${user.university.name}${user.faculty ? ` — ${user.faculty.name}` : ""}</li>` : null}</ul>
      <p class="small muted">لتعديل البيانات الأساسية تواصل مع إدارة الكلية.</p></div>
    <div class="grid cols-2"><${ChangePassword} /><${Mfa} user=${user} /><${Prefs} user=${user} /><${PushTest} /><${Sessions} /></div>
  </div>`;
}
