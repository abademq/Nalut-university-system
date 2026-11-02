// Course materials repository: files by course and term. Teachers publish; students share
// summaries that the course's teachers or the administration review before they appear.
import { html, useState, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, Tabs, fmtDate } from "../ui.js";
import { api, downloadPath } from "../api.js";

const size = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} م.ب` : `${Math.ceil(b / 1024)} ك.ب`);

function Upload({ code, cats, user, fac, onDone }) {
  const student = user.role === "student";
  const [v, bind, setV] = useForm({ category: student ? "summary" : "lecture", title: "", description: "" });
  const [file, setFile] = useState(null);
  const [submit, busy, error] = useSubmit(async () => {
    if (!file) throw new Error("اختر الملف");
    const fd = new FormData();
    fd.append("code", code);
    if (fac) fd.append("faculty_id", fac);
    Object.entries(v).forEach(([k, x]) => fd.append(k, x));
    fd.append("file", file);
    const m = await api.form("/api/materials", fd);
    toast(m.status === "pending" ? "أُرسل الملف للمراجعة، ويظهر للجميع بعد اعتماده" : "نُشر الملف");
    setV({ ...v, title: "", description: "" });
    setFile(null);
    onDone();
  });
  return html`<form class="card" onSubmit=${submit}><h3>${student ? "مشاركة ملف (ملخص، حلول…)" : "رفع ملف"}</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>التصنيف</label><select ...${bind("category")}>${Object.entries(cats).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
      <div class="field"><label>العنوان</label><input ...${bind("title")} required minlength="3" maxlength="200" /></div>
      <div class="field"><label>الملف</label><input type="file" required onChange=${(e) => setFile(e.target.files[0] || null)} /></div></div>
    <div class="field"><label>وصف (اختياري)</label><input ...${bind("description")} maxlength="1000" /></div>
    ${student ? html`<p class="small muted">يراجع أستاذ المقرر أو الإدارة الملف قبل ظهوره، ويُنسب إليك عند نشره. لا ترفع ما ليس لك حق نشره.</p>` : null}
    <button disabled=${busy}>${student ? "إرسال للمراجعة" : "نشر"}</button></form>`;
}

function FileRow({ m, reload }) {
  const decide = async (approve) => {
    const reason = approve ? null : prompt("سبب عدم النشر (يصل لصاحب الملف):");
    if (!approve && !reason) return;
    try { await api.post(`/api/materials/${m.id}/review`, { approve, reason }); reload(); } catch (e) { toastError(e); }
  };
  const del = async () => {
    if (!confirm("حذف الملف من المستودع؟")) return;
    try { await api.del(`/api/materials/${m.id}`); reload(); } catch (e) { toastError(e); }
  };
  return html`<li><div class="row between" style="flex-wrap:wrap"><div>
      <strong>${m.title}</strong> <span class="small muted">${m.category_label}${m.term ? ` · ${m.term}` : ""}</span>
      ${m.status === "pending" ? html` <${Chip} kind="warning">قيد المراجعة<//>` : null}
      ${m.status === "rejected" ? html` <${Chip} kind="error">لم يُنشر: ${m.reject_reason}<//>` : null}
      <div class="small muted">${m.by_student ? `بإعداد الطالب ${m.uploader}` : m.uploader} · ${fmtDate(m.created_at)}
        ${m.file ? ` · ${size(m.file.size)}` : ""} · ${m.downloads} تنزيل</div>
      ${m.description ? html`<div class="small">${m.description}</div>` : null}</div>
    <div class="row"><button class="small" onClick=${() => downloadPath(`/api/materials/${m.id}/download`, m.file?.name).then(reload).catch(toastError)}>تنزيل</button>
      ${m.can_review && m.status !== "published" ? html`<button class="small secondary" onClick=${() => decide(true)}>نشر</button>` : null}
      ${m.can_review && m.status !== "rejected" ? html`<button class="small ghost" onClick=${() => decide(false)}>${m.status === "published" ? "سحب" : "رفض"}</button>` : null}
      ${m.can_review || (m.mine && (m.status !== "published" || !m.by_student)) ? html`<button class="small ghost" onClick=${del}>حذف</button>` : null}</div></div></li>`;
}

function CourseFiles({ course, cats, user, fac, back }) {
  const list = useAsync(() => api.get(`/api/materials?code=${encodeURIComponent(course.code)}${fac ? `&faculty_id=${fac}` : ""}`), [course.code, fac]);
  const [cat, setCat] = useState("");
  return html`<div>
    <div class="row between"><h2>${course.code} — ${course.title}</h2><button class="secondary small" onClick=${back}>← كل المقررات</button></div>
    <div class="card"><div class="field" style="max-width:240px"><select value=${cat} onChange=${(e) => setCat(e.target.value)}>
      <option value="">كل التصنيفات</option>${Object.entries(cats).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <${Async} state=${list}>${(rows) => {
      const shown = rows.filter((m) => !cat || m.category === cat);
      return shown.length ? html`<ul class="list">${shown.map((m) => html`<${FileRow} m=${m} reload=${list.reload} />`)}</ul>` : html`<${Empty}>لا توجد ملفات بعد<//>`;
    }}<//></div>
    <${Upload} code=${course.code} cats=${cats} user=${user} fac=${fac} onDone=${list.reload} />
  </div>`;
}

export function MaterialsView({ user, params }) {
  const cats = useAsync(() => api.get("/api/materials/categories"), []);
  const org = useAsync(() => (user.faculty ? Promise.resolve(null) : api.get("/api/org/structure")), []);
  const [fac, setFac] = useState("");
  const courses = useAsync(() => (user.faculty || fac ? api.get(`/api/materials/courses${fac ? `?faculty_id=${fac}` : ""}`)
    : Promise.resolve([])), [fac]);
  const queue = useAsync(() => (user.role === "student" ? Promise.resolve([]) : api.get("/api/materials/pending")), []);
  const [tab, setTab] = useState(params?.get("review") ? "review" : "courses");
  const [course, setCourse] = useState(null);
  const [q, setQ] = useState("");
  if (!cats.data) return null;
  const tabs = [["courses", "المقررات"]];
  if ((queue.data || []).length) tabs.push(["review", `للمراجعة (${queue.data.length})`]);
  return html`<div><h1>مستودع المواد</h1>
    <p class="muted">ملفات كل مقرر عبر الفصول: محاضرات، ملخصات، امتحانات سابقة، تمارين ومراجع.</p>
    ${tabs.length > 1 ? html`<${Tabs} value=${tab} onChange=${setTab} tabs=${tabs} />` : null}
    ${org.data ? html`<div class="field" style="max-width:320px"><label>الكلية</label><select value=${fac} onChange=${(e) => { setFac(e.target.value); setCourse(null); }}>
      <option value="">اختر…</option>${org.data.faculties.map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
    ${tab === "review" ? html`<div class="card"><ul class="list">${(queue.data || []).map((m) => html`<li>
      <div class="small muted">${m.course_code} — ${m.course_title}</div></li><${FileRow} m=${m} reload=${() => { queue.reload(); courses.reload(); }} />`)}</ul></div>` : null}
    ${tab === "courses" && course ? html`<${CourseFiles} course=${course} cats=${cats.data} user=${user} fac=${fac} back=${() => { setCourse(null); courses.reload(); }} />` : null}
    ${tab === "courses" && !course ? html`<div class="card"><div class="field" style="max-width:320px"><input placeholder="بحث برمز المقرر أو اسمه" value=${q}
      onInput=${(e) => setQ(e.target.value)} /></div>
      <${Async} state=${courses}>${(rows) => {
        const shown = rows.filter((c) => !q || c.code.includes(q) || c.title.includes(q));
        return shown.length ? html`<div class="table-wrap"><table><thead><tr><th>المقرر</th><th class="num">الملفات</th><th></th></tr></thead>
          <tbody>${shown.map((c) => html`<tr style="cursor:pointer" onClick=${() => setCourse(c)}><td><span class="mono">${c.code}</span> — ${c.title}
            ${c.mine ? html` <${Chip} kind="info">مقرراتي<//>` : null}</td><td class="num">${c.files}${c.pending ? html` <${Chip} kind="warning">${c.pending} للمراجعة<//>` : null}</td>
            <td><button class="small secondary">فتح</button></td></tr>`)}</tbody></table></div>` : html`<${Empty}>لا توجد مقررات<//>`;
      }}<//></div>` : null}
  </div>`;
}
