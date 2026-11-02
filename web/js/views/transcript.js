import { html, useAsync, Async, Empty, Chip, Kpi, pct } from "../ui.js";
import { api } from "../api.js";
import { StudentAdvisor } from "./ai.js";
import { MyDocuments } from "./documents.js";

const LEVEL = { danger: "error", warning: "warning", success: "success" };

// Published results by term, each term's average and the cumulative one, then study advice.
export function TranscriptCard({ t }) {
  if (!t) return null;
  const onPlatform = t.terms.filter((x) => !x.prior);
  const lastTerm = onPlatform[onPlatform.length - 1];
  return html`<div>
    <div class="kpis">
      <${Kpi} label="المعدل التراكمي" value=${t.cumulative_average !== null ? pct(t.cumulative_average) : "—"}
        hint=${t.cumulative_label ? `${t.cumulative_label} (${t.cumulative_letter})` : "يظهر بعد نشر أول نتيجة"} />
      <${Kpi} label="آخر معدل فصلي" value=${lastTerm ? pct(lastTerm.average) : "—"} hint=${lastTerm ? lastTerm.term : null} />
      <${Kpi} label="الوحدات المنجزة" value=${t.earned_credits} />
    </div>
    ${t.advice?.length ? html`<div class="card"><h3>نصائح للتركيز</h3>
      ${t.advice.map((a) => html`<div class=${`alert ${LEVEL[a.level] || "info"}`} style="margin:.35rem 0">${a.text}</div>`)}
      <p class="small muted">نصائح آلية من نتائجك وحضورك ومهامك، للتوجيه فقط وليست قراراً أكاديمياً.</p></div>` : null}
    ${t.terms.length ? [...t.terms].reverse().map((term) => html`<div class="card">
      <div class="row between"><h3>${term.term}</h3>
        <span>${term.prior ? "المعدل" : "المعدل الفصلي"}: <strong>${pct(term.average)}</strong> ${term.label ? html`<${Chip}>${term.label}<//>` : null}</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>المقرر</th><th class="num">الوحدات</th><th class="num">الدرجة</th><th>التقدير</th><th>النتيجة</th></tr></thead>
        <tbody>${term.courses.map((c) => html`<tr><td><span class="mono small">${c.code}</span> ${c.title}</td>
          <td class="num">${c.credits}</td><td class="num">${pct(c.percent)}</td><td>${c.letter || "—"}</td>
          <td>${c.state === "passed" ? html`<${Chip} kind="success">${c.source === "transfer" ? "معادلة" : c.source === "prior" ? "ناجح (قبل المنصة)" : "ناجح"}<//>`
            : html`<${Chip} kind="danger">راسب<//>`}</td></tr>`)}</tbody>
        <tfoot><tr><th>المجموع</th><th class="num">${term.credits}</th><th colspan="3" class="small">المنجز ${term.earned_credits} وحدة</th></tr></tfoot>
      </table></div></div>`) : html`<${Empty}>لم تُنشر نتائج بعد<//>`}
    <p class="small muted">المعدل متوسط الدرجات موزوناً بالوحدات (المواد المعادلة بلا درجة تُحتسب في الوحدات فقط). المقرر المعاد يُحتسب في التراكمي مرة واحدة بآخر نتيجة منشورة.
      درجة النجاح ${t.pass_mark}%.</p>
  </div>`;
}

export function TranscriptView() {
  const state = useAsync(() => api.get("/api/me/transcript"), []);
  return html`<div><h1>نتيجتي والمعدل</h1><${StudentAdvisor} /><${Async} state=${state}>${(t) => html`<${TranscriptCard} t=${t} />`}<//><${MyDocuments} /></div>`;
}
