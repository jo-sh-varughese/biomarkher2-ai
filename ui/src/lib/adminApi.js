/* ============================================================================
   The admin console's data layer.

   Live, every call goes to /api/admin/* and the server enforces every rule
   (the last administrator, no self-demotion, password policy, the audit
   trail). With no backend -- the static demo build -- the same interface is
   served from a seeded, in-browser store so the console can be shown end to
   end. That store imitates the server's rules closely enough to demonstrate
   them, is labelled "Demo data" on every screen, and protects nothing.
   ==========================================================================*/

import { apiRequest, downloadFile } from "./api.js";
import { DEMO_REVIEWS } from "./demo.js";

const qs = (params = {}) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return entries.length ? `?${new URLSearchParams(entries)}` : "";
};

/* ---------------------------------------------------------------- live --- */

const live = {
  demo: false,
  overview: () => apiRequest("/api/admin/overview"),
  users: (params) => apiRequest(`/api/admin/users${qs(params)}`),
  user: (id) => apiRequest(`/api/admin/users/${id}`),
  createUser: (body) => apiRequest("/api/admin/users", { method: "POST", body }),
  updateUser: (id, patch) => apiRequest(`/api/admin/users/${id}`, { method: "PATCH", body: patch }),
  deleteUser: (id) => apiRequest(`/api/admin/users/${id}`, { method: "DELETE" }),
  setPassword: (id, body) => apiRequest(`/api/admin/users/${id}/password`, { method: "POST", body }),
  link: (id) => apiRequest(`/api/admin/users/${id}/link`, { method: "POST", body: {} }),
  unlock: (id) => apiRequest(`/api/admin/users/${id}/unlock`, { method: "POST", body: {} }),
  signOut: (id) => apiRequest(`/api/admin/users/${id}/sign-out`, { method: "POST", body: {} }),
  approve: (id, role) => apiRequest(`/api/admin/users/${id}/approve`, { method: "POST", body: { role } }),
  sessions: () => apiRequest("/api/admin/sessions"),
  revokeSession: (id) => apiRequest(`/api/admin/sessions/${id}`, { method: "DELETE" }),
  audit: (params) => apiRequest(`/api/admin/audit${qs(params)}`),
  settings: () => apiRequest("/api/admin/settings"),
  updateSettings: (patch) => apiRequest("/api/admin/settings", { method: "PATCH", body: patch }),
  system: () => apiRequest("/api/admin/system"),
  exportFile: (name, params) => {
    const paths = {
      users: "/api/admin/users.csv",
      audit: `/api/admin/audit.csv${qs(params)}`,
      reviews: "/api/admin/export/reviews.jsonl",
      annotations: "/api/admin/export/annotations.jsonl",
    };
    return downloadFile(paths[name], `biomarkher2-${name}`);
  },
};

/* ---------------------------------------------------------------- demo --- */

const STORE_KEY = "bmh2.demoAdmin.v1";
const ROLES = ["admin", "pathologist", "viewer"];
const PERMS = {
  admin: ["admin", "analyze", "annotate", "report", "review", "view"],
  pathologist: ["analyze", "annotate", "report", "review", "view"],
  viewer: ["analyze", "report", "view"],
};
const CATEGORIES = {
  signin: ["auth.login", "auth.login_failed", "auth.login_blocked", "auth.locked", "auth.logout", "auth.session_revoked"],
  accounts: ["setup.completed", "user.created", "user.updated", "user.profile_updated", "user.approved",
    "user.deleted", "access.requested", "access.rejected", "access.duplicate"],
  security: ["auth.password_changed", "auth.password_reset", "user.password_set", "user.link_created",
    "user.unlocked", "user.sessions_revoked", "auth.locked"],
  settings: ["settings.updated"],
  data: ["data.exported"],
};
export const DEMO_SETTINGS = {
  site_name: "BioMarkHER2",
  announcement: "",
  session_idle_minutes: 60,
  session_max_hours: 12,
  allow_remember_me: true,
  remember_me_days: 7,
  password_min_length: 10,
  lockout_threshold: 5,
  lockout_minutes: 15,
  allow_access_requests: true,
};

const iso = (d) => new Date(d).toISOString().replace(/\.\d{3}Z$/, "+00:00");
const hoursAgo = (h) => iso(Date.now() - h * 3600e3);
const rid = (prefix) =>
  `${prefix}_${Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, "0")).join("")}`;

