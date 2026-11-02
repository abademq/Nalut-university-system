import { html, useAsync, Async, Empty, Chip, toast, toastError, fmtDate, ROLE } from "../ui.js";
import { api } from "../api.js";

const STATUS = { pending: ["قيد النظر", "warning"], approved: ["نُفّذ الحذف", "danger"], rejected: ["رُفض", ""] };

// Delete now when this account decides deletions; otherwise file a request to the administration.
export async function deleteAccount(target, onDone) {
  const reason = prompt(`حذف حساب «${target.full_name}» نهائياً مع كل بياناته (التسجيل والدرجات والحضور والرسائل والملفات). لا يمكن التراجع.\n\nاكتب السبب:`);
  if (!reason || reason.trim().length < 5) return;
  try {
    await api.post(`/api/users/${target.id}/delete`, { reason });
    toast("حُذف الحساب نهائياً", "success");
    onDone?.();
  } catch (e) {
    if (e.status !== 403) return toastError(e);
    if (!confirm("حذف هذا الحساب يحتاج موافقة الإدارة. إرسال طلب حذف لها؟")) return;
    await api.post(`/api/users/${target.id}/deletion-requests`, { reason })
      .then(() => toast("أُرسل طلب الحذف للإدارة", "success")).catch(toastError);
  }
}

export function DeletionsView() {
  const state = useAsync(() => api.get("/api/account-deletions"), []);
  const decide = async (r, approve) => {
    const note = approve ? "" : prompt("سبب الرفض (اختياري):") ?? null;
    if (note === null) return;
    if (approve && !confirm(`حذف حساب «${r.target.full_name}» نهائياً مع كل بياناته؟ لا يمكن التراجع.`)) return;
    await api.post(`/api/account-deletions/${r.id}`, { approve, note }).then(() => toast(approve ? "حُذف الحساب" : "رُفض الطلب")).catch(toastError);
    state.reload();
  };
  return html`<div><h1>طلبات حذف الحسابات</h1>
    <p class="muted">الحذف نهائي: يُزال الحساب وكل ما يخصه، ويبقى في سجل التدقيق اسمه ورقمه وسبب الحذف ومن طلبه ومن نفّذه.</p>
    <${Async} state=${state}>${(rows) => rows.length ? html`<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>الحساب</th><th>السبب</th><th>طلبه</th><th>الحالة</th><th></th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td><strong>${r.target.full_name}</strong>
          <div class="small muted">${ROLE[r.target.role] || r.target.role}${r.target.code ? ` · ${r.target.code}` : ""}</div></td>
        <td class="small">${r.reason}</td><td class="small">${r.requested_by || "—"}<div class="muted">${fmtDate(r.created_at)}</div></td>
        <td><${Chip} kind=${STATUS[r.status][1]}>${STATUS[r.status][0]}<//>
          ${r.decided_by ? html`<div class="small muted">${r.decided_by}${r.decision_note ? `: ${r.decision_note}` : ""}</div>` : null}</td>
        <td>${r.can_decide ? html`<div class="row"><button class="small danger" onClick=${() => decide(r, true)}>احذف</button>
          <button class="small secondary" onClick=${() => decide(r, false)}>ارفض</button></div>` : null}</td></tr>`)}</tbody></table></div></div>`
      : html`<${Empty}>لا توجد طلبات<//>`}<//></div>`;
}
