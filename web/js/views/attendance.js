import {
  html, useState, useEffect, useRef, useAsync, Async, Empty, Chip, StatusChip, ErrorBox, useForm, useSubmit,
  toast, toastError, Tabs, Modal, Kpi, Bar, ATT_STATUS, RISK_FLAG, fmtDate, pct, useCourses, navigate, Icon } from "../ui.js";
import { api, deviceId, blobUrl } from "../api.js";

const isAdmin = (u) => u.role === "university_admin" || u.role === "faculty_admin";
const isInstructor = (u) => u.role === "teacher" || u.role === "assistant";

function newNonce() {
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

function getPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
      () => resolve(null), { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
  });
}

// ------------------------------------------------------------------ camera helpers

function useCamera(facingMode, active) {
  const videoRef = useRef(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!active) return undefined;
    let stream;
    let cancelled = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("الكاميرا غير متاحة في هذا المتصفح (تتطلب اتصالاً آمناً HTTPS)");
      return undefined;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode, width: { ideal: 1280 } }, audio: false })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          videoRef.current.play().catch(() => {});
        }
      })
      .catch(() => setError("تعذر تشغيل الكاميرا. اسمح بالوصول إلى الكاميرا أو استخدم الرمز الرقمي."));
    return () => { cancelled = true; stream?.getTracks().forEach((t) => t.stop()); };
  }, [facingMode, active]);
  return [videoRef, error];
}

function QrScanner({ onCode }) {
  const [videoRef, error] = useCamera("environment", true);
  useEffect(() => {
    let stop = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const detector = "BarcodeDetector" in window ? new window.BarcodeDetector({ formats: ["qr_code"] }) : null;
    const tick = async () => {
      if (stop) return;
      const v = videoRef.current;
      if (v && v.readyState >= 2 && v.videoWidth) {
        try {
          let text = null;
          if (detector) {
            const codes = await detector.detect(v);
            text = codes[0]?.rawValue || null;
          } else if (window.jsQR) {
            const scale = Math.min(1, 640 / v.videoWidth);
            canvas.width = v.videoWidth * scale;
            canvas.height = v.videoHeight * scale;
            ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
            const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
            text = window.jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" })?.data || null;
          }
          if (text && text.startsWith("NUS1:")) {
            stop = true;
            onCode(text);
            return;
          }
        } catch { /* keep scanning */ }
      }
      setTimeout(tick, 200);
    };
    tick();
    return () => { stop = true; };
  }, []);
  return html`<div>
    ${error ? html`<div class="alert warning">${error}</div>` : html`<div class="scanner">
      <video ref=${videoRef} playsinline muted></video><div class="frame"></div></div>`}
  </div>`;
}

function SelfieCapture({ onCapture, onCancel }) {
  const [videoRef, error] = useCamera("user", true);
  const take = () => {
    const v = videoRef.current;
    if (!v?.videoWidth) return;
    const c = document.createElement("canvas");
    const scale = Math.min(1, 720 / v.videoWidth);
    c.width = v.videoWidth * scale;
    c.height = v.videoHeight * scale;
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    c.toBlob((b) => b && onCapture(b), "image/jpeg", 0.85);
  };
  // The picture comes straight from the live camera stream; gallery uploads are not offered.
  return html`<div class="stack">
    <div class="alert info">هذه الجلسة تتطلب صورة حية من الكاميرا الأمامية. تُحفظ مشفرة لمدة محدودة ولا يطّلع عليها إلا المسؤول عند المراجعة.</div>
    ${error ? html`<div class="alert warning">${error}</div>` : html`<div class="scanner selfie"><video ref=${videoRef} playsinline muted></video></div>`}
    <div class="row"><button class="big" onClick=${take} disabled=${!!error}><${Icon} name="camera" size=${18} />التقاط الصورة وإرسال الحضور</button></div>
    <button class="secondary" onClick=${onCancel}>إلغاء</button>
    <p class="small muted">إذا تعذر استخدام الكاميرا، تواصل مع أستاذ المقرر لتسجيل حضورك يدوياً مع ذكر السبب.</p>
  </div>`;
}

