import { html, render, useState, useEffect, useCallback, useRef } from "../vendor/preact-htm.mjs";
import { api } from "./api.js";

export { html, render, useState, useEffect, useCallback, useRef };

// ---------------------------------------------------------------- labels

export const ROLE = {
  platform_admin: "مشرف المنصة", university_admin: "إدارة الجامعة", faculty_admin: "إدارة الكلية",
  staff: "موظف إداري", teacher: "عضو هيئة تدريس", assistant: "معيد", student: "طالب",
};
export const ASSIGNMENT_STATUS = {
  not_started: ["لم يبدأ", ""], in_progress: ["قيد العمل", "info"], submitted: ["تم التسليم", "primary"],
  late: ["متأخر", "danger"], reviewed: ["تمت المراجعة", "success"],
};
export const KIND = { homework: "واجب", research: "بحث", project: "مشروع", quiz: "اختبار", activity: "نشاط" };
export const ATT_STATUS = {
  present: ["حاضر", "success"], late: ["متأخر", "warning"], absent: ["غائب", "danger"], excused: ["بعذر", "info"],
  pending_review: ["قيد المراجعة", "warning"], rejected: ["مرفوض", "danger"],
};
export const CATEGORY = {
  announcement: "إعلان", academic_note: "ملاحظة أكاديمية", official_warning: "تحذير رسمي",
  admin_notice: "إشعار إداري", system: "تنبيه النظام",
};
export const PRIORITY = { normal: ["عادي", ""], important: ["مهم", "warning"], urgent: ["عاجل", "danger"] };
export const RESULT_STATUS = {
  draft: ["مسودة", ""], submitted: ["بانتظار الاعتماد", "warning"], approved: ["معتمدة", "info"],
  published: ["منشورة", "success"],
};
export const RISK_FLAG = {
  outside_geofence: "خارج نطاق القاعة", shared_device: "جهاز مشترك مع حساب آخر",
  device_used_by_other_account: "جهاز استُخدم لحساب آخر مؤخراً", new_device: "جهاز جديد",
  no_device_id: "بدون معرف جهاز", face_no_match: "عدم تطابق الوجه", face_liveness_failed: "فشل فحص الحيوية",
  early_leave: "انصراف مبكر",
};
export const DAYS = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"];

// ---------------------------------------------------------------- formatting

const LOCALE = "ar-LY-u-nu-latn";
export function fmtDate(v, withTime = true) {
  if (!v) return "—";
  const d = new Date(v);
  return d.toLocaleString(LOCALE, withTime
    ? { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "numeric" });
}
// Arabic counting: ساعة، ساعتين، 3 ساعات، 11 ساعة.
const count = (n, one, two, few) => (n === 1 ? one : n === 2 ? two : n <= 10 ? `${n} ${few}` : `${n} ${one}`);

/** "منذ 5 دقائق" / "خلال يومين", by the server's clock. past: it already happened (never "خلال"). */
export function fmtRelative(v, past = false) {
  if (!v) return "";
  let diff = (new Date(v) - (Date.now() + (window.__nusClockSkew || 0))) / 1000;
  if (past && diff > 0) diff = 0;
  const abs = Math.abs(diff);
  if (abs < 60) return "الآن";
  const amount = abs < 3600 ? count(Math.floor(abs / 60), "دقيقة", "دقيقتين", "دقائق")
    : abs < 86400 ? count(Math.floor(abs / 3600), "ساعة", "ساعتين", "ساعات")
      : count(Math.floor(abs / 86400), "يوم", "يومين", "أيام");
  return diff > 0 ? `خلال ${amount}` : `منذ ${amount}`;
}
export function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}
export const pct = (v) => (v === null || v === undefined ? "—" : `${v}%`);
export function toLocalInput(d) {
  const x = new Date(d);
  const p = (n) => String(n).padStart(2, "0");
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}T${p(x.getHours())}:${p(x.getMinutes())}`;
}

// ---------------------------------------------------------------- hooks

export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    return fn().then((data) => setState({ loading: false, data, error: null }))
      .catch((error) => setState({ loading: false, data: null, error }));
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}

// ---------------------------------------------------------------- toast

let toastHost = null;
export function toast(message, kind = "") {
  if (!toastHost) {
    toastHost = document.createElement("div");
    toastHost.className = "toast-wrap";
    document.body.appendChild(toastHost);
  }
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  toastHost.appendChild(el);
  setTimeout(() => el.remove(), 3800);
}
export const toastError = (e) => toast(e?.message || "حدث خطأ", "error");

// ---------------------------------------------------------------- components

import { ICONS } from "./icons.js";
// one icon family everywhere; decorative, so hidden from screen readers
export const Icon = ({ name, size = 20 }) => html`<svg class="icon" width=${size} height=${size} viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
  dangerouslySetInnerHTML=${{ __html: ICONS[name] || "" }} />`;

export const Chip = ({ kind = "", children }) => html`<span class="chip ${kind}">${children}</span>`;
export const StatusChip = ({ map, value }) => {
  const [label, kind] = map[value] || [value, ""];
  return html`<${Chip} kind=${kind}>${label}<//>`;
};
export const Loading = () => html`<div class="empty">جارٍ التحميل…</div>`;
export const Empty = ({ children }) => html`<div class="empty">${children || "لا توجد بيانات"}</div>`;
export const ErrorBox = ({ error }) => error ? html`<div class="alert error">${error.message || String(error)}</div>` : null;

