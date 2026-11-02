import { html, useState, useAsync, Async, Empty, Chip, Kpi, ErrorBox, useForm, useSubmit, toast, toastError } from "../ui.js";
import { api } from "../api.js";

const STATE = {
  passed: ["ناجح", "success"], failed: ["راسب", "danger"], in_progress: ["قيد الدراسة", "info"], remaining: ["لم يُدرس", ""],
};
const NEXT = {
  open: ["متاح", "success"], pending: ["متاح إذا نجحت في متطلبه هذا الفصل", "warning"], closed: ["مغلق: متطلب لم يُنجز", "danger"],
};
const reqs = (c) => c.prerequisites.length
  ? c.prerequisites.map((p, i) => html`${i ? "، " : ""}<span class=${p.state === "passed" ? "" : "muted"}>${p.code}</span>`)
  : html`<span class="muted">—</span>`;

// Where a student stands in their programme: what must be passed now, what comes next, the plan.
export function PlanCard({ p }) {
  if (!p || !p.program) return html`<${Empty}>لم يُربط بتخصص بعد. تواصل مع إدارة الكلية.<//>`;
  return html`<div>
    <p class="muted">التخصص: <strong>${p.program.name}</strong> · ${p.level ? `الفصل الدراسي ${p.level}` : "لم يبدأ بعد"}</p>
    <div class="kpis">
      <${Kpi} label="وحدات الخطة (الإجبارية)" value=${p.plan_credits} />
      <${Kpi} label="المنجز" value=${p.earned_credits} />
      <${Kpi} label="المتبقي" value=${p.remaining_credits} />
    </div>
    ${p.must_pass.length ? html`<div class="card"><h3>لازم تنجح فيها هذا الفصل</h3>
      <p class="small muted">مقررات تدرسها الآن، وهي متطلب سابق لمقررات الفصل القادم؛ إن لم تنجح فيها تُغلق عليك.</p>
      <ul class="list">${p.must_pass.map((m) => html`<li><strong>${m.title}</strong> <span class="mono small">(${m.code})</span>
        <div class="small">تفتح لك: ${m.unlocks.join("، ")}</div></li>`)}</ul></div>` : null}
    <div class="card"><h3>مقررات الفصل القادم (الفصل ${p.next_semester})</h3>
      ${p.next_courses.length ? html`<div class="table-wrap"><table>
        <thead><tr><th>المقرر</th><th class="num">الوحدات</th><th>في الخطة</th><th>المتطلبات</th><th>الحالة</th></tr></thead>
        <tbody>${p.next_courses.map((c) => html`<tr><td><span class="mono small">${c.code}</span> ${c.title}${c.required ? "" : html` <${Chip}>اختياري<//>`}</td>
          <td class="num">${c.credits}</td>
          <td class="small">الفصل ${c.semester}${c.overdue ? html` <${Chip} kind="warning">متأخر عن خطته<//>` : null}</td>
          <td class="small">${reqs(c)}</td>
          <td><${Chip} kind=${NEXT[c.status][1]}>${NEXT[c.status][0]}<//>
            ${c.status === "closed" ? html`<div class="small muted">ينقصك: ${c.missing.filter((m) => m.state !== "in_progress").map((m) => m.title).join("، ")}</div>` : null}</td></tr>`)}</tbody>
      </table></div>` : html`<${Empty}>لا توجد مقررات متبقية حتى هذا الفصل<//>`}</div>
    <div class="card"><h3>الخطة الدراسية كاملة</h3>
      ${p.semesters.filter((s) => s.courses.length).map((s) => html`<h4 style="margin:.8rem 0 .3rem">الفصل ${s.semester}
          <span class="small muted">· ${s.credits} وحدة · المنجز ${s.earned}</span></h4>
        <div class="table-wrap"><table><tbody>${s.courses.map((c) => html`<tr>
          <td><span class="mono small">${c.code}</span> ${c.title}${c.required ? "" : html` <${Chip}>اختياري<//>`}</td>
          <td class="num">${c.credits} وحدات</td><td class="small">يتطلب: ${reqs(c)}</td>
          <td><${Chip} kind=${STATE[c.state][1]}>${STATE[c.state][0]}<//></td></tr>`)}</tbody></table></div>`)}
    </div>
  </div>`;
}

export function MyPlanView() {
  const state = useAsync(() => api.get("/api/me/plan"), []);
  return html`<div><h1>خطتي الدراسية</h1><${Async} state=${state}>${(p) => html`<${PlanCard} p=${p} />`}<//></div>`;
}

// ------------------------------------------------------------------ administration

function PlanEditor({ program, onSaved }) {
  const [rows, setRows] = useState(program.courses.map((c) => ({ ...c, prerequisites: c.prerequisites.join(" ") })));
  const set = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const [save, busy, error] = useSubmit(async () => {
    await api.put(`/api/programs/${program.id}/courses`, { courses: rows.map((r) => ({
      semester: Number(r.semester), code: r.code.trim(), title: r.title.trim(), credits: Number(r.credits),
      required: !!r.required, prerequisites: String(r.prerequisites).split(/[\s,،]+/).filter(Boolean) })) });
    toast("حُفظت الخطة", "success");
    onSaved();
  });
  const total = rows.filter((r) => r.required).reduce((n, r) => n + Number(r.credits || 0), 0);
  return html`<form class="card" onSubmit=${save}><h3>الخطة الدراسية</h3><${ErrorBox} error=${error} />
    <p class="small muted">كل مقرر برمزه وفصله في الخطة ووحداته ومتطلباته (رموز من الخطة في فصول سابقة). المتطلبات تصبح قاعدة تسجيل
      للمقرر في كل فصل يُطرح فيه. مجموع الوحدات الإجبارية: <strong>${total}</strong></p>
    <div class="table-wrap"><table>
      <thead><tr><th>الفصل</th><th>الرمز</th><th>الاسم</th><th>الوحدات</th><th>إجباري</th><th>المتطلبات</th><th></th></tr></thead>
      <tbody>${rows.map((r, i) => html`<tr>
        <td><select value=${r.semester} onChange=${(e) => set(i, "semester", e.target.value)}>
          ${Array.from({ length: program.semesters }, (_, k) => html`<option value=${k + 1}>${k + 1}</option>`)}</select></td>
        <td><input class="ltr" style="max-width:110px" value=${r.code} onInput=${(e) => set(i, "code", e.target.value)} required /></td>
        <td><input value=${r.title} onInput=${(e) => set(i, "title", e.target.value)} required /></td>
        <td><input type="number" min="0" max="20" style="max-width:70px" value=${r.credits} onInput=${(e) => set(i, "credits", e.target.value)} /></td>
        <td><input type="checkbox" checked=${r.required} onChange=${(e) => set(i, "required", e.target.checked)} aria-label="إجباري" /></td>
        <td><input class="ltr" style="max-width:160px" value=${r.prerequisites} aria-label="المتطلبات" onInput=${(e) => set(i, "prerequisites", e.target.value)} /></td>
        <td><button type="button" class="ghost small" onClick=${() => setRows(rows.filter((_, j) => j !== i))}>حذف</button></td></tr>`)}</tbody>
    </table></div>
    <div class="row"><button type="button" class="secondary small" onClick=${() => setRows([...rows,
      { semester: rows.length ? rows[rows.length - 1].semester : 1, code: "", title: "", credits: 3, required: true, prerequisites: "" }])}>+ مقرر</button>
      <span class="spacer"></span><button disabled=${busy}>حفظ الخطة</button></div></form>`;
}

function Placement({ program, onDone }) {
  const [codes, setCodes] = useState("");
  const [place, busy, error] = useSubmit(async () => {
    const r = await api.post(`/api/programs/${program.id}/students`, { student_codes: codes.split(/[\s,،]+/).filter(Boolean) });
    toast(`رُبط ${r.placed.length} طالب${r.unknown.length ? ` — غير معروف أو من كلية أخرى: ${r.unknown.join("، ")}` : ""}`);
    setCodes("");
    onDone();
  });
  return html`<form class="card" onSubmit=${place}><h3>ربط طلبة بالتخصص</h3><${ErrorBox} error=${error} />
    <div class="field"><label>أرقام القيد</label><textarea value=${codes} onInput=${(e) => setCodes(e.target.value)} required></textarea></div>
    <p class="small muted">الطالب غير المربوط يتبع تلقائياً تخصص قسمه إن كان للقسم تخصص واحد.</p>
    <button disabled=${busy}>ربط</button></form>`;
}

export function ProgramDetail({ id }) {
  const state = useAsync(() => api.get(`/api/programs/${id}`), [id]);
  return html`<${Async} state=${state}>${(p) => html`<div>
    <div class="row"><a href="#/programs">← التخصصات</a></div>
    <h1>${p.name} <span class="mono small muted">${p.code}</span></h1>
    <p class="muted">${p.semesters} فصول · ${p.credits} وحدة إجبارية · ${p.students} طالب مربوط</p>
    <${PlanEditor} key=${p.courses.length} program=${p} onSaved=${state.reload} />
    <${Placement} program=${p} onDone=${state.reload} /></div>`}<//>`;
}

export function ProgramsView({ user }) {
  const state = useAsync(() => api.get("/api/programs"), []);
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const [v, bind] = useForm({ name: "", code: "", semesters: 8, faculty_id: user.faculty?.id || "", department_id: "" });
  const [create, busy, error] = useSubmit(async () => {
    await api.post("/api/programs", { name: v.name, code: v.code, semesters: Number(v.semesters),
      faculty_id: v.faculty_id ? Number(v.faculty_id) : null, department_id: v.department_id ? Number(v.department_id) : null });
    toast("أُنشئ التخصص", "success");
    state.reload();
  });
  const facs = structure.data?.faculties || [];
  const fac = facs.find((f) => String(f.id) === String(v.faculty_id));
  return html`<div><h1>التخصصات والخطط الدراسية</h1>
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="grid cols-3">${rows.map((p) => html`
      <a class="card item-link" href=${`#/programs/${p.id}`}><div class="row between"><strong>${p.name}</strong><span class="mono small">${p.code}</span></div>
        <div class="small muted">${p.semesters} فصول · ${p.credits} وحدة إجبارية · ${p.students} طالب</div></a>`)}</div>`
      : html`<${Empty}>لا توجد تخصصات بعد<//>`}<//>
    <form class="card" onSubmit=${create}><h3>تخصص جديد</h3><${ErrorBox} error=${error} />
      <div class="form-grid">
        <div class="field"><label>الاسم</label><input ...${bind("name")} required /></div>
        <div class="field"><label>الرمز</label><input class="ltr" ...${bind("code")} required /></div>
        <div class="field"><label>عدد الفصول</label><input type="number" min="1" max="14" ...${bind("semesters")} /></div>
        ${!user.faculty ? html`<div class="field"><label>الكلية</label><select ...${bind("faculty_id")} required><option value="">—</option>
          ${facs.map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
        <div class="field"><label>القسم</label><select ...${bind("department_id")}><option value="">—</option>
          ${((fac || facs.find((f) => f.id === user.faculty?.id))?.departments || []).map((d) => html`<option value=${d.id}>${d.name}</option>`)}</select></div>
      </div><button disabled=${busy}>إنشاء</button></form></div>`;
}
