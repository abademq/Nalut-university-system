import { html, useState, useEffect, useForm, useSubmit, ErrorBox } from "../ui.js";
import { api, request } from "../api.js";

const DEMO = [
  ["s.ali@nalut.edu.ly", "طالب"],
  ["t.ahmed@nalut.edu.ly", "أستاذ"],
  ["ta.omar@nalut.edu.ly", "معيد"],
  ["registrar@nalut.edu.ly", "موظف"],
  ["dean.it@nalut.edu.ly", "إدارة الكلية"],
  ["president@nalut.edu.ly", "إدارة الجامعة"],
  ["platform@demo.ly", "مشرف المنصة"],
  ["student@demo2.edu.ly", "طالب بجامعة أخرى"],
];

function svgDataUri(svg) {
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

export function MfaSetup({ token, onDone }) {
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  useEffect(() => {
    request("POST", "/api/auth/mfa/setup", { json: {}, headers }).then(setSetup).catch((e) => setSetup({ error: e }));
  }, []);
  const [submit, busy, error] = useSubmit(async () => {
    const data = await request("POST", "/api/auth/mfa/enable", { json: { code }, headers });
    onDone(data);
  });
  if (!setup) return html`<p class="muted">جارٍ التحضير…</p>`;
  if (setup.error) return html`<${ErrorBox} error=${setup.error} />`;
  return html`<form onSubmit=${submit}>
    <p>امسح الرمز بتطبيق المصادقة (مثل Google Authenticator أو Microsoft Authenticator)، ثم أدخل الرمز المكون من 6 أرقام.</p>
    <img src=${svgDataUri(setup.qr_svg)} alt="رمز إعداد المصادقة الثنائية" style="width:200px;background:#fff;padding:8px;border-radius:12px;display:block;margin:0 auto" />
    <p class="small muted">أو أدخل المفتاح يدوياً: <span class="mono">${setup.secret}</span></p>
    <${ErrorBox} error=${error} />
    <div class="field"><label>رمز التحقق</label>
      <input inputmode="numeric" autocomplete="one-time-code" maxlength="6" value=${code} onInput=${(e) => setCode(e.target.value)} required /></div>
    <button class="big" disabled=${busy}>تفعيل المصادقة الثنائية</button>
  </form>`;
}

function Forgot({ onBack }) {
  const [step, setStep] = useState(1);
  const [v, bind] = useForm({ identifier: "", token: "", new_password: "" });
  const [msg, setMsg] = useState("");
  const [send, busy1, err1] = useSubmit(async () => {
    const r = await api.post("/api/auth/password/forgot", { identifier: v.identifier });
    setMsg(r.message);
    setStep(2);
  });
  const [reset, busy2, err2] = useSubmit(async () => {
    await api.post("/api/auth/password/reset", { token: v.token.trim(), new_password: v.new_password });
    setMsg("تم تغيير كلمة المرور، يمكنك تسجيل الدخول الآن");
    setStep(3);
  });
  return html`<div>
    <h2>استعادة كلمة المرور</h2>
    ${msg ? html`<div class="alert info">${msg}</div>` : null}
    ${step === 1 ? html`<form onSubmit=${send}>
      <${ErrorBox} error=${err1} />
      <div class="field"><label>البريد الإلكتروني أو رقم الهاتف</label><input ...${bind("identifier")} required /></div>
      <button class="big" disabled=${busy1}>إرسال رمز الاستعادة</button></form>` : null}
    ${step === 2 ? html`<form onSubmit=${reset}>
      <${ErrorBox} error=${err2} />
      <div class="field"><label>رمز الاستعادة</label><input class="mono" ...${bind("token")} required /></div>
      <div class="field"><label>كلمة المرور الجديدة (10 أحرف على الأقل، حروف وأرقام)</label>
        <input type="password" autocomplete="new-password" ...${bind("new_password")} required /></div>
      <button class="big" disabled=${busy2}>تعيين كلمة المرور</button></form>` : null}
    <p><button class="ghost" onClick=${onBack}>العودة لتسجيل الدخول</button></p>
  </div>`;
}

export function Login({ onLogin }) {
  const [v, bind, setV] = useForm({ identifier: "", password: "", mfa_code: "" });
  const [stage, setStage] = useState("login"); // login | mfa | setup | forgot
  const [setupToken, setSetupToken] = useState(null);
  const [demo, setDemo] = useState(false);
  useEffect(() => { api.get("/api/health").then((h) => setDemo(!!h.demo)).catch(() => {}); }, []);

  const [submit, busy, error] = useSubmit(async () => {
    const body = { identifier: v.identifier.trim(), password: v.password };
    if (stage === "mfa") body.mfa_code = v.mfa_code;
    const data = await api.post("/api/auth/login", body);
    if (data.mfa_required) return setStage("mfa");
    if (data.mfa_setup_required) {
      setSetupToken(data.setup_token);
      return setStage("setup");
    }
    onLogin(data);
  });

  return html`<div class="auth-wrap"><div class="auth">
    <div class="card">
      <img class="logo" src="/static/icon.svg" alt="" />
      <h1>منصة الجامعة الذكية</h1>
      <p class="muted" style="text-align:center">بوابة موحدة للطلبة وأعضاء هيئة التدريس والإدارة</p>
      ${stage === "forgot" ? html`<${Forgot} onBack=${() => setStage("login")} />` : null}
      ${stage === "setup" ? html`<div><div class="alert warning">حسابك الإداري يتطلب تفعيل المصادقة الثنائية قبل المتابعة.</div>
        <${MfaSetup} token=${setupToken} onDone=${onLogin} /></div>` : null}
      ${stage === "login" || stage === "mfa" ? html`<form onSubmit=${submit}>
        <${ErrorBox} error=${error} />
        ${stage === "login" ? html`
          <div class="field"><label>البريد الإلكتروني أو رقم الهاتف</label>
            <input autocomplete="username" ...${bind("identifier")} required /></div>
          <div class="field"><label>كلمة المرور</label>
            <input type="password" autocomplete="current-password" ...${bind("password")} required /></div>` : html`
          <div class="alert info">أدخل رمز التحقق من تطبيق المصادقة.</div>
          <div class="field"><label>رمز التحقق</label>
            <input inputmode="numeric" autocomplete="one-time-code" maxlength="6" ...${bind("mfa_code")} required /></div>`}
        <button class="big" disabled=${busy}>${busy ? "جارٍ الدخول…" : "تسجيل الدخول"}</button>
        <p class="small" style="text-align:center;margin-top:.75rem">
          <button type="button" class="ghost small" onClick=${() => setStage("forgot")}>نسيت كلمة المرور؟</button></p>
      </form>` : null}
    </div>
    ${demo && stage === "login" ? html`<div class="card">
      <h3>حسابات العرض التجريبي</h3>
      <p class="small muted">كلمة المرور لجميع الحسابات: <span class="mono">Demo@12345</span></p>
      <div class="demo-accounts">${DEMO.map(([email, label]) => html`
        <button type="button" class="secondary" onClick=${() => setV({ ...v, identifier: email, password: "Demo@12345" })}>${label}</button>`)}
      </div></div>` : null}
  </div></div>`;
}
