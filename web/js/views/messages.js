import { html, useState, useEffect, useRef, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, ROLE, fmtRelative, fmtDate, navigate } from "../ui.js";
import { api, downloadFile } from "../api.js";

function NewConversation({ params, onClose }) {
  const contacts = useAsync(() => api.get("/api/contacts"), []);
  const [v, bind, setV] = useForm({ to: params?.get("to") || "", subject: "", body: "", course: params?.get("course") || "" });
  const [submit, busy, error] = useSubmit(async () => {
    const r = await api.post("/api/conversations", { recipient_ids: [Number(v.to)], subject: v.subject, body: v.body,
      course_id: v.course ? Number(v.course) : null });
    navigate(`#/messages/${r.id}`);
  });
  const person = (contacts.data || []).find((c) => String(c.id) === String(v.to));
  return html`<form class="card" onSubmit=${submit}><div class="card-head"><h3>محادثة جديدة</h3>
    <button type="button" class="ghost" onClick=${onClose}>✕</button></div><${ErrorBox} error=${error} />
    <div class="field"><label>إلى</label><select ...${bind("to")} required onChange=${(e) => {
      const c = (contacts.data || []).find((x) => String(x.id) === e.target.value);
      setV({ ...v, to: e.target.value, course: c?.course_ids?.[0] || "" });
    }}><option value="">اختر…</option>
      ${(contacts.data || []).map((c) => html`<option value=${c.id}>${c.full_name} — ${ROLE[c.role]}</option>`)}</select>
      <p class="small muted">تظهر هنا الجهات المسموح بمراسلتها وفق سياسة المؤسسة.</p></div>
    ${person?.course_ids?.length > 1 ? html`<p class="small muted">مرتبطة بأكثر من مقرر؛ ستُربط المحادثة بالأول.</p>` : null}
    <div class="field"><label>الموضوع</label><input ...${bind("subject")} required /></div>
    <div class="field"><label>الرسالة</label><textarea ...${bind("body")} required></textarea></div>
    <button disabled=${busy}>إرسال</button></form>`;
}

export function MessagesView({ params }) {
  const state = useAsync(() => api.get("/api/conversations"), []);
  const [creating, setCreating] = useState(!!params?.get("to"));
  return html`<div>
    <div class="row between"><h1>الرسائل</h1><button onClick=${() => setCreating(!creating)}>+ محادثة جديدة</button></div>
    ${creating ? html`<${NewConversation} params=${params} onClose=${() => setCreating(false)} />` : null}
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><ul class="list">${rows.map((c) => html`<li>
      <a class="item-link" href=${`#/messages/${c.id}`}><div class="row between"><strong>${c.subject}</strong>
        <span class="row">${c.unread ? html`<${Chip} kind="danger">${c.unread} جديدة<//>` : null}<span class="small muted">${fmtRelative(c.last_message_at)}</span></span></div>
        <div class="small muted">${c.participants.map((p) => `${p.full_name} (${ROLE[p.role]})`).join("، ")}</div></a></li>`)}</ul></div>`
      : html`<${Empty}>لا توجد محادثات<//>`}<//>
  </div>`;
}

export function ThreadView({ id }) {
  const state = useAsync(() => api.get(`/api/conversations/${id}/messages`), [id]);
  const [body, setBody] = useState("");
  const [file, setFile] = useState(null);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); window.dispatchEvent(new Event("nus:notifications")); }, [state.data]);
  useEffect(() => { const t = setInterval(state.reload, 15000); return () => clearInterval(t); }, [id]);
  const [send, busy, error] = useSubmit(async () => {
    const fd = new FormData();
    fd.append("body", body);
    if (file) fd.append("upload", file);
    await api.form(`/api/conversations/${id}/messages`, fd);
    setBody("");
    setFile(null);
    state.reload();
  });
  const report = async (m) => {
    const reason = prompt("سبب الإبلاغ عن هذه الرسالة:");
    if (!reason || reason.trim().length < 3) return;
    await api.post(`/api/messages/${m.id}/report`, { reason }).then(() => toast("تم إرسال البلاغ للإدارة")).catch(toastError);
  };
  return html`<${Async} state=${state}>${(c) => html`<div>
    <div class="row"><a href="#/messages">← الرسائل</a></div><h1>${c.subject}</h1>
    <div class="card"><div class="thread">${c.messages.map((m) => html`<div class=${`bubble ${m.mine ? "mine" : ""}`}>
      <div class="meta">${m.sender} · ${fmtDate(m.created_at)}</div>
      <div style="white-space:pre-wrap">${m.body}</div>
      ${m.file ? html`<button class="ghost small" onClick=${() => downloadFile(m.file.id, m.file.name).catch(toastError)}>📎 ${m.file.name}</button>` : null}
      ${!m.mine ? html`<button class="ghost small" onClick=${() => report(m)} title="إبلاغ">⚑ إبلاغ</button>` : null}
    </div>`)}<div ref=${end}></div></div></div>
    <form class="card" onSubmit=${send}><${ErrorBox} error=${error} />
      <div class="field"><textarea placeholder="اكتب رسالتك…" value=${body} onInput=${(e) => setBody(e.target.value)} required></textarea></div>
      <div class="row"><input type="file" style="max-width:260px" onChange=${(e) => setFile(e.target.files[0] || null)} />
        <span class="spacer"></span><button disabled=${busy}>إرسال</button></div></form>
  </div>`}<//>`;
}
