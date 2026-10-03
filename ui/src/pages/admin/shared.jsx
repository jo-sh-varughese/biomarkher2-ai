/* Pieces every admin page shares: the data-layer context, a loading hook,
   and the small presentational parts (role badge, status pill, user cell,
   device and event labels) that have to read the same on every screen. */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import Icon from "../../components/Icon.jsx";
import { avatarStyle } from "../../state/AuthContext.jsx";
import { dateTime, initials, relativeTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";

export const AdminContext = createContext(null);

export function useAdmin() {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdmin must be used inside the admin layout");
  return ctx;
}

/** Runs `loader` now and whenever `deps` change; `reload` re-runs it. Stale
    responses (from a previous set of deps) are dropped, so typing quickly
    in a search box can't paint an older result over a newer one. */
export function useLoad(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const run = useCallback(async () => {
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await loader();
      if (mine === seq.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (mine === seq.current) setState((s) => ({ ...s, error, loading: false }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    run();
  }, [run]);
  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) };
}

export function PageHead({ title, lede, actions, eyebrow }) {
  return (
    <div className="page__head">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h1>{title}</h1>
        {lede ? <p className="lede">{lede}</p> : null}
      </div>
      {actions ? <div className="page__actions">{actions}</div> : null}
    </div>
  );
}

export function LoadError({ error, onRetry, t }) {
  return (
    <div className="empty">
      <span className="empty__art">
        <Icon name="alert" size={28} strokeWidth={1.5} />
      </span>
      <h3>{t("admin.loadFailed")}</h3>
      <p>{errorText(error, t)}</p>
      <button type="button" className="btn" onClick={onRetry}>
        <Icon name="refresh" size={15} /> {t("admin.retry")}
      </button>
    </div>
  );
}

export function SkeletonRows({ rows = 5 }) {
  return (
    <div className="skeleton-rows" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skeleton" style={{ height: 44, opacity: 1 - i * 0.14 }} />
      ))}
    </div>
  );
}

const ROLE_ICON = { admin: "shield", pathologist: "scan", viewer: "eye" };

export function RoleBadge({ role, t }) {
  return (
    <span className={`role-badge role-badge--${role}`}>
      <Icon name={ROLE_ICON[role] ?? "user"} size={12} />
      {t(`roles.${role}`)}
    </span>
  );
}

/** The one state that matters most, first: a lock blocks sign-in right now,
    a pending request needs an administrator, and so on down. */
export function userState(user) {
  if (user.locked) return "locked";
  if (user.status === "pending") return "pending";
  if (user.status === "invited") return "invited";
  if (user.status === "disabled") return "disabled";
  if (user.must_change_password) return "mustChange";
  return "active";
}

const STATE_TONE = {
  active: "ok",
  locked: "danger",
  pending: "warn",
  invited: "accent",
  disabled: "muted",
  mustChange: "warn",
};

export function StatusPill({ user, t }) {
  const state = userState(user);
  return (
    <span className={`status-pill status-pill--${STATE_TONE[state]}`}>
      <span className="status-pill__dot" aria-hidden="true" />
      {t(`status.${state}`)}
    </span>
  );
}

export function UserCell({ user, you, t, onOpen }) {
  const body = (
    <>
      <span className="avatar avatar--sm" style={avatarStyle(user.accent)} aria-hidden="true">
        {initials(user.name)}
      </span>
      <span className="user-cell__text">
        <span className="user-cell__name">
          {user.name}
          {you ? <span className="you-tag">{t("admin.you")}</span> : null}
        </span>
        <span className="user-cell__email">{user.email}</span>
      </span>
    </>
  );
  return onOpen ? (
    <button type="button" className="user-cell user-cell--button" onClick={onOpen}>
      {body}
    </button>
  ) : (
    <span className="user-cell">{body}</span>
  );
}

export function when(value, t, locale) {
  return value ? relativeTime(value, t, locale) : t("admin.never");
}

export function stamp(value, locale) {
  return value ? dateTime(value, locale) : "—";
}

/* ------------------------------------------------------------ devices --- */

/** "Chrome on Windows" from a user-agent string -- enough to recognise one's
    own laptop in a list of sessions, which is all this is for. */
