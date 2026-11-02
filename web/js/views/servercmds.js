import { html, useAsync, Chip, toast } from "../ui.js";
import { api } from "../api.js";

// Every command run on the server, in one place for the platform administrator. Run them over
// SSH on the server (a terminal: ssh user@server), each with sudo.
const SECTIONS = [
  { title: "المنصة: إغلاق وفتح", items: [
    ["sudo nus-close \"المنصة مغلقة للصيانة حتى الساعة 10 مساءً\"", "إغلاق المنصة فوراً: كل الصفحات والتطبيق تعرض الرسالة (اختيارية). يبقى الإغلاق بعد إعادة التشغيل."],
    ["sudo nus-open", "إعادة فتح المنصة."],
  ] },
  { title: "صفحة الدخول", items: [
    ["sudo nus-demo off", "إخفاء الحسابات التجريبية وكلمة مرورها من صفحة الدخول (الحسابات نفسها تبقى؛ غيّر كلمات مرورها أو أوقفها)."],
    ["sudo nus-demo on", "إظهارها مرة أخرى."],
    ["sudo nus-demo", "عرض الحالة الحالية."],
  ] },
  { title: "البيانات", items: [
    ["sudo nus-reset", "مسح كل البيانات والبدء من جديد بعد نسخة احتياطية. يبقى: الجامعة وإعداداتها، مشرف المنصة، الصفات الوظيفية، والكليات والأقسام والفصول والتخصصات. يطلب كتابة «امسح كل شيء» ثم كلمة مرور جديدة لمشرف المنصة."],
    ["sudo nus-reset --all", "مثله، ويمسح الكليات والأقسام والفصول والتخصصات أيضاً."],
    ["sudo nus-delete-accounts", "حذف كل الحسابات عدا مشرف المنصة، مع كل ما يخص أصحابها (التسجيل والدرجات والحضور والرسائل والطلبات والملفات). تبقى المقررات والهيكل والتخصصات والصفات والإعدادات. نسخة احتياطية أولاً، ويطلب كتابة «امسح كل شيء»."],
    ["ls -lh /var/lib/nus/backups/", "النسخ الاحتياطية: يومياً الساعة 03:30 وتُحفظ 14 يوماً، وقبل كل مسح (before-reset)."],
    ["sudo systemctl stop nus && sudo cp /var/lib/nus/backups/nus-YYYY-MM-DD.db /var/lib/nus/nus.db && sudo chown nus: /var/lib/nus/nus.db && sudo systemctl start nus",
     "استرجاع قاعدة البيانات من نسخة احتياطية (غيّر التاريخ لاسم الملف). الملفات المرفوعة في files-*.tgz بجانبها."],
  ] },
  { title: "الرسائل النصية", items: [
    ["sudo nus-sms-check", "فحص إعدادات Resala في ملف الأسرار."],
    ["sudo nus-sms-check 0912345678", "فحصها وإرسال رمز تحقق تجريبي واحد للرقم."],
  ] },
  { title: "الخدمة والتحديث", items: [
    ["sudo systemctl restart nus", "إعادة تشغيل المنصة؛ لازمة بعد أي تعديل في /etc/nus/nus.env."],
    ["sudo systemctl status nus", "حالة الخدمة (تعمل أم لا)."],
    ["sudo journalctl -u nus -f", "سجل المنصة مباشرة (Ctrl+C للخروج) لمعرفة سبب أي خطأ."],
    ["sudo journalctl -u nus --since \"1 hour ago\"", "سجل الساعة الأخيرة."],
    ["cat /opt/nus/VERSION", "النسخة المنشورة على الخادم."],
    ["sudo certbot --nginx -d nalut.abade.ly --redirect", "تفعيل HTTPS على الخادم نفسه (إن لم يكن عبر Cloudflare)."],
  ], note: "التحديث صار تلقائياً: كل دفعة للفرع الرئيسي في GitHub تُختبر، وإن نجحت يتحدث الخادم وحده. زر «Run workflow» في Actions ← deploy للتحديث اليدوي." },
  { title: "ملف الأسرار /etc/nus/nus.env", items: [
    ["sudo nano /etc/nus/nus.env", "فتح الملف للتعديل (Ctrl+O للحفظ، Ctrl+X للخروج)، ثم: sudo systemctl restart nus"],
  ], keys: [
    ["ANTHROPIC_API_KEY", "مفتاح Claude لميزات الذكاء الاصطناعي."], ["AI_MODEL", "النموذج (الافتراضي claude-opus-5-5)."],
    ["SMS_PROVIDER=resala", "مزود الرسائل النصية."], ["RESALA_API_KEY", "مفتاح Resala."],
    ["RESALA_SERVICE_NAME", "الاسم في رسالة رمز التحقق (الافتراضي: جامعة نالوت)."], ["RESALA_SENDER", "اسم المرسل المعتمد عند Resala."],
    ["RESALA_TEST=true", "وضع التجربة: Resala تقبل الطلب دون إرسال أو خصم."],
    ["RESALA_SMS_TEMPLATE_ID", "القالب الواحد القديم؛ القوالب حسب النوع تُدخل من إعدادات المؤسسة."],
    ["FCM_CREDENTIALS_FILE", "ملف Firebase للإشعارات الفورية (الافتراضي /etc/nus/firebase.json)."],
    ["SECRET_KEY / DATA_ENCRYPTION_KEY", "مفاتيح التشفير: لا تغيّرها ولا تشاركها أبداً."],
  ] },
];

function Command({ cmd, text }) {
  const copy = () => navigator.clipboard?.writeText(cmd).then(() => toast("نُسخ الأمر"), () => {});
  return html`<li style="margin-bottom:.6rem"><div class="row" style="gap:.4rem;align-items:flex-start">
      <code class="ltr" style="font-family:inherit;flex:1;white-space:pre-wrap;word-break:break-all;background:var(--surface-2, rgba(127,127,127,.12));padding:.35rem .5rem;border-radius:6px">${cmd}</code>
      <button class="ghost small" onClick=${copy} title="نسخ">نسخ</button></div>
    <div class="small muted" style="margin-top:.2rem">${text}</div></li>`;
}

export function ServerCommandsView() {
  const health = useAsync(() => api.get("/api/health"), []);
  const h = health.data;
  return html`<div><h1>أوامر الخادم</h1>
    <p class="muted">تُكتب في الخادم عبر SSH. كل أمر يحتاج sudo. لا تشارك محتوى ملف الأسرار مع أحد.</p>
    ${h ? html`<div class="card row" style="flex-wrap:wrap;gap:.5rem">
      <${Chip} kind=${h.closed ? "danger" : "success"}>${h.closed ? "المنصة مغلقة" : "المنصة مفتوحة"}<//>
      <${Chip} kind=${h.demo ? "warning" : "success"}>${h.demo ? "الحسابات التجريبية ظاهرة في صفحة الدخول" : "الحسابات التجريبية مخفية"}<//>
      <${Chip}>النسخة: <span class="mono">${h.version}</span><//></div>` : null}
    ${SECTIONS.map((s) => html`<div class="card"><h3>${s.title}</h3><ul class="list" style="list-style:none;padding:0">
      ${s.items.map(([cmd, text]) => html`<${Command} cmd=${cmd} text=${text} />`)}</ul>
      ${s.keys ? html`<div class="table-wrap"><table><tbody>${s.keys.map(([k, t]) => html`<tr><td class="mono ltr small">${k}</td><td class="small">${t}</td></tr>`)}</tbody></table></div>` : null}
      ${s.note ? html`<p class="small muted">${s.note}</p>` : null}</div>`)}
  </div>`;
}
