/* The admin console's frame: its section tabs, the demo-data banner when
   there is no server, and the data layer every page below reads through
   useAdmin(). Reaching it needs the "admin" permission; the server checks
   the same permission on every /api/admin route, so this is the courtesy,
   not the lock. */

import { useMemo } from "react";
import { NavLink, Outlet } from "react-router-dom";
import Icon from "../../components/Icon.jsx";
import { useAuth } from "../../state/AuthContext.jsx";
import { useT } from "../../i18n/I18nContext.jsx";
import { adminApi, resetDemoAdmin } from "../../lib/adminApi.js";
import { AdminContext } from "./shared.jsx";

const TABS = [
  { to: "/admin", end: true, icon: "grid", key: "admin.nav.overview" },
  { to: "/admin/users", icon: "users", key: "admin.nav.users", badge: true },
  { to: "/admin/sessions", icon: "monitor", key: "admin.nav.sessions" },
  { to: "/admin/audit", icon: "activity", key: "admin.nav.audit" },
  { to: "/admin/settings", icon: "settings", key: "admin.nav.settings" },
  { to: "/admin/system", icon: "server", key: "admin.nav.system" },
];

export default function AdminLayout() {
  const { can, isServer, user, pendingRequests, refresh } = useAuth();
  const t = useT();
  const api = useMemo(() => adminApi(!isServer, user), [isServer, user]);
  const value = useMemo(() => ({ api, demo: api.demo, refreshBadge: refresh }), [api, refresh]);

  if (!can("admin")) {
    return (
      <div className="empty" style={{ marginTop: 40 }}>
        <span className="empty__art">
          <Icon name="lock" size={28} strokeWidth={1.5} />
        </span>
        <h3>{t("admin.noAccessTitle")}</h3>
        <p>{t("admin.noAccessBody")}</p>
      </div>
    );
  }

  return (
    <AdminContext.Provider value={value}>
      {api.demo ? (
        <div className="note note--warn admin-demo">
          <span className="note__icon">
            <Icon name="info" size={16} />
          </span>
          <span>{t("admin.demoBanner")}</span>
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => {
              resetDemoAdmin();
              window.location.reload();
            }}
          >
            <Icon name="refresh" size={14} /> {t("admin.resetDemo")}
          </button>
        </div>
      ) : null}

      <nav className="admin-tabs" aria-label={t("admin.navLabel")}>
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => `admin-tabs__item${isActive ? " is-active" : ""}`}
          >
            <Icon name={tab.icon} size={16} />
            <span>{t(tab.key)}</span>
            {tab.badge && pendingRequests ? (
              <span className="count count--warn" title={t("admin.overview.kpiPending")}>
                {pendingRequests}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </AdminContext.Provider>
  );
}
