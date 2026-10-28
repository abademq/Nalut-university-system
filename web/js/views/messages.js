import { html, useState, useEffect, useRef, useAsync, Async, Empty, Chip, ErrorBox, useForm, useSubmit, toast, toastError, ROLE, fmtRelative, fmtDate, navigate, Icon } from "../ui.js";
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
    <button type="button" class="ghost" onClick=${onClose}aria-label="إغلاق"><${Icon} name="close" size=${18} /></button></div><${ErrorBox} error=${error} />
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
    <p class="small muted">يمكن لإدارة الجامعة الاطلاع على المحادثات لأغراض الرقابة، ويُسجَّل كل اطلاع باسم من قام به.</p>
    ${creating ? html`<${NewConversation} params=${params} onClose=${() => setCreating(false)} />` : null}
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><ul class="list">${rows.map((c) => html`<li>
      <a class="item-link" href=${`#/messages/${c.id}`}><div class="row between"><strong>${c.subject}</strong>
        <span class="row">${c.unread ? html`<${Chip} kind="danger">${c.unread} جديدة<//>` : null}<span class="small muted">${fmtRelative(c.last_message_at, true)}</span></span></div>
        <div class="small muted">${c.participants.map((p) => `${p.full_name} (${ROLE[p.role]})`).join("، ")}</div></a></li>`)}</ul></div>`
      : html`<${Empty}>لا توجد محادثات<//>`}<//>
  </div>`;
}

export function ThreadView({ id }) {
  const state = useAsync(() => api.get(`/api/conversations/${id}/messages`), [id]);
  const [body, setBody] = useState("");
  const [file, setFile] = useState(null);
  const [pick, setPick] = useState(0);  // remounts the file input to clear it after sending
  const end = useRef(null);
  const [fresh, setFresh] = useState([]); // messages that arrived after the page loaded
  useEffect(() => setFresh([]), [state.data]);
  const all = state.data ? [...state.data.messages, ...fresh] : [];
  const lastId = all.length ? all[all.length - 1].id : 0;
  const last = useRef(0);
  last.current = lastId;
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); window.dispatchEvent(new Event("nus:notifications")); }, [lastId]);
  // live: every few seconds ask only for what is newer (small on weak networks), paused while the
  // page is hidden
  const poll = async () => {
    if (document.hidden || !last.current) return;
    try {
      const r = await api.get(`/api/conversations/${id}/messages?after=${last.current}`);
      const got = r.messages.filter((m) => m.id > last.current);
      if (got.length) setFresh((f) => [...f, ...got.filter((m) => !f.some((x) => x.id === m.id))]);
    } catch { /* a missed poll is retried on the next tick */ }
  };
  useEffect(() => {
    const t = setInterval(poll, 4000);
    const back = () => { if (!document.hidden) poll(); };
    document.addEventListener("visibilitychange", back);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", back); };
  }, [id]);
  const [send, busy, error] = useSubmit(async () => {
    if (!body.trim() && !file) throw new Error("اكتب رسالة أو أرفق ملفاً");
    const fd = new FormData();
    fd.append("body", body);
    if (file) fd.append("upload", file);
    await api.form(`/api/conversations/${id}/messages`, fd);
    setBody("");
    setFile(null);
    setPick(pick + 1);
    await poll();
  });
  const report = async (m) => {
    const reason = prompt("سبب الإبلاغ عن هذه الرسالة:");
    if (!reason || reason.trim().length < 3) return;
    await api.post(`/api/messages/${m.id}/report`, { reason }).then(() => toast("تم إرسال البلاغ للإدارة")).catch(toastError);
  };
  return html`<${Async} state=${state}>${(c) => html`<div>
    <div class="row"><a href="#/messages">← الرسائل</a></div><h1>${c.subject}</h1>
    <div class="card"><div class="thread">${all.map((m) => html`<div class=${`bubble ${m.mine ? "mine" : ""}`}>
      <div class="meta">${m.sender} · ${fmtDate(m.created_at)}</div>
      ${m.body ? html`<div style="white-space:pre-wrap">${m.body}</div>` : null}
      ${m.file ? html`<button class="secondary small" style="margin-top:.35rem" title="تنزيل الملف"
        onClick=${() => downloadFile(m.file.id, m.file.name).catch(toastError)}><${Icon} name="download" size=${16} /> تنزيل ${m.file.name}</button>` : null}
      ${!m.mine ? html`<button class="ghost small" onClick=${() => report(m)} title="إبلاغ"><${Icon} name="flag" size=${16} /> إبلاغ</button>` : null}
    </div>`)}<div ref=${end}></div></div></div>
    <form class="card" onSubmit=${send}><${ErrorBox} error=${error} />
      <div class="field"><textarea placeholder="اكتب رسالتك… (أو أرفق ملفاً فقط)" value=${body} onInput=${(e) => setBody(e.target.value)}></textarea></div>
      <div class="row"><input key=${pick} type="file" style="max-width:260px" accept=".pdf,.doc,.docx,.pptx,.xlsx,.txt,.png,.jpg,.jpeg,.zip"
        onChange=${(e) => setFile(e.target.files[0] || null)} />
        <span class="spacer"></span><button disabled=${busy}>إرسال</button></div></form>
  </div>`}<//>`;
}

