// Official documents with a QR to check them: issued by student affairs ("documents.issue"),
// or by the student for an enrolment certificate when the institution allows it.
import { html, useAsync, Async, Empty, Chip, useForm, useSubmit, ErrorBox, toast, toastError, fmtDate } from "../ui.js";
import { api } from "../api.js";

export async function openDocument(id) {
  const w = window.open("", "_blank"); // opened now, while the click still counts, then pointed at the link
  try {
    const { url } = await api.post(`/api/documents/${id}/link`);
    if (w) w.location.href = url; else window.location.href = url;
  } catch (e) { if (w) w.close(); toastError(e); }
}

function DocList({ rows, manage, reload }) {
  const revoke = async (d) => {
    const reason = prompt("سبب إلغاء الوثيقة (يظهر لمن يتحقق منها):");
    if (!reason || reason.trim().length < 3) return;
    try { await api.post(`/api/documents/${d.id}/revoke`, { reason }); reload(); } catch (e) { toastError(e); }
  };
  return rows.length ? html`<div class="table-wrap"><table><thead><tr><th>الوثيقة</th><th>الرقم</th><th>موجهة إلى</th><th>الإصدار</th><th>الحالة</th><th></th></tr></thead>
    <tbody>${rows.map((d) => html`<tr><td>${d.kind_label}</td><td class="mono small">${d.code}</td><td class="small">${d.addressee}</td>
      <td class="small">${fmtDate(d.issued_at)}<div class="muted">${d.self_issued ? "بطلب الطالب" : d.issuer}</div></td>
      <td>${d.revoked_at ? html`<${Chip} kind="error">ملغاة<//>` : html`<${Chip} kind="success">سارية<//>`}</td>
      <td class="row"><button class="small" onClick=${() => openDocument(d.id)}>عرض وطباعة</button>
        ${manage && !d.revoked_at ? html`<button class="small ghost" onClick=${() => revoke(d)}>إلغاء</button>` : null}</td></tr>`)}</tbody></table></div>`
    : html`<${Empty}>لا توجد وثائق صادرة<//>`;
}

/** On a student's page, for those who issue documents. */
export function StudentDocuments({ studentId }) {
  const list = useAsync(() => api.get(`/api/documents?student_id=${studentId}`), [studentId]);
  const [v, bind] = useForm({ kind: "enrollment", addressee: "إلى من يهمه الأمر" });
  const [submit, busy, error] = useSubmit(async () => {
    const d = await api.post("/api/documents", { student_id: Number(studentId), kind: v.kind, addressee: v.addressee });
    toast("صدرت الوثيقة");
    list.reload();
    openDocument(d.id);
  });
  return html`<div class="card"><h3>الوثائق الرسمية</h3>
    <form onSubmit=${submit}><${ErrorBox} error=${error} /><div class="form-grid">
      <div class="field"><label>الوثيقة</label><select ...${bind("kind")}><option value="enrollment">إفادة قيد</option><option value="transcript">كشف درجات</option></select></div>
      <div class="field"><label>موجهة إلى</label><input ...${bind("addressee")} required minlength="3" maxlength="200" /></div>
      <div class="field"><label> </label><button disabled=${busy}>إصدار</button></div></div></form>
    <p class="small muted">كل وثيقة تحمل رمز QR يفتح صفحة تحقق عامة تبيّن صحتها وبياناتها الأساسية. تُحفظ كما صدرت، فتعديل الدرجات لاحقاً لا يغيّرها؛ وإن احتجت تصحيحها فألغِها وأصدر غيرها.</p>
    <${Async} state=${list}>${(rows) => html`<${DocList} rows=${rows} manage reload=${list.reload} />`}<//></div>`;
}

/** The student's own documents (and an enrolment certificate when self-issue is allowed). */
export function MyDocuments() {
  const list = useAsync(() => api.get("/api/documents"), []);
  const issue = async () => {
    const addressee = prompt("موجهة إلى:", "إلى من يهمه الأمر");
    if (!addressee) return;
    try {
      const d = await api.post("/api/documents", { kind: "enrollment", addressee });
      list.reload();
      openDocument(d.id);
    } catch (e) { toastError(e); }
  };
  return html`<div class="card"><div class="row between"><h3>وثائقي الرسمية</h3>
    <button class="small secondary" onClick=${issue}>إفادة قيد إلكترونية</button></div>
    <${Async} state=${list}>${(rows) => html`<${DocList} rows=${rows} reload=${list.reload} />`}<//>
    <p class="small muted">كشف الدرجات الرسمي وإفادة القيد المختومة تُطلب من «الطلبات والمعاملات».</p></div>`;
}