// ------------------------------------------------------------------ scan (students / staff)

export function ScanView() {
  const [stage, setStage] = useState("scan"); // scan | manual | selfie | sending | done
  const [pending, setPending] = useState(null); // {payload|short_code, session_id, req}
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [manual, bindManual] = useForm({ session_id: "", short_code: "" });

  const send = async (p, selfie) => {
    setStage("sending");
    setError(null);
    try {
      const fd = new FormData();
      if (p.payload) fd.append("payload", p.payload);
      else { fd.append("short_code", p.short_code); fd.append("session_id", p.session_id); }
      fd.append("nonce", newNonce());
      if (p.req.require_location || p.req.has_geofence) {
        const pos = await getPosition();
        if (pos) { fd.append("latitude", pos.latitude); fd.append("longitude", pos.longitude); }
        else if (p.req.require_location) throw new Error("هذه الجلسة تتطلب تفعيل الموقع (GPS) والسماح للمتصفح باستخدامه");
      }
      if (selfie) fd.append("selfie", selfie, "live.jpg");
      const r = await api.form("/api/attendance/check-in", fd, { "X-Device-Id": deviceId() });
      setResult(r);
      setStage("done");
      if (navigator.vibrate) navigator.vibrate(120);
    } catch (e) {
      setError(e);
      setStage("scan");
    }
  };

  const begin = async (p) => {
    try {
      const req = await api.get(`/api/attendance/sessions/${p.session_id}/requirements`);
      const full = { ...p, req };
      setPending(full);
      if (req.require_selfie) setStage("selfie");
      else send(full);
    } catch (e) {
      setError(e);
      setStage("scan");
    }
  };

  const onCode = (payload) => begin({ payload, session_id: payload.split(":")[1] });

  return html`<div style="max-width:480px;margin:0 auto">
    <h1>تسجيل الحضور</h1>
    <${ErrorBox} error=${error} />
    ${stage === "scan" ? html`<div class="card stack">
      <p class="muted">وجّه الكاميرا إلى رمز QR المعروض في القاعة. الرمز يتغير كل بضع ثوانٍ، لذا امسحه مباشرة من الشاشة.</p>
      <${QrScanner} onCode=${onCode} />
      <button class="secondary" onClick=${() => setStage("manual")}>إدخال الرمز الرقمي بدلاً من المسح</button></div>` : null}
    ${stage === "manual" ? html`<form class="card" onSubmit=${(e) => { e.preventDefault(); begin({ short_code: manual.short_code, session_id: manual.session_id }); }}>
      <div class="field"><label>رقم الجلسة</label><input inputmode="numeric" ...${bindManual("session_id")} required /></div>
      <div class="field"><label>الرمز الرقمي (6 أرقام)</label><input inputmode="numeric" maxlength="6" class="mono" ...${bindManual("short_code")} required /></div>
      <div class="row"><button>تسجيل</button><button type="button" class="secondary" onClick=${() => setStage("scan")}>العودة للمسح</button></div></form>` : null}
    ${stage === "selfie" ? html`<div class="card"><${SelfieCapture} onCapture=${(b) => send(pending, b)} onCancel=${() => setStage("scan")} /></div>` : null}
    ${stage === "sending" ? html`<div class="card empty">جارٍ التحقق على الخادم…</div>` : null}
    ${stage === "done" ? html`<div class="card" style="text-align:center">
      <div class="big-icon">${result.status === "pending_review" ? html`<${Icon} name="wait" size=${56} />` : html`<${Icon} name="ok" size=${56} />`}</div>
      <h2>${result.message}</h2><p class="muted">${result.session}</p>
      <p class="small">${fmtDate(result.check_out_at || result.check_in_at)}</p>
      ${result.status === "pending_review" ? html`<p class="small muted">بعض مؤشرات التحقق تحتاج مراجعة بشرية. لن يُتخذ أي إجراء بحقك دون مراجعة.</p>` : null}
      <a class="btn secondary" href="#/attendance">سجل حضوري</a></div>` : null}
  </div>`;
}

