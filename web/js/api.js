// API client. The access token is kept in memory only; the refresh token lives in an
// HttpOnly cookie that JavaScript cannot read.

let accessToken = null;
let onLogout = () => {};

// Platform administrator managing a university: every request carries its id (per tab).
let acting = null;
try { acting = sessionStorage.getItem("nus-acting"); } catch { /* storage unavailable */ }
export function getActing() { return acting; }
export function setActing(id) {
  acting = id ? String(id) : null;
  try { if (acting) sessionStorage.setItem("nus-acting", acting); else sessionStorage.removeItem("nus-acting"); } catch { /* ignore */ }
  window.dispatchEvent(new Event("nus:acting"));
}

export function setToken(token) { accessToken = token; }
export function hasToken() { return !!accessToken; }
export function setLogoutHandler(fn) { onLogout = fn; }

export class ApiError extends Error {
  constructor(status, message, body) { super(message); this.status = status; this.body = body; }
}

async function refresh() {
  const res = await fetch("/api/auth/refresh", {
    method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "nus-web" },
  });
  if (!res.ok) return null;
  const data = await res.json();
  accessToken = data.access_token;
  return data;
}

let refreshing = null;
export function tryRefresh() {
  refreshing = refreshing || refresh().finally(() => { refreshing = null; });
  return refreshing;
}

function errorMessage(body, status) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && Array.isArray(body.detail)) return "بيانات غير صالحة: " + body.detail.map((d) => d.loc?.slice(-1)[0]).join("، ");
  if (status === 429) return "محاولات كثيرة، حاول بعد قليل";
  return "تعذر إتمام الطلب";
}

export async function request(method, path, { json, form, raw = false, retry = true, headers = {} } = {}) {
  const opts = { method, headers: { ...headers }, credentials: "same-origin" };
  if (accessToken) opts.headers.Authorization = `Bearer ${accessToken}`;
  if (acting) opts.headers["X-Act-As-University"] = acting;
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  // a weak or dropped connection must not leave the page waiting forever
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), form ? 180000 : 40000);
  opts.signal = ctrl.signal;
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    // a change that timed out may still have reached the server: say so before a retry
    const sent = method !== "GET";
    if (e?.name === "AbortError") {
      throw new ApiError(0, sent ? "الشبكة بطيئة جداً ولم يصل الرد. تحقق هل تم الإجراء قبل إعادة المحاولة"
        : "الشبكة بطيئة جداً، حاول مرة أخرى");
    }
    throw new ApiError(0, sent ? "انقطع الاتصال. تحقق هل تم الإجراء قبل إعادة المحاولة" : "تعذر الاتصال بالخادم، تحقق من الشبكة");
  } finally {
    clearTimeout(timer);
  }
  // the server's clock, so relative times are right even when this device's clock is not
  const date = Date.parse(res.headers.get("date") || "");
  if (!Number.isNaN(date)) window.__nusClockSkew = date - Date.now();
  if (res.status === 401 && retry && !path.startsWith("/api/auth/")) {
    if (await tryRefresh()) return request(method, path, { json, form, raw, retry: false, headers });
    onLogout();
  }
  if (raw) {
    if (!res.ok) throw new ApiError(res.status, errorMessage(await res.json().catch(() => null), res.status));
    return res;
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status), body);
  return body;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, json) => request("POST", p, { json: json ?? {} }),
  put: (p, json) => request("PUT", p, { json }),
  patch: (p, json) => request("PATCH", p, { json }),
  del: (p) => request("DELETE", p),
  form: (p, form, headers) => request("POST", p, { form, headers }),
};

export async function downloadFile(fileId, name) {
  const res = await request("GET", `/api/files/${fileId}`, { raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name || "file";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export async function blobUrl(path) {
  const res = await request("GET", path, { raw: true });
  return URL.createObjectURL(await res.blob());
}

// Random per-install identifier (not a hardware id). Used only as a risk signal for check-ins.
export function deviceId() {
  try {
    let id = localStorage.getItem("nus-device-id");
    if (!id) {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      id = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem("nus-device-id", id);
    }
    return id;
  } catch {
    return "";
  }
}
