import { html, useState, useAsync, Async, Empty, Chip, Tabs, ErrorBox, useForm, useSubmit, toast, DAYS, ROLE, fmtDate } from "../ui.js";
import { api } from "../api.js";

const isAdmin = (u) => u.role === "university_admin" || u.role === "faculty_admin";

function CreateCourse({ user, onCreated }) {
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const [v, bind] = useForm({ code: "", title: "", credits: 3, faculty_id: user.faculty?.id || "", department_id: "",
    day: 0, start: "08:30", end: "10:00", room: "" });
  const [submit, busy, error] = useSubmit(async () => {
    const body = { code: v.code, title: v.title, credits: Number(v.credits),
      faculty_id: v.faculty_id ? Number(v.faculty_id) : null, department_id: v.department_id ? Number(v.department_id) : null,
      schedule: v.room ? [{ day: Number(v.day), start: v.start, end: v.end, room: v.room }] : [] };
    const term = structure.data?.terms.find((t) => t.is_current);
    if (term) body.term_id = term.id;
    await api.post("/api/courses", body);
    toast("تم إنشاء المقرر");
    onCreated();
  });
  const faculties = structure.data?.faculties || [];
  const fac = faculties.find((f) => String(f.id) === String(v.faculty_id));
  return html`<form class="card" onSubmit=${submit}><h3>مقرر جديد</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>الرمز</label><input ...${bind("code")} required /></div>
      <div class="field"><label>اسم المقرر</label><input ...${bind("title")} required /></div>
      <div class="field"><label>الوحدات</label><input type="number" min="0" max="20" ...${bind("credits")} /></div>
      ${user.role === "university_admin" ? html`<div class="field"><label>الكلية</label><select ...${bind("faculty_id")} required>
        <option value="">—</option>${faculties.map((f) => html`<option value=${f.id}>${f.name}</option>`)}</select></div>` : null}
      <div class="field"><label>القسم</label><select ...${bind("department_id")}><option value="">—</option>
        ${(fac?.departments || []).map((d) => html`<option value=${d.id}>${d.name}</option>`)}</select></div>
      <div class="field"><label>اليوم</label><select ...${bind("day")}>${DAYS.map((d, i) => html`<option value=${i}>${d}</option>`)}</select></div>
      <div class="field"><label>من</label><input type="time" ...${bind("start")} /></div>
      <div class="field"><label>إلى</label><input type="time" ...${bind("end")} /></div>
      <div class="field"><label>القاعة</label><input ...${bind("room")} /></div>
    </div>
    <p class="small muted">تُنشأ عناصر التقييم الافتراضية (أعمال السنة 40، النهائي 60) ويمكن تعديلها لاحقاً.</p>
    <button disabled=${busy}>إنشاء</button></form>`;
}

