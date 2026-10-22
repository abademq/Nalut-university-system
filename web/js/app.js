import { html, render, useState, useEffect, ROLE, toastError } from "./ui.js";
import { api, setToken, setLogoutHandler, tryRefresh, getActing, setActing } from "./api.js";
import { Login } from "./views/login.js";
import { Home } from "./views/home.js";
import { CoursesView, CourseDetail } from "./views/courses.js";
import { AssignmentsView, AssignmentDetail } from "./views/assignments.js";
import { GradesView, ResultsApproval } from "./views/grades.js";
import { AttendanceView, ScanView, SessionView, DisplayView } from "./views/attendance.js";
import { NotificationsView, SendNotification } from "./views/notifications.js";
import { MessagesView, ThreadView } from "./views/messages.js";
import { RequestsView, RequestDetail } from "./views/requests.js";
import { UsersView, StructureView, SettingsView, LaunchView, AuditView, AbuseReportsView, UniversitiesView, PermissionsView } from "./views/admin.js";
import { ReportsView } from "./views/reports.js";
import { ProfileView } from "./views/profile.js";
import { BannerStrip, BannersView, ArchiveView, ArchiveDetail } from "./views/manage.js";
import { GuideView } from "./views/guide.js";
import { PublicationsView } from "./views/publications.js";

const isAdmin = (r) => r === "university_admin" || r === "faculty_admin";
const isInstructor = (r) => r === "teacher" || r === "assistant";
// a configurable capability (see the permissions page); university admins hold all of them
const can = (u, key) => u.role === "university_admin" || (u.can || []).includes(key);

// [hash, label, icon, roles predicate, mobile tab?]
const NAV = [
  ["#/", "الرئيسية", "⌂", () => true, true],
  ["#/universities", "الجامعات", "🏛", (r) => r === "platform_admin", true],
  ["#/courses", "المقررات", "📚", (r) => r !== "staff" && r !== "platform_admin", false],
  ["#/assignments", "المهام والواجبات", "📝", (r) => r === "student" || isInstructor(r), true],
  ["#/grades", "الدرجات", "🎓", (r) => r === "student" || isInstructor(r), false],
  ["#/results", "اعتماد النتائج", "✅", (r, u) => isAdmin(r) && can(u, "results.approve"), false],
  ["#/attendance", "الحضور", "📷", (r) => r !== "platform_admin", true],
  ["#/notifications", "الإشعارات", "🔔", (r) => r !== "platform_admin", true],
  ["#/publications", "الجداول والإعلانات المصورة", "🗓", (r) => r !== "platform_admin", false],
  ["#/messages", "الرسائل", "💬", (r) => r !== "platform_admin", false],
  ["#/requests", "الطلبات والمعاملات", "📄", (r) => r !== "platform_admin", false],
  ["#/reports", "التقارير", "📊", (r, u) => (isAdmin(r) || isInstructor(r)) && can(u, "reports.view"), false],
  ["#/users", "المستخدمون", "👥", (r) => isAdmin(r), false],
  ["#/structure", "الهيكل التنظيمي", "🏢", isAdmin, false],
  ["#/banners", "الإعلانات المثبتة", "📌", (r, u) => (isAdmin(r) || r === "staff") && can(u, "banners.manage"), false],
  ["#/archive", "أرشيف الطلبة", "🗂", (r, u) => (isAdmin(r) || (r === "staff" && u.office)) && can(u, "archive.access")
    && (r !== "staff" || (u.archive_offices || ["registrar"]).includes(u.office)), false],
  ["#/abuse", "بلاغات الرسائل", "⚑", (r, u) => isAdmin(r) && can(u, "messages.moderate"), false],
  ["#/audit", "سجل التدقيق", "🛡", (r, u) => r === "platform_admin" || (isAdmin(r) && can(u, "audit.view")), false],
  ["#/settings", "إعدادات المؤسسة", "⚙", (r) => r === "university_admin", false],
  ["#/permissions", "الصلاحيات", "🔑", (r) => r === "university_admin", false],
  ["#/launch", "شاشة البداية والنغمات", "📱", (r, u) => !!u.acting, false],
  ["#/profile", "حسابي", "👤", () => true, true],
  ["#/guide", "دليل الاستخدام", "❓", () => true, false],
];

