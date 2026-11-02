import { html, useState, ErrorBox, toast, toastError, Chip } from "../ui.js";
import { api, downloadPath } from "../api.js";

const KINDS = {
  students: { title: "الطلبة", file: "students-template.xlsx",
    text: "الطلبة الحاليون والسابقون: رقم القيد، الاسم، البريد، الهاتف، الكلية، القسم، الدفعة، الحالة (مستمر، موقوف قيده، متخرج، منسحب)، الفصل الدراسي الحالي، التخصص." },
  results: { title: "النتائج السابقة", file: "results-template.xlsx",
    text: "المقررات التي نجح فيها الطلبة قبل المنصة أو بالمعادلة: رقم القيد، رمز المقرر، اسمه، وحداته، الدرجة %، الفصل، النوع (سابق أو معادلة). استورد الطلبة أولاً." },
};

// Saves the temporary passwords of the new accounts (shown once) as a CSV the administration hands out.
function savePasswords(list) {
  const csv = "\ufeffرقم القيد,الاسم,كلمة المرور المؤقتة\n" + list.map((p) => `${p.code},"${p.full_name.replaceAll('"', '""')}",${p.password}`).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = "new-student-passwords.csv";
  a.click();
}

function Importer({ kind }) {
  const k = KINDS[kind];
  const [file, setFile] = useState(null);
  const [pick, setPick] = useState(0);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const check = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const fd = new FormData();
      fd.append("upload", file);
      setPreview(await api.form(`/api/import/${kind}/preview`, fd));
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const apply = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.post(`/api/import/jobs/${preview.id}/commit`);
      setResult(r); setPreview(null); setFile(null); setPick(pick + 1);
      toast("طُبّق الملف", "success");
      if (r.passwords?.length) savePasswords(r.passwords);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return html`<div class="card"><h3>${k.title}</h3><p class="small muted">${k.text}</p>
    <div class="row" style="flex-wrap:wrap">
      <button class="secondary small" onClick=${() => downloadPath(`/api/import/${kind}/template`, k.file).catch(toastError)}>نزّل نموذج Excel</button>
      <input key=${pick} type="file" accept=".xlsx,.csv" style="max-width:260px" onChange=${(e) => { setFile(e.target.files[0] || null); setPreview(null); }} />
      <button class="small" disabled=${!file || busy} onClick=${check}>${busy && !preview ? "جارٍ الفحص…" : "افحص الملف"}</button></div>
    <${ErrorBox} error=${error} />
    ${preview ? html`<div style="margin-top:.7rem">
      <div class="row" style="flex-wrap:wrap"><${Chip}>${preview.summary.rows} سطر<//>
        ${preview.summary.create !== undefined ? html`<${Chip} kind="success">جديد ${preview.summary.create}<//><${Chip} kind="info">تحديث ${preview.summary.update}<//>` : null}
        ${preview.summary.errors ? html`<${Chip} kind="danger">${preview.summary.errors} سطر فيه أخطاء<//>` : html`<${Chip} kind="success">لا أخطاء<//>`}</div>
      ${preview.errors.length ? html`<div class="table-wrap" style="margin-top:.5rem"><table><thead><tr><th class="num">السطر</th><th>رقم القيد</th><th>المشكلة</th></tr></thead>
        <tbody>${preview.errors.map((e) => html`<tr><td class="num">${e.line}</td><td class="mono">${e.code || "—"}</td><td class="small">${e.problems.join("؛ ")}</td></tr>`)}</tbody></table></div>
        <p class="small muted">صحّح هذه الأسطر في الملف وارفعه من جديد؛ لا يُطبَّق شيء ما دام فيه أخطاء.</p>` : null}
      ${preview.can_commit ? html`<button disabled=${busy} onClick=${apply}>${busy ? "جارٍ التطبيق…" : `طبّق ${preview.summary.rows} سطر`}</button>` : null}</div>` : null}
    ${result ? html`<div class="alert success" style="margin-top:.6rem">
      ${result.created !== undefined ? `أُنشئ ${result.created} حساب، وحُدّث ${result.updated}.` : `أُضيف ${result.added} مقرر، وحُدّث ${result.updated}.`}
      ${result.passwords?.length ? html`<div class="small">نُزّل ملف كلمات المرور المؤقتة للحسابات الجديدة (يظهر مرة واحدة فقط).
        <button class="ghost small" onClick=${() => savePasswords(result.passwords)}>نزّله مرة أخرى</button></div>` : null}</div>` : null}
  </div>`;
}

export function ImportView({ user }) {
  const can = (k) => (user.can || []).includes(k);
  return html`<div><h1>استيراد البيانات</h1>
    <p class="muted">لإدخال البيانات الموجودة دفعة واحدة من Excel. يُفحص الملف أولاً ويظهر كل خطأ برقم سطره، ولا يتغير شيء حتى تضغط «طبّق».
      الطالب الموجود (بنفس رقم القيد) تُحدَّث بياناته ولا يتكرر.</p>
    ${can("users.manage") ? html`<${Importer} kind="students" />` : null}
    ${can("programs.manage") ? html`<${Importer} kind="results" />` : null}
    <p class="small muted">الطالب يدخل ببريده أو رقم هاتفه؛ من لا بريد ولا هاتف له لا يستطيع الدخول حتى يُضافا.</p></div>`;
}