// ------------------------------------------------------------------ my attendance

function MyAttendance({ user }) {
  const state = useAsync(() => api.get("/api/me/attendance"), []);
  return html`<div>
    <a class="btn big" href="#/attendance/scan" style="margin-bottom:1rem;width:100%"><${Icon} name="camera" size=${18} />${user.role === "student" ? "مسح رمز الحضور" : "تسجيل الدخول / الانصراف"}</a>
    <${Async} state=${state}>${(d) => html`
      ${d.courses.length ? html`<div class="card"><h2>نسب الحضور</h2><div class="table-wrap"><table>
        <thead><tr><th>المقرر</th><th class="num">المحاضرات</th><th class="num">حضور</th><th class="num">تأخير</th><th class="num">غياب</th><th>نسبة الغياب</th></tr></thead>
        <tbody>${d.courses.map((c) => html`<tr><td>${c.course.title}</td><td class="num">${c.sessions}</td><td class="num">${c.present}</td>
          <td class="num">${c.late}</td><td class="num">${c.absent}</td>
          <td><div class="row"><div style="flex:1;min-width:80px"><${Bar} value=${c.absence_percent} warnAbove=${15} badAbove=${25} /></div>${pct(c.absence_percent)}</div></td></tr>`)}
        </tbody></table></div></div>` : null}
      <div class="card"><h2>السجل</h2>${d.records.length ? html`<ul class="list">${d.records.map((r) => html`<li class="row between">
        <span>${r.session}<div class="small muted">${fmtDate(r.starts_at)}${r.check_out_at ? ` · انصراف ${fmtDate(r.check_out_at)}` : ""}</div></span>
        <${StatusChip} map=${ATT_STATUS} value=${r.status} /></li>`)}</ul>` : html`<${Empty} />`}</div>`}<//>
  </div>`;
}

// ------------------------------------------------------------------ sessions (instructors / admins)

function CreateSession({ user, kind, onCreated }) {
  const courses = useCourses();
  const [v, bind, setV] = useForm({ course_id: "", title: "", location: "", risk_level: "normal", duration_minutes: "",
    geofence: false, latitude: "", longitude: "", radius_m: "" });
  const useHere = async () => {
    const p = await getPosition();
    if (!p) return toast("تعذر تحديد الموقع", "error");
    setV({ ...v, geofence: true, latitude: p.latitude.toFixed(6), longitude: p.longitude.toFixed(6) });
  };
  const [submit, busy, error] = useSubmit(async () => {
    const body = { kind, title: v.title || null, location: v.location || null, risk_level: v.risk_level,
      duration_minutes: v.duration_minutes ? Number(v.duration_minutes) : null };
    if (kind === "course") body.course_id = Number(v.course_id);
    if (v.geofence && v.latitude) Object.assign(body, { latitude: Number(v.latitude), longitude: Number(v.longitude), radius_m: v.radius_m ? Number(v.radius_m) : null });
    const s = await api.post("/api/attendance/sessions", body);
    onCreated(s);
  });
  return html`<form class="card" onSubmit=${submit}><h3>${kind === "course" ? "جلسة حضور جديدة" : "جلسة دوام للموظفين"}</h3><${ErrorBox} error=${error} />
    <div class="form-grid">
      ${kind === "course" ? html`<div class="field"><label>المقرر</label><select ...${bind("course_id")} required><option value="">اختر…</option>
        ${(courses.data || []).map((c) => html`<option value=${c.id}>${c.code} — ${c.title}</option>`)}</select></div>`
        : html`<div class="field"><label>العنوان</label><input ...${bind("title")} placeholder="دوام — المدخل الرئيسي" /></div>`}
      <div class="field"><label>المكان / القاعة</label><input ...${bind("location")} /></div>
      <div class="field"><label>المدة (دقيقة)</label><input type="number" min="5" max="960" placeholder="الافتراضي من إعدادات المؤسسة" ...${bind("duration_minutes")} /></div>
      <div class="field"><label>مستوى التحقق</label><select ...${bind("risk_level")}>
        <option value="normal">عادي — QR ديناميكي</option><option value="high">مرتفع (امتحان) — حسب إعدادات المؤسسة</option></select></div>
    </div>
    <label class="check"><input type="checkbox" ...${bind("geofence", "checkbox")} /> تحديد نطاق جغرافي للقاعة (إشارة مساعدة وليست دليلاً قاطعاً)</label>
    ${v.geofence || v.risk_level === "high" ? html`<div class="form-grid">
      <div class="field"><label>خط العرض</label><input class="ltr" ...${bind("latitude")} /></div>
      <div class="field"><label>خط الطول</label><input class="ltr" ...${bind("longitude")} /></div>
      <div class="field"><label>نصف القطر (م)</label><input type="number" min="20" placeholder="الافتراضي" ...${bind("radius_m")} /></div>
      <div class="field"><label> </label><button type="button" class="secondary" onClick=${useHere}><${Icon} name="pin_map" size=${18} />استخدام موقعي الحالي</button></div></div>` : null}
    <button disabled=${busy}>بدء الجلسة وعرض الرمز</button></form>`;
}