export function Async({ state, children }) {
  if (state.loading && !state.data) return html`<${Loading} />`;
  if (state.error) return html`<${ErrorBox} error=${state.error} />`;
  return children(state.data);
}

export const Kpi = ({ label, value, hint }) => html`
  <div class="kpi"><div class="label">${label}</div><div class="value">${value ?? "—"}</div>
  ${hint ? html`<div class="hint">${hint}</div>` : null}</div>`;

export function Bar({ value, warnBelow, badBelow, warnAbove, badAbove }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  let cls = "";
  if ((badBelow !== undefined && v < badBelow) || (badAbove !== undefined && v >= badAbove)) cls = "bad";
  else if ((warnBelow !== undefined && v < warnBelow) || (warnAbove !== undefined && v >= warnAbove)) cls = "warn";
  return html`<div class="bar ${cls}"><span style=${`width:${v}%`}></span></div>`;
}

export function Tabs({ tabs, value, onChange }) {
  return html`<div class="tabs" role="tablist">${tabs.map(([key, label]) => html`
    <button role="tab" aria-selected=${value === key} class=${value === key ? "active" : ""}
      onClick=${() => onChange(key)}>${label}</button>`)}</div>`;
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return html`<div class="modal-back" onClick=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="modal" role="dialog" aria-modal="true">
      <div class="card-head"><h2>${title}</h2><button class="ghost" onClick=${onClose} aria-label="إغلاق">✕</button></div>
      ${children}
    </div></div>`;
}

// Generic controlled form state.
export function useForm(initial) {
  const [values, setValues] = useState(initial);
  const bind = (name, type = "text") => type === "checkbox"
    ? { checked: !!values[name], onChange: (e) => setValues((v) => ({ ...v, [name]: e.target.checked })) }
    : { value: values[name] ?? "", onInput: (e) => setValues((v) => ({ ...v, [name]: e.target.value })) };
  return [values, bind, setValues];
}

export function useSubmit(fn) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async (...args) => {
    args[0]?.preventDefault?.();
    setBusy(true);
    setError(null);
    try {
      return await fn(...args);
    } catch (err) {
      setError(err);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return [submit, busy, error];
}

// Course picker that loads the caller's visible courses.
export function useCourses() {
  return useAsync(() => api.get("/api/courses"), []);
}

export function navigate(hash) { location.hash = hash; }

// ------------------------------------------------------------------ appearance (light / dark / automatic)

export const THEMES = { auto: "تلقائي حسب الجهاز", light: "فاتح", dark: "داكن" };
export function getTheme() {
  try { return localStorage.getItem("nus-theme") || "auto"; } catch { return "auto"; }
}
export function setTheme(t) {
  try { if (t === "auto") localStorage.removeItem("nus-theme"); else localStorage.setItem("nus-theme", t); } catch { /* private mode */ }
  applyTheme();
}
export function applyTheme() {
  const t = getTheme();
  if (t === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}
applyTheme();

// A national id shown masked (last four digits); "إظهار" asks the server for the full number,
// which records the request in the audit log.
export function NationalId({ value, url }) {
  const [full, setFull] = useState(null);
  if (!value) return html`<span class="muted">—</span>`;
  const reveal = () => api.get(url).then((r) => setFull(r.national_id)).catch(toastError);
  return html`<span class="row" style="gap:.5rem;display:inline-flex;align-items:center">
    <span class="mono ltr">${full || value}</span>
    ${full ? html`<button type="button" class="ghost small" onClick=${() => setFull(null)}>إخفاء</button>`
      : html`<button type="button" class="ghost small" onClick=${reveal} title="يُسجَّل الإظهار في سجل التدقيق">إظهار</button>`}</span>`;
}
