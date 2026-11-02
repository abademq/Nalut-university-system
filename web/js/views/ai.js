import { html, useState, useEffect, Chip, ErrorBox, toast, toastError, fmtDate, Icon } from "../ui.js";
import { api } from "../api.js";

// What this account may use; asked once per page load.
let statusPromise = null;
export function useAi() {
  const [s, setS] = useState(null);
  useEffect(() => {
    statusPromise = statusPromise || api.get("/api/ai/status").catch(() => ({ available: false }));
    statusPromise.then(setS);
  }, []);
  return s;
}
export const resetAi = () => { statusPromise = null; };

const Note = () => html`<p class="small muted"><${Icon} name="shield" size=${14} /> تحليل آلي بالذكاء الاصطناعي (Claude) للتوجيه فقط، وليس قراراً.
  تُرسل الأرقام دون أسماء أو أرقام قيد.</p>`;
const When = ({ r }) => html`<span class="small muted">${r.cached ? "تحليل محفوظ" : "تحليل جديد"} · ${fmtDate(r.generated_at)}</span>`;

function useRun(fn) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const run = async (...args) => {
    setBusy(true); setError(null);
    try { setData(await fn(...args)); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return [run, busy, error, data, setData];
}

// ------------------------------------------------------------------ 1-2 student advisor and outlook

const OUTLOOK = { good: ["جيد", "success"], watch: ["يحتاج متابعة", "warning"], at_risk: ["في خطر", "danger"], unknown: ["بيانات غير كافية", ""] };

export function StudentAdvisor() {
  const ai = useAi();
  const [consent, setConsent] = useState(null);
  const [run, busy, error, r] = useRun((fresh) => api.post(`/api/ai/me/analysis${fresh ? "?fresh=true" : ""}`));
  useEffect(() => { if (ai) setConsent(ai.consent); }, [ai]);
  if (!ai?.students) return null;
  if (!consent) return html`<div class="card"><h3>المرشد الدراسي الذكي</h3>
    <p>يحلل الذكاء الاصطناعي نتائجك وحضورك ومهامك وخطتك، ويقترح ما تركز عليه، ويتوقع وضعك في مقررات هذا الفصل، ويضع لك خطة مذاكرة أسبوعية.</p>
    <p class="small muted">تُرسل لخدمة Claude من Anthropic أرقامك الدراسية وأسماء المقررات فقط، دون اسمك أو رقم قيدك أو بريدك. تستطيع سحب الموافقة متى شئت.</p>
    <button onClick=${() => api.post("/api/ai/me/consent").then(() => { setConsent(true); resetAi(); }).catch(toastError)}>أوافق، وأريد التحليل</button></div>`;
  return html`<div class="card"><div class="row between"><h3>المرشد الدراسي الذكي</h3>
      <div class="row">${r ? html`<${When} r=${r} />` : null}
        <button class="small" disabled=${busy} onClick=${() => run(!!r)}>${busy ? "جارٍ التحليل…" : r ? "تحديث التحليل" : "حلّل مستواي"}</button></div></div>
    <${ErrorBox} error=${error} />
    ${r ? html`<div class="stack">
      <p>${r.summary}</p>
      ${r.strengths.length ? html`<div><strong>نقاط قوتك</strong><ul>${r.strengths.map((x) => html`<li>${x}</li>`)}</ul></div>` : null}
      ${r.focus.length ? html`<div><strong>ركّز على</strong><ul class="list">${r.focus.map((f) => html`<li><strong>${f.course}</strong>: ${f.why}
        <div class="small">الخطوة: ${f.action}</div></li>`)}</ul></div>` : null}
      ${r.outlook.length ? html`<div><strong>توقع هذا الفصل</strong> <span class="small muted">(تقدير من الحضور والمهام، وليس نتيجة)</span>
        <div class="table-wrap"><table><tbody>${r.outlook.map((o) => html`<tr><td class="mono">${o.course_code}</td>
          <td><${Chip} kind=${OUTLOOK[o.outlook]?.[1]}>${OUTLOOK[o.outlook]?.[0] || o.outlook}<//></td><td class="small">${o.reason}</td></tr>`)}</tbody></table></div></div>` : null}
      ${r.weekly_plan.length ? html`<div><strong>خطة مذاكرة أسبوعية</strong><ul class="list">${r.weekly_plan.map((d) => html`<li><strong>${d.day}</strong>: ${d.plan}</li>`)}</ul></div>` : null}
      ${r.tip ? html`<div class="alert info">${r.tip}</div>` : null}</div>` : null}
    <${Note} />
    <button class="ghost small" onClick=${() => api.del("/api/ai/me/consent").then(() => { setConsent(false); resetAi(); toast("سُحبت الموافقة"); }).catch(toastError)}>سحب الموافقة</button>
  </div>`;
}

// ------------------------------------------------------------------ 3 assistant

export function AssistantView() {
  const ai = useAi();
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [run, busy, error] = useRun(async (question) => {
    const r = await api.post("/api/ai/ask", { question });
    setItems((x) => [...x, { q: question, a: r.answer }]);
    setQ("");
  });
  if (ai && !ai.assistant) return html`<div><h1>المساعد الذكي</h1><div class="alert info">المساعد غير مفعّل حالياً.</div></div>`;
  return html`<div><h1>المساعد الذكي</h1>
    <p class="muted">اسأل عن استخدام المنصة ولوائح الحضور والدرجات والتسجيل والطلبات. يجيب من دليل المنصة وإعدادات المؤسسة.</p>
    ${items.map((x) => html`<div class="card"><div class="small muted">سؤالك: ${x.q}</div><div style="white-space:pre-line;margin-top:.4rem">${x.a}</div></div>`)}
    <form class="card" onSubmit=${(e) => { e.preventDefault(); if (q.trim().length >= 3) run(q.trim()); }}>
      <${ErrorBox} error=${error} />
      <div class="field"><textarea value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="مثلاً: كم مرة أقدر نغيب في المقرر؟ كيف نطلب إفادة قيد؟" maxlength="600"></textarea></div>
      <div class="row">${["كم نسبة الغياب المسموحة؟", "كيف أطلب عذر غياب؟", "متى تظهر نتيجتي؟"].map((s) => html`<button type="button" class="ghost small" onClick=${() => run(s)}>${s}</button>`)}
        <span class="spacer"></span><button disabled=${busy}>${busy ? "…" : "اسأل"}</button></div></form>
    <p class="small muted">إجابات آلية قد تخطئ؛ القرار والتفاصيل الرسمية عند شؤون الطلبة وإدارة الكلية.</p></div>`;
}

// ------------------------------------------------------------------ 4 draft review (students)

export function DraftReview({ assignmentId }) {
  const ai = useAi();
  const [text, setText] = useState("");
  const [run, busy, error, r] = useRun(() => api.post(`/api/ai/assignments/${assignmentId}/review-draft`, { text }));
  if (!ai?.students) return null;
  if (!ai.consent) return html`<div class="card small muted">لمراجعة مسودتك بالذكاء الاصطناعي، فعّل «المرشد الدراسي الذكي» من صفحة «نتيجتي والمعدل».</div>`;
  return html`<details class="card"><summary><strong>راجع مسودتي قبل التسليم</strong> <span class="small muted">(لا يكتب الحل عنك)</span></summary>
    <${ErrorBox} error=${error} />
    <div class="field"><textarea value=${text} onInput=${(e) => setText(e.target.value)} placeholder="الصق نص مسودتك هنا (30 حرفاً على الأقل)" rows="8"></textarea></div>
    <button class="secondary small" disabled=${busy || text.trim().length < 30} onClick=${() => run()}>${busy ? "جارٍ المراجعة…" : "راجع"}</button>
    ${r ? html`<div class="stack" style="margin-top:.6rem"><p>${r.overall}</p>
      ${r.strengths.length ? html`<div><strong>جيد</strong><ul>${r.strengths.map((x) => html`<li>${x}</li>`)}</ul></div>` : null}
      ${r.improvements.length ? html`<div><strong>حسّن</strong><ul>${r.improvements.map((x) => html`<li>${x}</li>`)}</ul></div>` : null}
      ${r.checklist.length ? html`<div><strong>قبل التسليم</strong><ul>${r.checklist.map((x) => html`<li>${x}</li>`)}</ul></div>` : null}</div>` : null}
  </details>`;
}

// ------------------------------------------------------------------ 5 + 7 teacher: course summary and questions

export function CourseAi({ course }) {
  const ai = useAi();
  const [run, busy, error, r] = useRun((fresh) => api.post(`/api/ai/courses/${course.id}/summary${fresh ? "?fresh=true" : ""}`));
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(5);
  const [kind, setKind] = useState("mixed");
  const [level, setLevel] = useState("medium");
  const [ask, busyQ, errorQ, qs] = useRun(() => api.post(`/api/ai/courses/${course.id}/questions`, { topic, count: Number(count), kind, level }));
  if (!ai?.staff) return html`<div class="alert info">ميزات الذكاء الاصطناعي غير مفعّلة.</div>`;
  return html`<div class="grid cols-2">
    <div class="card"><div class="row between"><h3>ملخص المقرر</h3>
        <div class="row">${r ? html`<${When} r=${r} />` : null}<button class="small" disabled=${busy} onClick=${() => run(!!r)}>${busy ? "…" : r ? "تحديث" : "حلّل المقرر"}</button></div></div>
      <${ErrorBox} error=${error} />
      ${r ? html`<div class="stack"><p>${r.overview}</p>
        ${r.at_risk.length ? html`<div><strong>طلبة يحتاجون متابعة</strong><ul class="list">${r.at_risk.map((s) => html`<li>
          ${s.student_id ? html`<a href=${`#/students/${s.student_id}`}>${s.full_name}</a>` : s.full_name}: ${s.reason}
          <div class="small">اقتراح: ${s.suggestion}</div></li>`)}</ul></div>` : null}
        ${r.difficult_parts.length ? html`<div><strong>الأصعب على الطلبة</strong><ul>${r.difficult_parts.map((x) => html`<li>${x}</li>`)}</ul></div>` : null}
        ${r.suggestions.length ? html`<div><strong>اقتراحات تدريسية</strong><ul>${r.suggestions.map((x) => html`<li>${x}</li>`)}</ul></div>` : null}</div>` : null}
      <${Note} /></div>
    <div class="card"><h3>أسئلة مراجعة</h3><${ErrorBox} error=${errorQ} />
      <div class="field"><label>الموضوع</label><input value=${topic} onInput=${(e) => setTopic(e.target.value)} placeholder="مثلاً: الحلقات التكرارية والمصفوفات" /></div>
      <div class="form-grid">
        <div class="field"><label>العدد</label><input type="number" min="1" max="15" value=${count} onInput=${(e) => setCount(e.target.value)} /></div>
        <div class="field"><label>النوع</label><select value=${kind} onChange=${(e) => setKind(e.target.value)}>
          <option value="mixed">متنوع</option><option value="mcq">اختيار من متعدد</option><option value="short">إجابة قصيرة</option></select></div>
        <div class="field"><label>المستوى</label><select value=${level} onChange=${(e) => setLevel(e.target.value)}>
          <option value="easy">سهل</option><option value="medium">متوسط</option><option value="hard">صعب</option></select></div></div>
      <button class="secondary small" disabled=${busyQ || topic.trim().length < 3} onClick=${() => ask()}>${busyQ ? "جارٍ الإعداد…" : "أنشئ الأسئلة"}</button>
      ${qs ? html`<ol style="margin-top:.6rem">${qs.questions.map((q) => html`<li style="margin-bottom:.6rem"><div>${q.question}</div>
        ${q.choices.length ? html`<ul class="small">${q.choices.map((c) => html`<li>${c}</li>`)}</ul>` : null}
        <details class="small"><summary>الإجابة</summary><strong>${q.answer}</strong> — ${q.explanation}</details></li>`)}</ol>
        <p class="small muted">راجع الأسئلة قبل استعمالها.</p>` : null}</div>
  </div>`;
}

// ------------------------------------------------------------------ 6 feedback draft (inside the grading form)

export function FeedbackDraftButton({ submissionId, onDraft }) {
  const ai = useAi();
  const [busy, setBusy] = useState(false);
  if (!ai?.staff) return null;
  const go = async () => {
    setBusy(true);
    try { const r = await api.post(`/api/ai/submissions/${submissionId}/feedback-draft`); onDraft(r.feedback); toast("أُضيفت مسودة تعليق؛ عدّلها قبل الحفظ"); }
    catch (e) { toastError(e); } finally { setBusy(false); }
  };
  return html`<button type="button" class="ghost small" disabled=${busy} onClick=${go}>${busy ? "…" : "اقترح تعليقاً (ذكاء اصطناعي)"}</button>`;
}

// ------------------------------------------------------------------ 8 written report

export function ReportNarrative() {
  const ai = useAi();
  const [run, busy, error, r] = useRun((fresh) => api.post(`/api/ai/reports/narrative${fresh ? "?fresh=true" : ""}`));
  if (!ai?.staff) return null;
  return html`<div class="card"><div class="row between"><h3>تقرير مكتوب</h3>
      <div class="row">${r ? html`<${When} r=${r} />` : null}<button class="small" disabled=${busy} onClick=${() => run(!!r)}>${busy ? "جارٍ الكتابة…" : r ? "تحديث" : "اكتب التقرير"}</button></div></div>
    <${ErrorBox} error=${error} />
    ${r ? html`<div class="stack"><p><strong>${r.headline}</strong></p><ul>${r.findings.map((x) => html`<li>${x}</li>`)}</ul>
      <div><strong>توصيات</strong><ul>${r.recommendations.map((x) => html`<li>${x}</li>`)}</ul></div></div>` : null}
    <${Note} /></div>`;
}

// ------------------------------------------------------------------ 9 attendance patterns

export function PatternsReading() {
  const ai = useAi();
  const [run, busy, error, r] = useRun(() => api.post("/api/ai/attendance/patterns"));
  if (!ai?.staff) return null;
  const name = (t) => Object.entries(r?.accounts || {}).reduce((s, [k, v]) => s.replaceAll(k, v), t);
  return html`<div class="card"><div class="row between"><h3>قراءة الأنماط</h3>
      <button class="small" disabled=${busy} onClick=${() => run()}>${busy ? "…" : "اشرح الأنماط"}</button></div>
    <${ErrorBox} error=${error} />
    ${r ? html`<div class="stack"><p>${name(r.summary)}</p><ul class="list">${r.items.map((i) => html`<li><strong>${name(i.what)}</strong>
      <div class="small">${name(i.why_it_matters)}</div><div class="small">ما يُراجَع: ${name(i.what_to_check)}</div></li>`)}</ul></div>` : null}
    <p class="small muted">إشارات للمراجعة البشرية فقط، ولا تعني مخالفة.</p></div>`;
}

// ------------------------------------------------------------------ 10 wording help (notification form)

export function ComposeHelper({ title, body, purpose, onApply }) {
  const ai = useAi();
  const [run, busy, error, r] = useRun(() => api.post("/api/ai/compose", { draft: `${title}\n${body}`.trim(), purpose }));
  if (!ai?.staff) return null;
  return html`<div class="field"><button type="button" class="ghost small" disabled=${busy || (title + body).trim().length < 5} onClick=${() => run()}>
      ${busy ? "…" : "حسّن الصياغة واقترح نص رسالة قصيرة"}</button><${ErrorBox} error=${error} />
    ${r ? html`<div class="card" style="margin-top:.4rem"><div><strong>${r.title}</strong></div><div style="white-space:pre-line">${r.text}</div>
      <div class="small" style="margin-top:.4rem">رسالة قصيرة (${r.sms_length} حرفاً${r.sms_fits ? "" : " — أطول من رسالة واحدة"}): ${r.sms}</div>
      <button type="button" class="small secondary" onClick=${() => onApply(r)}>استعمل هذه الصياغة</button></div>` : null}</div>`;
}