function SessionsList({ kindFilter }) {
  const state = useAsync(() => api.get("/api/attendance/sessions"), []);
  return html`<div class="card"><h3>الجلسات</h3><${Async} state=${state}>${(rows) => {
    const list = rows.filter((s) => !kindFilter || s.kind === kindFilter);
    return list.length ? html`<div class="table-wrap"><table><thead><tr><th>الجلسة</th><th>البداية</th><th>الحالة</th><th class="num">حضور</th><th class="num">غياب</th><th class="num">مراجعة</th></tr></thead>
    <tbody>${list.map((s) => html`<tr><td><a href=${`#/attendance/session/${s.id}`}>${s.title}</a>
      ${s.risk_level === "high" ? html` <${Chip} kind="warning">تحقق مرتفع<//>` : null}</td>
      <td class="small">${fmtDate(s.starts_at)}</td><td>${s.status === "open" ? html`<${Chip} kind="success">مفتوحة<//>` : html`<${Chip}>مغلقة<//>`}</td>
      <td class="num">${(s.counts.present || 0) + (s.counts.late || 0)}${s.expected ? `/${s.expected}` : ""}</td>
      <td class="num">${s.counts.absent || 0}</td><td class="num">${s.counts.pending_review || 0}</td></tr>`)}</tbody></table></div>` : html`<${Empty} />`;
  }}<//></div>`;
}

function SelfieModal({ recordId, onClose }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let u;
    blobUrl(`/api/attendance/records/${recordId}/selfie`).then((x) => { u = x; setUrl(x); }).catch(setErr);
    return () => u && URL.revokeObjectURL(u);
  }, [recordId]);
  return html`<${Modal} title="الصورة الحية" onClose=${onClose}>
    <${ErrorBox} error=${err} />${url ? html`<img class="selfie" src=${url} alt="صورة التحقق" />` : null}
    <p class="small muted">تم تسجيل اطلاعك على هذه الصورة في سجل التدقيق.</p><//>`;
}

