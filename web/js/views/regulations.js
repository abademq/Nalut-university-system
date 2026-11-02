import { html, useState, useAsync, Async, Empty, Chip, ErrorBox, useSubmit, toast, toastError, fmtDate, Icon } from "../ui.js";
import { api, downloadFile } from "../api.js";

function Editor({ item, categories, faculties, onDone }) {
  const [title, setTitle] = useState(item?.title || "");
  const [body, setBody] = useState(item?.body || "");
  const [category, setCategory] = useState(item?.category || "general");
  const [faculty, setFaculty] = useState(item?.faculty_id || "");
  const [file, setFile] = useState(null);
  const [save, busy, error] = useSubmit(async () => {
    const fd = new FormData();
    fd.append("title", title); fd.append("body", body); fd.append("category", category);
    if (faculty) fd.append("faculty_id", faculty);
    if (file) fd.append("upload", file);
    await api.form(item ? `/api/regulations/${item.id}` : "/api/regulations", fd);
    toast(item ? "حُفظت اللائحة" : "نُشرت اللائحة", "success");
    onDone();
  });
  return html`<form class="card" onSubmit=${save}><h3>${item ? "تعديل لائحة" : "لائحة جديدة"}</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>العنوان</label><input value=${title} onInput=${(e) => setTitle(e.target.value)} required maxlength="200" /></div>
      <div class="field"><label>التصنيف</label><select value=${category} onChange=${(e) => setCategory(e.target.value)}>
        ${Object.entries(categories).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
      ${faculties ? html`<div class="field"><label>تخص</label><select value=${faculty} onChange=${(e) => setFaculty(e.target.value)}>
        <option value="">الجامعة كلها</option>${faculties.map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
    </div>
    <div class="field"><label>النص</label><textarea rows="10" value=${body} onInput=${(e) => setBody(e.target.value)} placeholder="مواد اللائحة، كل مادة في سطر"></textarea></div>
    <div class="field"><label>الملف الرسمي (PDF، اختياري)</label><input type="file" accept=".pdf,.doc,.docx" onChange=${(e) => setFile(e.target.files[0] || null)} /></div>
    <div class="row"><button disabled=${busy}>${item ? "حفظ" : "نشر"}</button><button type="button" class="ghost" onClick=${onDone}>إلغاء</button></div></form>`;
}

export function RegulationsView({ user }) {
  const state = useAsync(() => api.get("/api/regulations"), []);
  const structure = useAsync(() => (user.faculty ? Promise.resolve(null) : api.get("/api/org/structure")), []);
  const [edit, setEdit] = useState(null); // null | "new" | item
  const [cat, setCat] = useState("");
  return html`<div><div class="row between"><h1>اللوائح والقواعد</h1>
      ${state.data?.can_manage && !edit ? html`<button onClick=${() => setEdit("new")}>+ لائحة</button>` : null}</div>
    <${Async} state=${state}>${(d) => html`
      ${edit ? html`<${Editor} item=${edit === "new" ? null : edit} categories=${d.categories}
        faculties=${structure.data?.faculties || null} onDone=${() => { setEdit(null); state.reload(); }} />` : null}
      <div class="card"><h3>القواعد المطبقة في المنصة</h3><p class="small muted">${d.note}</p>
        ${d.applied.map((a) => html`<h4 style="margin:.7rem 0 .3rem">${a.title}</h4><ul>${a.items.map((i) => html`<li>${i}</li>`)}</ul>`)}</div>
      ${d.items.length ? html`<div class="row" style="flex-wrap:wrap;margin-bottom:.5rem">
        <button class=${`small ${cat ? "ghost" : ""}`} onClick=${() => setCat("")}>الكل</button>
        ${Object.entries(d.categories).filter(([k]) => d.items.some((i) => i.category === k)).map(([k, l]) => html`
          <button class=${`small ${cat === k ? "" : "ghost"}`} onClick=${() => setCat(k)}>${l}</button>`)}</div>
        ${d.items.filter((i) => !cat || i.category === cat).map((r) => html`<details class="card" open=${d.items.length <= 3}>
          <summary><strong>${r.title}</strong> <${Chip}>${r.category_label}<//> ${r.faculty ? html`<${Chip} kind="info">${r.faculty}<//>` : null}</summary>
          ${r.body ? html`<div style="white-space:pre-line;margin-top:.5rem">${r.body}</div>` : null}
          <div class="row" style="margin-top:.5rem">
            ${r.file ? html`<button class="secondary small" onClick=${() => downloadFile(r.file.id, r.file.name).catch(toastError)}>
              <${Icon} name="download" size=${16} /> ${r.file.name}</button>` : null}
            <span class="small muted">آخر تحديث ${fmtDate(r.updated_at)}</span>
            ${d.can_manage ? html`<span class="spacer"></span><button class="ghost small" onClick=${() => setEdit(r)}>تعديل</button>
              <button class="ghost small" onClick=${() => confirm("حذف هذه اللائحة؟") && api.del(`/api/regulations/${r.id}`).then(state.reload).catch(toastError)}>حذف</button>` : null}</div>
        </details>`)}` : html`<${Empty}>لم تُنشر لوائح بعد<//>`}`}<//></div>`;
}