function fail(code, extra = {}, status = 400) {
  const err = new Error(code);
  Object.assign(err, { code, extra, status, fromServer: true });
  return err;
}

/* A small seeded generator, so the demo shows the same history every time. */
function seeded(seed) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

const UAS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
  "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
];

function seedStore(currentUser) {
  const base = (over) => ({
    id: rid("usr"),
    role: "pathologist",
    status: "active",
    registration: "",
    title: "",
    accent: "violet",
    must_change_password: false,
    has_password: true,
    locked: false,
    locked_until: null,
    failed_attempts: 0,
    request_note: "",
    created_at: hoursAgo(24 * 40),
    created_by: null,
    updated_at: hoursAgo(24 * 3),
    last_login_at: hoursAgo(5),
    last_login_ip: "10.21.4.18",
    password_changed_at: hoursAgo(24 * 30),
    ...over,
  });
  const me = base({
    id: "usr_demo000000000001",
    email: currentUser?.email ?? "pathologist@gmck.edu.in",
    name: currentUser?.name ?? "Dr. Anita Menon",
    role: "admin",
    registration: currentUser?.registration ?? "TC-MC-24817",
    title: "Consultant Pathologist",
    last_login_at: hoursAgo(0.1),
    last_login_ip: "127.0.0.1",
  });
  const users = [
    me,
    base({ email: "m.nair@example.org", name: "Dr. Meera Nair", role: "admin", title: "Head of Department",
      registration: "TC-MC-10452", accent: "teal", last_login_at: hoursAgo(26) }),
    base({ email: "s.pillai@example.org", name: "Dr. S. Pillai", title: "Consultant Pathologist",
      registration: "TC-MC-18820", accent: "amber", last_login_at: hoursAgo(2) }),
    base({ email: "r.thomas@example.org", name: "Dr. R. Thomas", title: "Senior Resident",
      registration: "TC-MC-30117", accent: "sky", last_login_at: hoursAgo(9) }),
    base({ email: "f.rahman@example.org", name: "Dr. Fathima Rahman", title: "Junior Resident",
      registration: "TC-MC-41205", accent: "rose", locked: true, locked_until: iso(Date.now() + 11 * 60e3),
      failed_attempts: 5, last_login_at: hoursAgo(50) }),
    base({ email: "j.kurian@example.org", name: "Dr. Joseph Kurian", title: "Junior Resident",
      registration: "TC-MC-41377", accent: "lime", must_change_password: true, last_login_at: null,
      created_at: hoursAgo(20) }),
    base({ email: "a.varma@example.org", name: "Arjun Varma", role: "viewer", title: "Research fellow",
      accent: "sky", last_login_at: hoursAgo(72) }),
    base({ email: "l.das@example.org", name: "Leela Das", role: "viewer", status: "disabled",
      title: "Laboratory Technician", accent: "teal", last_login_at: hoursAgo(24 * 21) }),
    base({ email: "v.menon@example.org", name: "Dr. Vivek Menon", status: "invited", has_password: false,
      title: "Senior Resident", last_login_at: null, created_at: hoursAgo(30), password_changed_at: null }),
    base({ email: "n.joseph@example.org", name: "Dr. Neha Joseph", role: "viewer", status: "pending",
      title: "Senior Resident", registration: "TC-MC-45591", last_login_at: null, created_at: hoursAgo(7),
      request_note: "Joining the HER2 concordance study from next week." }),
  ];

  const byEmail = Object.fromEntries(users.map((u) => [u.email, u]));
  const rand = seeded(20260925);
  const audit = [];
  let id = 1;
  const push = (at, action, actor, target, extra = {}) =>
    audit.push({
      id: id++,
      at,
      action,
      actor: actor ? { id: actor.id, email: actor.email, name: actor.name } : null,
      target: target ? { id: target.id ?? null, email: target.email } : null,
      ip: extra.ip ?? "10.21.4." + Math.floor(10 + rand() * 80),
      detail: extra.detail ?? {},
    });
  const active = users.filter((u) => u.status === "active" && !u.must_change_password);
  for (let day = 13; day >= 0; day -= 1) {
    const logins = 2 + Math.floor(rand() * 5);
    for (let n = 0; n < logins; n += 1) {
      const who = active[Math.floor(rand() * active.length)];
      push(hoursAgo(day * 24 + 18 - n * 2 - rand()), "auth.login", who, who);
    }
    if (rand() < 0.35) {
      const who = active[Math.floor(rand() * active.length)];
      push(hoursAgo(day * 24 + 20), "auth.login_failed", null, who, { detail: { reason: "wrong_password", attempts: 1 } });
    }
  }
  push(hoursAgo(50.2), "auth.login_failed", null, byEmail["f.rahman@example.org"], { detail: { reason: "wrong_password", attempts: 5 } });
  push(hoursAgo(50.2), "auth.locked", null, byEmail["f.rahman@example.org"], { detail: { minutes: 15 } });
  push(hoursAgo(30), "user.created", me, byEmail["v.menon@example.org"], { detail: { role: "pathologist", status: "invited" } });
  push(hoursAgo(30), "user.link_created", me, byEmail["v.menon@example.org"], { detail: { kind: "invite" } });
  push(hoursAgo(20), "user.created", me, byEmail["j.kurian@example.org"], { detail: { role: "pathologist", status: "active" } });
  push(hoursAgo(7), "access.requested", null, byEmail["n.joseph@example.org"], { detail: { role: "viewer", status: "pending" } });
  push(hoursAgo(4), "settings.updated", me, null, { detail: { changes: { session_idle_minutes: { from: 30, to: 60 } } } });
  audit.sort((a, b) => (a.at < b.at ? -1 : 1));
  audit.forEach((e, i) => {
    e.id = i + 1;
  });

  const sessions = [
    { user: me, ua: UAS[0], ip: "127.0.0.1", current: true, created: 0.1, seen: 0 },
    { user: byEmail["s.pillai@example.org"], ua: UAS[1], ip: "10.21.4.33", created: 2, seen: 0.2 },
    { user: byEmail["s.pillai@example.org"], ua: UAS[2], ip: "10.21.7.9", created: 26, seen: 3, remember: true },
    { user: byEmail["r.thomas@example.org"], ua: UAS[3], ip: "10.21.4.61", created: 9, seen: 0.6 },
    { user: byEmail["m.nair@example.org"], ua: UAS[0], ip: "10.21.2.4", created: 26, seen: 1.5, remember: true },
  ].map((s) => ({
    id: rid("ses"),
    user_id: s.user.id,
    user_name: s.user.name,
    user_email: s.user.email,
    user_role: s.user.role,
    remember: Boolean(s.remember),
    created_at: hoursAgo(s.created),
    last_seen_at: hoursAgo(s.seen),
    expires_at: iso(Date.now() + (s.remember ? 6 * 24 : 10) * 3600e3),
    ip: s.ip,
    user_agent: s.ua,
    current: Boolean(s.current),
  }));

  return { users, audit, sessions, settings: { ...DEMO_SETTINGS }, meId: me.id };
}