export function CoursesView({ user }) {
  const state = useAsync(() => api.get("/api/courses"), []);
  const [creating, setCreating] = useState(false);
  return html`<div>
    <div class="row between"><h1>المقررات</h1>
      ${isAdmin(user) ? html`<button onClick=${() => setCreating(!creating)}>${creating ? "إلغاء" : "+ مقرر جديد"}</button>` : null}</div>
    ${creating ? html`<${CreateCourse} user=${user} onCreated=${() => { setCreating(false); state.reload(); }} />` : null}
    <${Async} state=${state}>${(courses) => courses.length ? html`<div class="grid cols-3">${courses.map((c) => html`
      <a class="card item-link" href=${`#/courses/${c.id}`}>
        <div class="row between"><strong>${c.code}</strong><${Chip}>${c.credits} وحدات<//></div>
        <h3 style="margin-top:.3rem">${c.title}</h3>
        <div class="small muted">${c.staff.map((s) => s.full_name).join("، ") || "لم يُسند بعد"}</div>
        <div class="small muted">${c.students_count} طالب · ${c.schedule.map((s) => `${DAYS[s.day]} ${s.start}`).join("، ")}</div>
      </a>`)}</div>` : html`<${Empty}>لا توجد مقررات<//>`}<//>
  </div>`;
}

// Weekly lecture slots of a course: any number of (day, from, to, room).
function SlotsEditor({ slots, onChange }) {
  const set = (i, k, val) => onChange(slots.map((s, j) => (j === i ? { ...s, [k]: k === "day" ? Number(val) : val } : s)));
  return html`<div class="field"><label>مواعيد المحاضرات الأسبوعية</label>
    ${slots.map((s, i) => html`<div class="row" style="margin-bottom:.4rem;flex-wrap:wrap">
      <select style="max-width:130px" value=${s.day} onChange=${(e) => set(i, "day", e.target.value)}>${DAYS.map((d, k) => html`<option value=${k}>${d}</option>`)}</select>
      <input type="time" style="max-width:120px" value=${s.start} onInput=${(e) => set(i, "start", e.target.value)} aria-label="من" />
      <input type="time" style="max-width:120px" value=${s.end} onInput=${(e) => set(i, "end", e.target.value)} aria-label="إلى" />
      <input style="max-width:160px" placeholder="القاعة" value=${s.room} onInput=${(e) => set(i, "room", e.target.value)} />
      <button type="button" class="small secondary" onClick=${() => onChange(slots.filter((_, j) => j !== i))}>حذف</button></div>`)}
    <button type="button" class="small secondary" onClick=${() => onChange([...slots, { day: 0, start: "08:30", end: "10:00", room: "" }])}>+ موعد</button>
    <div class="small muted" style="margin-top:.2rem">تظهر في «جدولي» بالتطبيق للطلبة المسجلين وأساتذة المقرر.</div></div>`;
}

function EditCourse({ course, onChange }) {
  const structure = useAsync(() => api.get("/api/org/structure"), []);
  const [slots, setSlots] = useState(course.schedule.map((s) => ({ day: s.day, start: s.start, end: s.end, room: s.room || "" })));
  const [v, bind] = useForm({ code: course.code, title: course.title, credits: course.credits,
    department_id: course.department_id || "", term_id: course.term_id || "" });
  const [submit, busy, error] = useSubmit(async () => {
    const schedule = slots.filter((s) => s.start && s.end);
    await api.patch(`/api/courses/${course.id}`, { code: v.code, title: v.title, credits: Number(v.credits),
      department_id: v.department_id ? Number(v.department_id) : null, term_id: v.term_id ? Number(v.term_id) : null, schedule });
    toast("تم حفظ المقرر");
    onChange();
  });
  const fac = (structure.data?.faculties || []).find((f) => f.id === course.faculty_id);
  return html`<form class="card" onSubmit=${submit}><h3>بيانات المقرر</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      <div class="field"><label>الرمز</label><input ...${bind("code")} required /></div>
      <div class="field"><label>الاسم</label><input ...${bind("title")} required /></div>
      <div class="field"><label>الوحدات</label><input type="number" min="0" max="20" ...${bind("credits")} /></div>
      <div class="field"><label>القسم</label><select ...${bind("department_id")}><option value="">—</option>
        ${(fac?.departments || []).map((d) => html`<option value=${d.id}>${d.name}</option>`)}</select></div>
      <div class="field"><label>الفصل الدراسي</label><select ...${bind("term_id")}><option value="">—</option>
        ${(structure.data?.terms || []).map((t) => html`<option value=${t.id}>${t.name}</option>`)}</select></div>
    </div>
    <${SlotsEditor} slots=${slots} onChange=${setSlots} />
    <button disabled=${busy}>حفظ</button></form>`;
}

function Components({ course, onChange }) {
  const [name, setName] = useState("");
  const [max, setMax] = useState("");
  const act = async (fn) => { try { await fn(); toast("تم"); onChange(); } catch (e) { toastError(e); } };
  return html`<div class="card"><h3>عناصر التقييم</h3>
    <p class="small muted">يمكن تعديلها ما دامت النتائج في حالة «مسودة». لا يُحذف عنصر عليه درجات مرصودة.</p>
    <ul class="list">${course.components.map((c) => html`<li class="row between"><span>${c.name} <span class="muted">(${c.max_score})</span></span>
      <span class="row"><button class="ghost small" onClick=${() => {
        const n = prompt("اسم العنصر:", c.name); if (n === null) return;
        const m = prompt("الدرجة القصوى:", c.max_score); if (m === null) return;
        act(() => api.patch(`/api/components/${c.id}`, { name: n, max_score: Number(m) }));
      }}>تعديل</button><button class="ghost small" onClick=${() => confirm(`حذف ${c.name}؟`) && act(() => api.del(`/api/components/${c.id}`))}>حذف</button></span></li>`)}</ul>
    <div class="row" style="margin-top:.5rem"><input style="max-width:200px" placeholder="عنصر جديد" value=${name} onInput=${(e) => setName(e.target.value)} />
      <input style="max-width:110px" type="number" placeholder="الدرجة" value=${max} onInput=${(e) => setMax(e.target.value)} />
      <button class="small" disabled=${!name || !max} onClick=${() => act(async () => { await api.post(`/api/courses/${course.id}/components`, { name, max_score: Number(max) }); setName(""); setMax(""); })}>إضافة</button></div>
  </div>`;
}

function StaffManager({ course, onChange }) {
  const teachers = useAsync(() => Promise.all([api.get("/api/users?role=teacher&limit=200"), api.get("/api/users?role=assistant&limit=200")])
    .then(([a, b]) => [...a.items, ...b.items]), []);
  const [v, bind] = useForm({ user_id: "", role: "instructor" });
  const [codes, setCodes] = useState("");
  const [assign, busy, error] = useSubmit(async () => {
    await api.post(`/api/courses/${course.id}/staff`, { user_id: Number(v.user_id), role: v.role });
    toast("تم الإسناد");
    onChange();
  });
  const [enroll, busy2, error2] = useSubmit(async () => {
    const r = await api.post(`/api/courses/${course.id}/enrollments`, { student_codes: codes.split(/[\s,،]+/).filter(Boolean) });
    toast(`أُضيف ${r.added.length} طالب${r.unknown.length ? ` — غير معروف: ${r.unknown.join("، ")}` : ""}`);
    setCodes("");
    onChange();
  });
  return html`<div class="grid cols-2">
    <form class="card" onSubmit=${assign}><h3>إسناد عضو هيئة تدريس</h3><${ErrorBox} error=${error} />
      <div class="field"><select ...${bind("user_id")} required><option value="">اختر…</option>
        ${(teachers.data || []).map((t) => html`<option value=${t.id}>${t.full_name} (${ROLE[t.role]})</option>`)}</select></div>
      <div class="field"><select ...${bind("role")}><option value="instructor">أستاذ المقرر</option><option value="assistant">معيد</option></select></div>
      <button disabled=${busy}>إسناد</button></form>
    <form class="card" onSubmit=${enroll}><h3>تسجيل طلبة</h3><${ErrorBox} error=${error2} />
      <div class="field"><label>أرقام القيد (مفصولة بمسافة أو فاصلة)</label><textarea value=${codes} onInput=${(e) => setCodes(e.target.value)} required></textarea></div>
      <button disabled=${busy2}>تسجيل</button></form>
  </div>`;
}

export function CourseDetail({ id, user }) {
  const state = useAsync(() => api.get(`/api/courses/${id}`), [id]);
  const teaches = user.role !== "student";
  const students = useAsync(() => (teaches ? api.get(`/api/courses/${id}/students`) : Promise.resolve([])), [id]);
  const assignments = useAsync(() => api.get(`/api/assignments?course_id=${id}`), [id]);
  const [tab, setTab] = useState("info");
  return html`<${Async} state=${state}>${(c) => html`<div>
    <h1>${c.code} — ${c.title}</h1>
    <${Tabs} value=${tab} onChange=${setTab} tabs=${[["info", "نظرة عامة"], ["assignments", "المهام"],
      ...(teaches ? [["students", `الطلبة (${c.students_count})`]] : []), ...(isAdmin(user) ? [["manage", "الإدارة"]] : teaches ? [["components", "عناصر التقييم"]] : [])]} />
    ${tab === "info" ? html`<div class="grid cols-2">
      <div class="card"><h3>معلومات المقرر</h3><ul class="list">
        <li>الوحدات: ${c.credits}</li>
        <li>هيئة التدريس: ${c.staff.map((s) => html`<div>${s.full_name} <span class="small muted">${s.role === "assistant" ? "معيد" : "أستاذ"}</span>
          ${user.role === "student" ? html` · <a href=${`#/messages?to=${s.id}&course=${c.id}`}>مراسلة</a>` : null}</div>`)}</li>
        <li>عناصر التقييم: ${c.components.map((x) => `${x.name} (${x.max_score})`).join("، ")}</li></ul></div>
      <div class="card"><h3>المواعيد</h3>${c.schedule.length ? c.schedule.map((s) => html`<div class="slot"><span>${DAYS[s.day]}</span>
        <span class="ltr">${s.start}–${s.end} · ${s.room}</span></div>`) : html`<${Empty} />`}
        ${teaches ? html`<div class="row" style="margin-top:1rem"><a class="btn small" href="#/attendance">بدء جلسة حضور</a>
          <a class="btn small secondary" href=${`#/grades/${c.id}`}>الدرجات</a></div>` : null}</div>
    </div>` : null}
    ${tab === "assignments" ? html`<div class="card"><${Async} state=${assignments}>${(list) => list.length ? html`<ul class="list">
      ${list.map((a) => html`<li><a class="item-link" href=${`#/assignments/${a.id}`}><strong>${a.title}</strong>
        <div class="small muted">التسليم: ${fmtDate(a.due_at)}</div></a></li>`)}</ul>` : html`<${Empty} />`}<//></div>` : null}
    ${tab === "students" ? html`<div class="card"><${Async} state=${students}>${(list) => html`<div class="table-wrap"><table>
      <thead><tr><th>الاسم</th><th>رقم القيد</th><th>الدفعة</th>${isAdmin(user) ? html`<th></th>` : null}</tr></thead>
      <tbody>${list.map((s) => html`<tr><td>${s.full_name}</td><td class="mono">${s.code}</td><td>${s.cohort || ""}</td>
        ${isAdmin(user) ? html`<td><button class="ghost small" onClick=${async () => {
          if (!confirm("سحب الطالب من المقرر؟")) return;
          await api.del(`/api/courses/${c.id}/enrollments/${s.id}`); students.reload(); }}>سحب</button></td>` : null}</tr>`)}</tbody>
      </table></div>`}<//></div>` : null}
    ${tab === "components" ? html`<${Components} course=${c} onChange=${state.reload} />` : null}
    ${tab === "manage" ? html`<div class="grid cols-2"><${EditCourse} course=${c} onChange=${state.reload} /><${Components} course=${c} onChange=${state.reload} /></div>
      <${StaffManager} course=${c} onChange=${() => { state.reload(); students.reload(); }} />` : null}
  </div>`}<//>`;
}