export function device(ua = "") {
  const browser =
    (/Edg\//.test(ua) && "Edge") ||
    (/OPR\//.test(ua) && "Opera") ||
    (/Firefox\//.test(ua) && "Firefox") ||
    (/Chrome\//.test(ua) && "Chrome") ||
    (/Safari\//.test(ua) && "Safari") ||
    null;
  const os =
    (/iPhone|iPad|iPod/.test(ua) && "iOS") ||
    (/Android/.test(ua) && "Android") ||
    (/Windows/.test(ua) && "Windows") ||
    (/Mac OS X|Macintosh/.test(ua) && "macOS") ||
    (/Linux/.test(ua) && "Linux") ||
    null;
  const mobile = /iPhone|Android.+Mobile|iPod/.test(ua);
  return { browser, os, icon: mobile ? "smartphone" : "monitor" };
}

export function deviceLabel(ua, t) {
  const { browser, os } = device(ua);
  if (!browser && !os) return t("admin.sessions.unknownDevice");
  if (!os) return browser;
  if (!browser) return os;
  return t("admin.sessions.on", { browser, os });
}

/* ------------------------------------------------------------- events --- */

const EVENT_LOOK = {
  "auth.login": ["login", "ok"],
  "auth.login_failed": ["alert", "warn"],
  "auth.login_blocked": ["ban", "danger"],
  "auth.locked": ["lock", "danger"],
  "auth.logout": ["logout", "muted"],
  "auth.session_revoked": ["logout", "muted"],
  "auth.password_changed": ["key", "accent"],
  "auth.password_reset": ["key", "accent"],
  "setup.completed": ["sparkles", "accent"],
  "user.created": ["userPlus", "accent"],
  "user.updated": ["pen", "accent"],
  "user.profile_updated": ["pen", "muted"],
  "user.approved": ["userCheck", "ok"],
  "user.deleted": ["trash", "danger"],
  "user.password_set": ["key", "warn"],
  "user.link_created": ["mail", "accent"],
  "user.unlocked": ["unlock", "ok"],
  "user.sessions_revoked": ["logout", "warn"],
  "access.requested": ["userPlus", "warn"],
  "access.rejected": ["ban", "muted"],
  "access.duplicate": ["userPlus", "muted"],
  "settings.updated": ["settings", "accent"],
  "data.exported": ["download", "muted"],
};

export function eventLook(action) {
  const [icon, tone] = EVENT_LOOK[action] ?? ["activity", "muted"];
  return { icon, tone };
}

export function eventLabel(event, t) {
  // Action names contain dots ("auth.login"), so they can't go through the
  // dotted key lookup; take the table and index it directly.
  const labels = t("admin.events");
  return (labels && typeof labels === "object" && labels[event.action]) || event.action;
}

const fmtValue = (value, t) => {
  if (value === true) return t("admin.system.on");
  if (value === false) return t("admin.system.off");
  if (value === "" || value == null) return "—";
  if (typeof value === "string" && ["admin", "pathologist", "viewer"].includes(value)) return t(`roles.${value}`);
  if (typeof value === "string" && ["active", "invited", "pending", "disabled"].includes(value)) return t(`status.${value}`);
  return String(value);
};

/** A one-line summary of what an event changed, in the reader's language. */
export function eventDetail(event, t) {
  const d = event.detail || {};
  if (d.changes) {
    return Object.entries(d.changes)
      .map(([key, change]) => {
        const settingKey = `admin.settings.keys.${key}`;
        const settingName = t(settingKey);
        const name = settingName !== settingKey ? settingName : key.replace(/_/g, " ");
        return `${name}: ${fmtValue(change.from, t)} → ${fmtValue(change.to, t)}`;
      })
      .join(" · ");
  }
  const parts = [];
  if (d.reason) {
    const key = `admin.reasons.${d.reason}`;
    const text = t(key);
    parts.push(text === key ? d.reason : text);
  }
  if (d.attempts) parts.push(`#${d.attempts}`);
  if (d.role && event.action !== "user.deleted") parts.push(fmtValue(d.role, t));
  if (d.kind) parts.push(t(`admin.linkKinds.${d.kind}`));
  if (d.minutes) parts.push(`${d.minutes} ${t("admin.settings.units.minutes")}`);
  if (d.file) parts.push(d.file);
  if (typeof d.count === "number") parts.push(t("admin.drawer.signedOut", { n: d.count }));
  if (d.must_change) parts.push(t("status.mustChange"));
  if (d.remember) parts.push(t("admin.sessions.remembered"));
  return parts.join(" · ");
}

export function EventRow({ event, t, locale, compact = false }) {
  const { icon, tone } = eventLook(event.action);
  const actor = event.actor?.name || event.actor?.email;
  const target = event.target?.email;
  const detail = eventDetail(event, t);
  return (
    <li className={`event${compact ? " event--compact" : ""}`}>
      <span className={`event__icon tone-${tone}`} aria-hidden="true">
        <Icon name={icon} size={15} />
      </span>
      <div className="event__text">
        <span className="event__title">
          <b>{eventLabel(event, t)}</b>
          {target && target !== event.actor?.email ? <span className="event__target"> · {target}</span> : null}
        </span>
        <span className="event__meta">
          {actor ? `${actor} · ` : ""}
          <span title={stamp(event.at, locale)}>{relativeTime(event.at, t, locale)}</span>
          {!compact && detail ? ` · ${detail}` : ""}
        </span>
      </div>
    </li>
  );
}