function ReviewQueue() {
  const state = useAsync(() => api.get("/api/attendance/review-queue"), []);
  const [selfie, setSelfie] = useState(null);
  const decide = async (id, approve) => {
    const reason = prompt(approve ? "سبب القبول (مثلاً: تحقق الأستاذ من وجود الطالب):" : "سبب الرفض:");
    if (!reason || reason.trim().length < 3) return;
    try {
      await api.post(`/api/attendance/records/${id}/review`, { approve, reason });
      toast("تم حفظ القرار");
      state.reload();
    } catch (e) { toastError(e); }
  };
  return html`<div class="card"><h3>تسجيلات بانتظار المراجعة</h3>
    <p class="small muted">تُحال التسجيلات إلى هنا عند وجود مؤشرات غير معتادة. لا تُعد أي إشارة وحدها دليلاً على المخالفة.</p>
    <${Async} state=${state}>${(rows) => rows.length ? html`<ul class="list">${rows.map((q) => html`<li>
      <div class="row between"><strong>${q.user.full_name} <span class="small muted mono">${q.user.code}</span></strong>
        <span class="small muted">${q.session.title} · ${fmtDate(q.record.check_in_at)}</span></div>
      <div class="row">${q.record.risk_flags.map((f) => html`<${Chip} kind="warning">${RISK_FLAG[f] || f}<//>`)}
        ${q.record.distance_m !== null ? html`<span class="small muted">المسافة ${Math.round(q.record.distance_m)} م</span>` : null}</div>
      <div class="row" style="margin-top:.4rem"><button class="small" onClick=${() => decide(q.record.id, true)}>قبول</button>
        <button class="small danger" onClick=${() => decide(q.record.id, false)}>رفض</button>
        ${q.record.has_selfie ? html`<button class="small secondary" onClick=${() => setSelfie(q.record.id)}>عرض الصورة</button>` : null}</div>
    </li>`)}</ul>` : html`<${Empty}>لا توجد حالات للمراجعة<//>`}<//>
    ${selfie ? html`<${SelfieModal} recordId=${selfie} onClose=${() => setSelfie(null)} />` : null}</div>`;
}

function Anomalies() {
  const state = useAsync(() => api.get("/api/attendance/anomalies"), []);
  return html`<div class="card"><h3>أنماط غير معتادة (آخر 30 يوماً)</h3><${Async} state=${state}>${(a) => html`
    <div class="kpis"><${Kpi} label="بانتظار المراجعة" value=${a.pending_review} /><${Kpi} label="أجهزة مشتركة بين حسابات" value=${a.shared_devices.length} /></div>
    ${a.shared_devices.length ? html`<h4>أجهزة استُخدمت لأكثر من حساب</h4><ul class="list">${a.shared_devices.map((d) => html`<li>
      <span class="mono small">${d.device}</span> — ${d.users.map((u) => `${u.full_name} (${u.code})`).join("، ")}</li>`)}</ul>` : null}
    ${a.frequently_flagged.length ? html`<h4>تسجيلات تحمل مؤشرات متكررة</h4><ul class="list">${a.frequently_flagged.map((f) => html`<li class="row between">
      <span>${f.user.full_name} <span class="small muted mono">${f.user.code}</span></span><${Chip} kind="warning">${f.flagged_checkins} تسجيل<//></li>`)}</ul>` : null}
    ${!a.shared_devices.length && !a.frequently_flagged.length ? html`<${Empty}>لا توجد أنماط لافتة<//>` : null}`}<//></div>`;
}

function Integrity() {
  const [res, setRes] = useState(null);
  return html`<div class="card"><h3>سلامة سجلات الحضور</h3>
    <p class="small muted">كل سجل مرتبط بسابقه بسلسلة تجزئة، وكل تعديل يجب أن يكون له سجل تعديل بسببه. يكشف هذا الفحص أي تعديل صامت.</p>
    <button onClick=${() => api.get("/api/attendance/integrity").then(setRes).catch(toastError)}>تشغيل الفحص</button>
    ${res ? html`<div class=${`alert ${res.ok ? "success" : "error"}`} style="margin-top:.75rem">
      ${res.ok ? `السجلات سليمة (${res.checked} سجل)` : `تم اكتشاف ${res.problems.length} مشكلة في ${res.checked} سجل`}
      ${res.problems.length ? html`<ul>${res.problems.map((p) => html`<li>سجل #${p.record_id}: ${p.problem}</li>`)}</ul>` : null}</div>` : null}</div>`;
}

function ManagerAttendance({ user }) {
  const [tab, setTab] = useState("sessions");
  const tabs = [["sessions", "جلسات المقررات"], ["review", "المراجعة"], ["anomalies", "الأنماط"]];
  if (isAdmin(user)) tabs.splice(1, 0, ["staff", "دوام الموظفين"]);
  if (user.role === "university_admin") tabs.push(["integrity", "السلامة"]);
  const created = (s) => navigate(`#/attendance/display/${s.id}`);
  return html`<div>
    <${Tabs} value=${tab} onChange=${setTab} tabs=${tabs} />
    ${tab === "sessions" ? html`${isInstructor(user) || isAdmin(user) ? html`<${CreateSession} user=${user} kind="course" onCreated=${created} />` : null}
      <${SessionsList} kindFilter="course" />` : null}
    ${tab === "staff" ? html`<${CreateSession} user=${user} kind="staff" onCreated=${created} /><${SessionsList} kindFilter="staff" />` : null}
    ${tab === "review" ? html`<${ReviewQueue} />` : null}
    ${tab === "anomalies" ? html`<${Anomalies} />` : null}
    ${tab === "integrity" ? html`<${Integrity} />` : null}
  </div>`;
}

export function AttendanceView({ user }) {
  const manager = isInstructor(user) || isAdmin(user);
  const [mine, setMine] = useState(!manager);
  return html`<div>
    <div class="row between"><h1>الحضور والانصراف</h1>
      ${manager && user.role !== "student" ? html`<button class="secondary small" onClick=${() => setMine(!mine)}>${mine ? "إدارة الجلسات" : "حضوري الشخصي"}</button>` : null}</div>
    ${mine ? html`<${MyAttendance} user=${user} />` : html`<${ManagerAttendance} user=${user} />`}
  </div>`;
}

function HistoryModal({ recordId, onClose }) {
  const state = useAsync(() => api.get(`/api/attendance/records/${recordId}/history`), [recordId]);
  return html`<${Modal} title="سجل التعديلات" onClose=${onClose}><${Async} state=${state}>${(rows) => rows.length ? html`<ul class="list">
    ${rows.map((r) => html`<li><strong>${ATT_STATUS[r.old]?.[0] || "—"} ← ${ATT_STATUS[r.new]?.[0]}</strong>
      <div class="small">${r.reason}</div><div class="small muted">${r.actor} · ${fmtDate(r.created_at)}</div></li>`)}</ul>` : html`<${Empty}>لا توجد تعديلات<//>`}<//><//>`;
}

export function SessionView({ id }) {
  const state = useAsync(() => api.get(`/api/attendance/sessions/${id}`), [id]);
  const [history, setHistory] = useState(null);
  const [selfie, setSelfie] = useState(null);
  const mark = async (userId, status) => {
    const reason = prompt("سبب التسجيل أو التعديل اليدوي:");
    if (!reason || reason.trim().length < 3) return;
    try {
      await api.post(`/api/attendance/sessions/${id}/manual`, { user_id: userId, status, reason });
      toast("تم التحديث");
      state.reload();
    } catch (e) { toastError(e); }
  };
  const close = async () => {
    if (!confirm("إغلاق الجلسة؟ سيُسجَّل غياب من لم يسجل حضوره.")) return;
    await api.post(`/api/attendance/sessions/${id}/close`).catch(toastError);
    state.reload();
  };
  return html`<${Async} state=${state}>${(s) => html`<div>
    <div class="row between"><h1>${s.title}</h1>
      <div class="row">${s.status === "open" ? html`<a class="btn" href=${`#/attendance/display/${s.id}`}>عرض رمز QR</a>
        <button class="secondary" onClick=${close}>إغلاق الجلسة</button>` : html`<${Chip}>مغلقة<//>`}</div></div>
    <p class="muted">${fmtDate(s.starts_at)} — ${fmtDate(s.ends_at)} ${s.location ? `· ${s.location}` : ""}
      ${s.require_selfie ? " · صورة حية" : ""}${s.require_location ? " · موقع" : ""}</p>
    <div class="kpis">${Object.entries(ATT_STATUS).map(([k, [l]]) => html`<${Kpi} label=${l} value=${s.counts[k] || 0} />`)}</div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>الاسم</th><th>الحالة</th><th>الوقت</th><th>مؤشرات</th><th>تسجيل يدوي</th></tr></thead>
      <tbody>${s.people.map((p) => html`<tr>
        <td>${p.user.full_name}<div class="small muted mono">${p.user.code || ""}</div></td>
        <td>${p.record ? html`<${StatusChip} map=${ATT_STATUS} value=${p.record.status} />` : html`<${Chip}>لم يسجل<//>`}
          ${p.record?.method === "manual" ? html` <span class="small muted">يدوي</span>` : null}</td>
        <td class="small">${p.record?.check_in_at ? fmtDate(p.record.check_in_at) : "—"}</td>
        <td>${(p.record?.risk_flags || []).map((f) => html`<${Chip} kind="warning">${RISK_FLAG[f] || f}<//> `)}
          ${p.record?.has_selfie ? html`<button class="ghost small" onClick=${() => setSelfie(p.record.id)}>الصورة</button>` : null}
          ${p.record ? html`<button class="ghost small" onClick=${() => setHistory(p.record.id)}>السجل</button>` : null}</td>
        <td><select aria-label="تسجيل يدوي" onChange=${(e) => { const v = e.target.value; e.target.value = ""; if (v) mark(p.user.id, v); }}>
          <option value="">—</option><option value="present">حاضر</option><option value="late">متأخر</option>
          <option value="excused">بعذر</option><option value="absent">غائب</option></select></td>
      </tr>`)}</tbody></table></div></div>
    ${history ? html`<${HistoryModal} recordId=${history} onClose=${() => setHistory(null)} />` : null}
    ${selfie ? html`<${SelfieModal} recordId=${selfie} onClose=${() => setSelfie(null)} />` : null}
  </div>`}<//>`;
}

export function DisplayView({ id }) {
  const [qr, setQr] = useState(null);
  const [error, setError] = useState(null);
  const [left, setLeft] = useState(0);
  useEffect(() => {
    let timer;
    let stop = false;
    const load = async () => {
      try {
        const d = await api.get(`/api/attendance/sessions/${id}/qr`);
        if (stop) return;
        setQr(d);
        setError(null);
        // fetch the next code just after this one rotates
        timer = setTimeout(load, Math.max(1000, d.expires_in * 1000 + 300));
      } catch (e) {
        setError(e);
        timer = setTimeout(load, 5000);
      }
    };
    load();
    return () => { stop = true; clearTimeout(timer); };
  }, [id]);
  useEffect(() => {
    if (!qr) return undefined;
    const started = Date.now();
    const t = setInterval(() => setLeft(Math.max(0, qr.expires_in - (Date.now() - started) / 1000)), 250);
    return () => clearInterval(t);
  }, [qr]);
  return html`<div class="qr-stage">
    <div class="row" style="width:100%;justify-content:space-between">
      <a class="btn secondary small" href=${`#/attendance/session/${id}`}>← تفاصيل الجلسة</a>
      ${qr ? html`<${Chip} kind="success">سجّل ${qr.present} حتى الآن<//>` : null}</div>
    <${ErrorBox} error=${error} />
    ${qr ? html`
      <h2>امسح الرمز بتطبيق المنصة لتسجيل الحضور</h2>
      <img src=${qr.image} alt="رمز QR للحضور" />
      <div class="countdown"><span style=${`width:${(left / qr.rotation_seconds) * 100}%`}></span></div>
      <div class="muted">يتجدد الرمز كل ${qr.rotation_seconds} ثانية — صور الرمز القديمة لا تُقبل</div>
      <div>رقم الجلسة <strong class="mono">${id}</strong> · الرمز الرقمي <span class="qr-code mono">${qr.short_code}</span></div>` : html`<p>جارٍ التحميل…</p>`}
  </div>`;
}