function route(hash, user) {
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(query);
  const parts = (path.replace(/^#\/?/, "") || "").split("/").filter(Boolean);
  const [a, b, c] = parts;
  switch (a) {
    case undefined: return html`<${Home} user=${user} />`;
    case "courses": return b ? html`<${CourseDetail} id=${b} user=${user} />` : html`<${CoursesView} user=${user} />`;
    case "assignments": return b ? html`<${AssignmentDetail} id=${b} user=${user} />` : html`<${AssignmentsView} user=${user} />`;
    case "grades": return html`<${GradesView} user=${user} courseId=${b} />`;
    case "results": return html`<${ResultsApproval} user=${user} />`;
    case "attendance":
      if (b === "scan") return html`<${ScanView} user=${user} />`;
      if (b === "session") return html`<${SessionView} id=${c} user=${user} />`;
      if (b === "display") return html`<${DisplayView} id=${c} user=${user} />`;
      return html`<${AttendanceView} user=${user} />`;
    case "notifications": return b === "send" ? html`<${SendNotification} user=${user} />` : html`<${NotificationsView} user=${user} />`;
    case "messages": return b ? html`<${ThreadView} id=${b} user=${user} />` : html`<${MessagesView} user=${user} params=${params} />`;
    case "requests": return b ? html`<${RequestDetail} id=${b} user=${user} />` : html`<${RequestsView} user=${user} />`;
    case "reports": return html`<${ReportsView} user=${user} />`;
    case "users": return html`<${UsersView} user=${user} />`;
    case "structure": return html`<${StructureView} user=${user} />`;
    case "settings": return html`<${SettingsView} user=${user} />`;
    case "audit": return html`<${AuditView} user=${user} />`;
    case "abuse": return html`<${AbuseReportsView} user=${user} />`;
    case "universities": return html`<${UniversitiesView} user=${user} />`;
    case "profile": return html`<${ProfileView} user=${user} />`;
    case "banners": return html`<${BannersView} user=${user} />`;
    case "archive": return b ? html`<${ArchiveDetail} id=${b} user=${user} />` : html`<${ArchiveView} user=${user} />`;
    case "guide": return html`<${GuideView} user=${user} />`;
    case "publications": return html`<${PublicationsView} user=${user} id=${b} />`;
    case "permissions": return html`<${PermissionsView} user=${user} />`;
    case "launch": return html`<${LaunchView} user=${user} />`;
    default: return html`<div class="card empty">الصفحة غير موجودة</div>`;
  }
}

function useHash() {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const on = () => { setHash(location.hash || "#/"); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function Shell({ user, onLogout }) {
  const hash = useHash();
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    if (user.role === "platform_admin") return undefined;
    const poll = () => api.get("/api/notifications?limit=1").then((d) => setUnread(d.unread)).catch(() => {});
    poll();
    const t = setInterval(poll, 30000);
    window.addEventListener("nus:notifications", poll);
    return () => { clearInterval(t); window.removeEventListener("nus:notifications", poll); };
  }, [user.id]);

  const items = NAV.filter(([, , , allowed]) => allowed(user.role, user));
  const active = (h) => (h === "#/" ? hash === "#/" || hash === "" : hash.startsWith(h));
  const brand = user.branding?.display_name || user.university?.name || "منصة الجامعة";
  const fullscreen = hash.startsWith("#/attendance/display/");

  if (fullscreen) return html`<div class="fullscreen">${route(hash, user)}</div>`;

  return html`<div class="layout">
    <aside class="sidebar">
      <div class="brand"><img src="/static/icon.svg" alt="" /><div>${brand}<small>${ROLE[user.role]}</small></div></div>
      <nav class="nav">${items.map(([h, label, icon]) => html`
        <a href=${h} class=${active(h) ? "active" : ""}><span>${icon} ${label}</span>
          ${h === "#/notifications" && unread ? html`<span class="count">${unread}</span>` : null}</a>`)}
        <a href="#/" onClick=${(e) => { e.preventDefault(); onLogout(); }}><span>⎋ تسجيل الخروج</span></a>
      </nav>
    </aside>
    <main class="main">
      <div class="topbar">
        <div><strong>${user.full_name}</strong><div class="who">${ROLE[user.role]}${user.faculty ? ` — ${user.faculty.name}` : ""}</div></div>
        <div class="row only-mobile"><a class="btn secondary small" href="#/messages">💬</a></div>
      </div>
      ${user.acting ? html`<div class="alert info row between"><span>🛡 أنت مشرف المنصة وتدير «${user.university?.name}» بصلاحيات إدارتها الكاملة. كل إجراء يُسجَّل باسمك.</span>
        <button class="small secondary" onClick=${() => { setActing(null); location.hash = "#/universities"; }}>العودة لإدارة المنصة</button></div>` : null}
      ${user.must_change_password ? html`<div class="alert warning">تستخدم كلمة مرور مؤقتة. <a href="#/profile">غيّرها الآن</a>.</div>` : null}
      ${user.role !== "platform_admin" ? html`<${BannerStrip} key=${hash.split("/")[1] || "home"} />` : null}
      ${route(hash, user)}
    </main>
    <nav class="bottom-nav">${items.filter((i) => i[4]).slice(0, 5).map(([h, label, icon]) => html`
      <a href=${h} class=${active(h) ? "active" : ""}><span class="ico">${icon}</span>${label.split(" ")[0]}
        ${h === "#/notifications" && unread ? html`<span class="count">${unread}</span>` : null}</a>`)}
    </nav>
  </div>`;
}

function applyBranding(user) {
  const b = user?.branding;
  if (b?.primary_color) {
    document.documentElement.style.setProperty("--primary", b.primary_color);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", b.primary_color);
  }
  if (b?.accent_color) document.documentElement.style.setProperty("--accent", b.accent_color);
  document.title = b?.display_name || user?.university?.name || "منصة الجامعة الذكية";
}

// The platform administrator either manages the platform or, after choosing a university,
// works inside it with its administration's full powers (the server enforces and audits this).
function PlatformShell({ user, onLogout }) {
  const [acting, setActingState] = useState(getActing());
  const [eff, setEff] = useState(null);
  useEffect(() => {
    const on = () => setActingState(getActing());
    window.addEventListener("nus:acting", on);
    return () => window.removeEventListener("nus:acting", on);
  }, []);
  useEffect(() => {
    setEff(null);
    if (!acting) return;
    api.get("/api/me").then(setEff).catch((e) => { toastError(e); setActing(null); });
  }, [acting]);
  useEffect(() => { applyBranding(eff || user); }, [eff]);
  const logout = () => { setActing(null); onLogout(); };
  if (!acting) return html`<${Shell} user=${user} onLogout=${logout} />`;
  if (!eff) return html`<div class="boot">جارٍ فتح الجامعة…</div>`;
  return html`<${Shell} key=${acting} user=${eff} onLogout=${logout} />`;
}

function App() {
  const [user, setUser] = useState(undefined);

  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => {});
    setToken(null);
    setUser(null);
    location.hash = "#/";
  };

  useEffect(() => {
    setLogoutHandler(() => { setToken(null); setUser(null); });
    // "Open the dashboard" from the mobile app: a one-time code signs this browser in
    const handoff = location.hash.match(/^#\/handoff\/([\w.-]+)$/);
    if (handoff) {
      history.replaceState(null, "", "/#/");
      api.post("/api/auth/handoff", { code: handoff[1] })
        .then((data) => { setToken(data.access_token); setUser(data.user); })
        .catch(() => tryRefresh().then((data) => setUser(data ? data.user : null)));
      return;
    }
    tryRefresh().then((data) => setUser(data ? data.user : null));
  }, []);

  useEffect(() => { if (user) applyBranding(user); }, [user]);

  if (user === undefined) return html`<div class="boot">جارٍ التحميل…</div>`;
  if (!user) return html`<${Login} onLogin=${(data) => { setToken(data.access_token); setUser(data.user); }} />`;
  if (user.role === "platform_admin") return html`<${PlatformShell} user=${user} onLogout=${logout} />`;
  return html`<${Shell} user=${user} onLogout=${logout} />`;
}

render(html`<${App} />`, document.getElementById("app"));

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