function createDemo(currentUser) {
  let store;
  try {
    store = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
  } catch {
    store = null;
  }
  if (!store?.users?.length) store = seedStore(currentUser);

  const save = () => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(store));
    } catch {
      /* A blocked store only means the demo resets on reload. */
    }
  };
  const me = () => store.users.find((u) => u.id === store.meId);
  const find = (id) => {
    const user = store.users.find((u) => u.id === id);
    if (!user) throw fail("not_found", {}, 404);
    return user;
  };
  const log = (action, target, detail = {}) => {
    const actor = me();
    store.audit.push({
      id: (store.audit.at(-1)?.id ?? 0) + 1,
      at: iso(Date.now()),
      action,
      actor: actor ? { id: actor.id, email: actor.email, name: actor.name } : null,
      target: target ? { id: target.id, email: target.email } : null,
      ip: "127.0.0.1",
      detail,
    });
  };
  const activeAdmins = () => store.users.filter((u) => u.role === "admin" && u.status === "active").length;
  const checkPassword = (password, email) => {
    const min = store.settings.password_min_length;
    if (!password || password.length < min) throw fail("password_too_short", { min });
    if (email && password.toLowerCase() === email.toLowerCase()) throw fail("password_like_email");
    if (new Set(password).size < 4) throw fail("password_repetitive");
  };
  const cleanEmail = (email) => {
    const value = String(email || "").trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value)) throw fail("email_invalid");
    return value;
  };
  const cleanName = (name) => {
    const value = String(name || "").trim().replace(/\s+/g, " ");
    if (value.length < 2 || value.length > 80) throw fail("name_invalid");
    return value;
  };
  const pause = (ms = 260) => new Promise((resolve) => setTimeout(resolve, ms));
  const done = async (value) => {
    save();
    await pause();
    return structuredClone(value);
  };
  const demoLink = (user, kind) => {
    const token = `demo-${rid("tok").slice(4)}`;
    log("user.link_created", user, { kind });
    return { token, path: `/reset?token=${token}`, expires_at: iso(Date.now() + (kind === "invite" ? 72 : 24) * 3600e3), kind };
  };

  return {
    demo: true,
    async overview() {
      const users = store.users;
      const week = Date.now() - 7 * 864e5;
      const fortnight = Date.now() - 14 * 864e5;
      const logins = store.audit.filter((e) => e.action === "auth.login" && Date.parse(e.at) >= fortnight).map((e) => e.at);
      return done({
        users: {
          total: users.length,
          by_role: Object.fromEntries(ROLES.map((r) => [r, users.filter((u) => u.role === r && u.status === "active").length])),
          by_status: Object.fromEntries(["active", "invited", "pending", "disabled"].map((s) => [s, users.filter((u) => u.status === s).length])),
          locked: users.filter((u) => u.locked).length,
          must_change_password: users.filter((u) => u.must_change_password).length,
          never_signed_in: users.filter((u) => u.status === "active" && !u.last_login_at).length,
        },
        sessions: { active: store.sessions.length, users_online: new Set(store.sessions.map((s) => s.user_id)).size },
        signins: {
          last_14_days: logins,
          week: logins.filter((at) => Date.parse(at) >= week).length,
          failed_week: store.audit.filter((e) => e.action === "auth.login_failed" && Date.parse(e.at) >= week).length,
        },
        pending: users.filter((u) => u.status === "pending"),
        locked: users.filter((u) => u.locked),
        recent: [...store.audit].reverse().slice(0, 8),
      });
    },
    async users({ q = "", role = "", status = "" } = {}) {
      const needle = q.trim().toLowerCase();
      const list = store.users
        .filter((u) => !role || u.role === role)
        .filter((u) => !status || (status === "locked" ? u.locked : u.status === status))
        .filter((u) => !needle || [u.name, u.email, u.registration, u.title].some((v) => v?.toLowerCase().includes(needle)))
        .sort((a, b) => a.name.localeCompare(b.name));
      return done({ users: list });
    },
    async user(id) {
      const user = find(id);
      return done({
        user,
        sessions: store.sessions.filter((s) => s.user_id === id),
        activity: [...store.audit].reverse().filter((e) => e.actor?.id === id || e.target?.id === id).slice(0, 25),
        reviews: DEMO_REVIEWS.filter((r) => r.reviewer && user.name.includes(r.reviewer.split(" ").at(-1))).length,
      });
    },
    async createUser(body) {
      const email = cleanEmail(body.email);
      const name = cleanName(body.name);
      if (!ROLES.includes(body.role)) throw fail("role_invalid");
      if (store.users.some((u) => u.email === email)) throw fail("email_taken", {}, 409);
      const invite = body.access === "invite";
      if (!invite) checkPassword(body.password, email);
      const user = {
        id: rid("usr"), email, name, role: body.role, status: invite ? "invited" : "active",
        registration: String(body.registration || "").toUpperCase(), title: body.title || "", accent: "violet",
        must_change_password: !invite && body.must_change_password !== false, has_password: !invite,
        locked: false, locked_until: null, failed_attempts: 0, request_note: "",
        created_at: iso(Date.now()), created_by: store.meId, updated_at: iso(Date.now()),
        last_login_at: null, last_login_ip: null, password_changed_at: invite ? null : iso(Date.now()),
      };
      store.users.push(user);
      log("user.created", user, { role: user.role, status: user.status });
      return done(invite ? { user, link: demoLink(user, "invite") } : { user });
    },
    async updateUser(id, patch) {
      const user = find(id);
      const changes = {};
      if ("name" in patch) changes.name = cleanName(patch.name);
      if ("email" in patch) {
        changes.email = cleanEmail(patch.email);
        if (store.users.some((u) => u.email === changes.email && u.id !== id)) throw fail("email_taken", {}, 409);
      }
      if ("role" in patch) {
        if (!ROLES.includes(patch.role)) throw fail("role_invalid");
        changes.role = patch.role;
      }
      if ("status" in patch) changes.status = patch.status;
      if ("registration" in patch) changes.registration = String(patch.registration || "").toUpperCase();
      if ("title" in patch) changes.title = patch.title;
      const diff = Object.fromEntries(Object.entries(changes).filter(([k, v]) => user[k] !== v));
      if (!Object.keys(diff).length) return done({ user });
      if (id === store.meId && ("role" in diff || "status" in diff)) throw fail("self_change", {}, 409);
      const wasAdmin = user.role === "admin" && user.status === "active";
      const staysAdmin = (diff.role ?? user.role) === "admin" && (diff.status ?? user.status) === "active";
      if (wasAdmin && !staysAdmin && activeAdmins() <= 1) throw fail("last_admin", {}, 409);
      Object.assign(user, diff, { updated_at: iso(Date.now()) });
      if (diff.status === "disabled") store.sessions = store.sessions.filter((s) => s.user_id !== id);
      log("user.updated", user, { changes: diff });
      return done({ user });
    },
    async deleteUser(id) {
      const user = find(id);
      if (id === store.meId) throw fail("self_delete", {}, 409);
      if (user.role === "admin" && user.status === "active" && activeAdmins() <= 1) throw fail("last_admin", {}, 409);
      store.users = store.users.filter((u) => u.id !== id);
      store.sessions = store.sessions.filter((s) => s.user_id !== id);
      log(user.status === "pending" ? "access.rejected" : "user.deleted", user, { name: user.name, role: user.role });
      return done({ ok: true });
    },
    async setPassword(id, { password, must_change_password = true }) {
      const user = find(id);
      if (id === store.meId) throw fail("use_profile", {}, 409);
      checkPassword(password, user.email);
      Object.assign(user, {
        must_change_password: Boolean(must_change_password), locked: false, locked_until: null, failed_attempts: 0,
        has_password: true, status: user.status === "invited" ? "active" : user.status, password_changed_at: iso(Date.now()),
      });
      store.sessions = store.sessions.filter((s) => s.user_id !== id);
      log("user.password_set", user, { must_change: Boolean(must_change_password) });
      return done({ user });
    },
    async link(id) {
      const user = find(id);
      if (["pending", "disabled"].includes(user.status)) throw fail("link_not_allowed", {}, 409);
      return done({ link: demoLink(user, user.status === "invited" ? "invite" : "reset") });
    },
    async unlock(id) {
      const user = find(id);
      Object.assign(user, { locked: false, locked_until: null, failed_attempts: 0 });
      log("user.unlocked", user);
      return done({ user });
    },
    async signOut(id) {
      const user = find(id);
      const before = store.sessions.length;
      store.sessions = store.sessions.filter((s) => s.user_id !== id || s.current);
      log("user.sessions_revoked", user, { count: before - store.sessions.length });
      return done({ ok: true, revoked: before - store.sessions.length });
    },
    async approve(id, role) {
      const user = find(id);
      if (user.status !== "pending") throw fail("not_pending", {}, 409);
      Object.assign(user, { status: "active", role, updated_at: iso(Date.now()) });
      log("user.approved", user, { role });
      return done({ user });
    },
    async sessions() {
      return done({ sessions: [...store.sessions].sort((a, b) => (a.last_seen_at < b.last_seen_at ? 1 : -1)) });
    },
    async revokeSession(id) {
      const session = store.sessions.find((s) => s.id === id);
      if (!session) throw fail("not_found", {}, 404);
      if (session.current) throw fail("use_logout", {}, 409);
      store.sessions = store.sessions.filter((s) => s.id !== id);
      log("auth.session_revoked", { id: session.user_id, email: session.user_email }, { session: id });
      return done({ ok: true });
    },
    async audit({ q = "", category = "", days, before, limit = 100 } = {}) {
      const needle = q.trim().toLowerCase();
      const since = days ? Date.now() - days * 864e5 : 0;
      const rows = [...store.audit]
        .reverse()
        .filter((e) => !category || CATEGORIES[category]?.includes(e.action))
        .filter((e) => !since || Date.parse(e.at) >= since)
        .filter((e) => !before || e.id < before)
        .filter((e) =>
          !needle ||
          [e.action, e.actor?.email, e.actor?.name, e.target?.email, e.ip, JSON.stringify(e.detail)]
            .some((v) => v?.toLowerCase().includes(needle)),
        );
      const events = rows.slice(0, limit);
      return done({ events, next: rows.length > limit ? events.at(-1).id : null });
    },
    async settings() {
      return done({ settings: store.settings });
    },
    async updateSettings(patch) {
      const changes = Object.fromEntries(Object.entries(patch).filter(([k, v]) => store.settings[k] !== v));
      if (Object.keys(changes).length) {
        log("settings.updated", null, {
          changes: Object.fromEntries(Object.entries(changes).map(([k, v]) => [k, { from: store.settings[k], to: v }])),
        });
        Object.assign(store.settings, changes);
      }
      return done({ settings: store.settings });
    },
    async system() {
      const admins = activeAdmins();
      return done({
        version: "0.2.0",
        python: "—",
        platform: "Static demo build (no server)",
        started_at: hoursAgo(3),
        uptime_seconds: 3 * 3600,
        host: window.location.hostname,
        port: Number(window.location.port) || (window.location.protocol === "https:" ? 443 : 80),
        secure_cookies: window.location.protocol === "https:",
        trust_proxy: false,
        model: { run: "artifacts/phase2_unet", epoch: 4, architecture: "unet_resnet18", conformal: "loaded", alpha: 0.1 },
        storage: {
          database: { path: "browser localStorage (demo)", exists: true, bytes: JSON.stringify(store).length },
          reviews: { path: "demo reviews", exists: true, bytes: JSON.stringify(DEMO_REVIEWS).length, entries: DEMO_REVIEWS.length },
          annotations: { path: "demo annotations", exists: false, bytes: 0, entries: 0 },
        },
        checks: [
          { id: "admins", level: admins >= 2 ? "ok" : "warn", value: admins },
          { id: "transport", level: "ok", value: { host: window.location.hostname, secure_cookies: window.location.protocol === "https:" } },
          { id: "model", level: "ok", value: "artifacts/phase2_unet" },
          { id: "conformal", level: "ok", value: "loaded" },
          { id: "portal", level: "ok", value: "static build" },
        ],
      });
    },
    async exportFile(name) {
      let text;
      let type = "text/csv";
      if (name === "users") {
        const rows = [["name", "email", "role", "status", "registration", "title", "created_at", "last_login_at"]];
        store.users.forEach((u) => rows.push([u.name, u.email, u.role, u.status, u.registration, u.title, u.created_at, u.last_login_at ?? ""]));
        text = rows.map((r) => r.map(csvCell).join(",")).join("\n");
      } else if (name === "audit") {
        const rows = [["time_utc", "action", "actor_email", "actor_name", "target_email", "ip", "detail"]];
        [...store.audit].reverse().forEach((e) =>
          rows.push([e.at, e.action, e.actor?.email ?? "", e.actor?.name ?? "", e.target?.email ?? "", e.ip ?? "", JSON.stringify(e.detail)]));
        text = rows.map((r) => r.map(csvCell).join(",")).join("\n");
      } else {
        type = "application/x-ndjson";
        text = name === "reviews" ? DEMO_REVIEWS.map((r) => JSON.stringify(r)).join("\n") : "";
      }
      log("data.exported", null, { file: name });
      save();
      const blob = new Blob([text], { type });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `biomarkher2-${name}-demo.${type === "text/csv" ? "csv" : "jsonl"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return true;
    },
  };
}

const csvCell = (value) => {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

let demoInstance = null;
export function adminApi(demo, currentUser) {
  if (!demo) return live;
  demoInstance ??= createDemo(currentUser);
  return demoInstance;
}

export function resetDemoAdmin() {
  try {
    localStorage.removeItem(STORE_KEY);
  } catch {
    /* ignore */
  }
  demoInstance = null;
}

export const DEMO_PERMISSIONS = PERMS;
