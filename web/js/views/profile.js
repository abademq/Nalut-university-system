import { html, useState, useAsync, Async, ErrorBox, useForm, useSubmit, toast, toastError, ROLE, fmtDate } from "../ui.js";
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

// Platform and university administrators have nobody above them to correct their details.
const selfEdit = (u) => u.acting || u.role === "platform_admin" || u.role === "university_admin";

function EditDetails({ user }) {
  const [v, bind] = useForm({ full_name: user.full_name || "", email: user.email || "", phone: user.phone || "", current_password: "" });
  const [submit, busy, error] = useSubmit(async () => {
    await api.patch("/api/me/profile", { full_name: v.full_name.trim(), email: v.email.trim(), phone: v.phone.trim(),
      current_password: v.current_password });
    toast("حُفظت بياناتك");
    setTimeout(() => location.reload(), 900);
  });
  return html`<form class="card" onSubmit=${submit}><h3>تعديل بياناتي</h3><${ErrorBox} error=${error} />
    <div class="field"><label>الاسم</label><input ...${bind("full_name")} required minlength="3" /></div>
    <div class="field"><label>البريد الإلكتروني (للدخول)</label><input type="email" class="ltr" autocomplete="email" ...${bind("email")} /></div>
    <div class="field"><label>رقم الهاتف (للدخول والرسائل)</label><input type="tel" class="ltr" autocomplete="tel" ...${bind("phone")} /></div>
    <div class="field"><label>كلمة المرور الحالية للتأكيد</label><input type="password" autocomplete="current-password" ...${bind("current_password")} required /></div>
    <p class="small muted">يجب أن يبقى البريد أو الهاتف لتسجيل الدخول.${user.acting ? " التعديل على حسابك أنت كمشرف للمنصة، لا على حسابات الجامعة." : ""}</p>
    <button disabled=${busy}>حفظ</button></form>`;
}

export function ProfileView({ user }) {
  return html`<div><h1>حسابي</h1>
    <div class="card"><ul class="list">
      <li><strong>${user.full_name}</strong> — ${ROLE[user.role]}</li>
      ${user.code ? html`<li>الرقم: <span class="mono">${user.code}</span></li>` : null}
      <li>البريد: <span class="ltr">${user.email || "—"}</span> · الهاتف: <span class="ltr">${user.phone || "—"}</span></li>
      ${user.university ? html`<li>${user.university.name}${user.faculty ? ` — ${user.faculty.name}` : ""}</li>` : null}</ul>
      ${selfEdit(user) ? null : html`<p class="small muted">لتعديل البيانات الأساسية تواصل مع إدارة الكلية.</p>`}</div>
    <div class="grid cols-2">${selfEdit(user) ? html`<${EditDetails} user=${user} />` : null}<${ChangePassword} /><${Mfa} user=${user} /><${Sessions} /></div>
  </div>`;
}