// ---------------------------------------------------------------- oversight (university administration)

export function OversightView() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const state = useAsync(() => api.get(`/api/oversight/conversations?limit=100&q=${encodeURIComponent(query)}`), [query]);
  return html`<div><h1>رقابة الرسائل</h1>
    <p class="muted">كل محادثات المنصة. فتح أي محادثة يُسجَّل في سجل التدقيق باسمك، ويُبلَّغ المستخدمون في صفحة الرسائل بأن الإدارة قد تطّلع عليها.</p>
    <form class="row" style="margin-bottom:.75rem" onSubmit=${(e) => { e.preventDefault(); setQuery(q); }}>
      <input style="max-width:340px" placeholder="بحث في الموضوع أو نص الرسائل أو اسم مشارك" value=${q} onInput=${(e) => setQ(e.target.value)} />
      <button class="secondary"><${Icon} name="search" size=${18} /> بحث</button></form>
    <${Async} state=${state}>${(d) => d.items.length ? html`<div class="card"><p class="small muted">${d.total} محادثة</p><ul class="list">${d.items.map((c) => html`<li>
      <a class="item-link" href=${`#/oversight/${c.id}`}><div class="row between"><strong>${c.subject}</strong>
        <span class="small muted">${c.messages} رسالة · ${fmtRelative(c.last_message_at, true)}</span></div>
        <div class="small muted">${c.participants.map((p) => `${p.full_name} (${ROLE[p.role]})`).join("، ")}</div>
        ${c.last ? html`<div class="small">${c.last}</div>` : null}</a></li>`)}</ul></div>`
      : html`<${Empty}>لا توجد محادثات<//>`}<//>
  </div>`;
}

export function OversightThread({ id }) {
  const state = useAsync(() => api.get(`/api/oversight/conversations/${id}`), [id]);
  return html`<${Async} state=${state}>${(c) => html`<div>
    <div class="row"><a href="#/oversight">← رقابة الرسائل</a></div>
    <h1>${c.subject}</h1>
    <p class="muted">${c.participants.map((p) => `${p.full_name} (${ROLE[p.role]})`).join("، ")}</p>
    <div class="alert info">تم تسجيل اطلاعك على هذه المحادثة في سجل التدقيق.</div>
    <div class="card"><div class="thread" style="max-height:none">${c.messages.map((m) => html`<div class="bubble">
      <div class="meta"><strong>${m.sender}</strong> · ${fmtDate(m.created_at)}${m.hidden ? html` · <${Chip} kind="danger">مخفية بعد بلاغ<//>` : null}</div>
      ${m.body ? html`<div style="white-space:pre-wrap">${m.body}</div>` : null}
      ${m.file ? html`<button class="secondary small" style="margin-top:.35rem" onClick=${() => downloadFile(m.file.id, m.file.name).catch(toastError)}>
        <${Icon} name="download" size=${16} /> تنزيل ${m.file.name}</button>` : null}</div>`)}</div></div>
  </div>`}<//>`;
}
