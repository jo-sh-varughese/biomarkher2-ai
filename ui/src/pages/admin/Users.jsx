/* The users table: every account, filterable by state and role, searchable,
   with each row's actions in its "⋯" menu and the full record one click
   away in a drawer. Filtering happens in the browser -- a department's
   accounts number in the tens or hundreds, and instant counts on every
   filter are worth more than a round trip per keystroke. */

import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import Icon from "../../components/Icon.jsx";
import ActionMenu from "../../components/ActionMenu.jsx";
import { useAuth } from "../../state/AuthContext.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { shortDate } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import AddUserDialog from "./AddUserDialog.jsx";
import UserDrawer from "./UserDrawer.jsx";
import UserActions, { quickAction } from "./UserActions.jsx";
import {
  LoadError,
  PageHead,
  RoleBadge,
  SkeletonRows,
  StatusPill,
  UserCell,
  stamp,
  useAdmin,
  useLoad,
  userState,
  when,
} from "./shared.jsx";

const FILTERS = ["all", "active", "pending", "invited", "locked", "disabled"];

const matches = (user, filter) => {
  if (filter === "all") return true;
  if (filter === "locked") return user.locked;
  if (filter === "active") return user.status === "active" && !user.locked;
  return user.status === filter;
};

export default function Users() {
  const { api, refreshBadge } = useAdmin();
  const { user: me } = useAuth();
  const { t, locale } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const { userId } = useParams();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [action, setAction] = useState(null);
  const filter = FILTERS.includes(params.get("status")) ? params.get("status") : "all";
  const adding = params.get("new") === "1";

  const { data, error, loading, reload } = useLoad(() => api.users(), [api]);
  const users = data?.users ?? [];

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f, users.filter((u) => matches(u, f)).length])),
    [users],
  );

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return users
      .filter((u) => matches(u, filter))
      .filter((u) => !role || u.role === role)
      .filter(
        (u) => !needle || [u.name, u.email, u.registration, u.title].some((v) => v?.toLowerCase().includes(needle)),
      )
      .sort((a, b) => {
        // Accounts that need an administrator float to the top.
        const rank = { pending: 0, locked: 1 };
        return (rank[userState(a)] ?? 2) - (rank[userState(b)] ?? 2) || a.name.localeCompare(b.name);
      });
  }, [users, filter, role, query]);

  const setFilter = (next) => {
    const p = new URLSearchParams(params);
    if (next === "all") p.delete("status");
    else p.set("status", next);
    setParams(p, { replace: true });
  };
  const openUser = (id) => navigate(`/admin/users/${id}${params.toString() ? `?${params}` : ""}`);
  const closeUser = () => navigate(`/admin/users${params.toString() ? `?${params}` : ""}`);
  const setAdding = (on) => {
    const p = new URLSearchParams(params);
    if (on) p.set("new", "1");
    else p.delete("new");
    setParams(p, { replace: true });
  };

  const isMe = (u) => me && (u.id === me.id || u.email === me.email);

  const quick = async (kind, u) => {
    try {
      await quickAction(api, kind, u);
      toast.ok(t(kind === "enable" ? "admin.drawer.enabled" : "admin.drawer.unlocked"));
      refreshBadge?.();
      reload();
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    }
  };

  const exportCsv = async () => {
    try {
      await api.exportFile("users");
      toast.ok(t("admin.system.exported"));
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    }
  };

  const menuFor = (u) => {
    const self = isMe(u);
    const pending = u.status === "pending";
    return [
      { label: t("admin.users.open"), icon: "user", onClick: () => openUser(u.id) },
      { label: t("admin.users.approve"), icon: "userCheck", hidden: !pending, onClick: () => setAction({ kind: "approve", user: u }) },
      { label: t("admin.users.reject"), icon: "ban", hidden: !pending, tone: "danger", onClick: () => setAction({ kind: "reject", user: u }) },
      { label: t("admin.users.resetPassword"), icon: "key", hidden: self || pending || u.status === "disabled", onClick: () => setAction({ kind: "password", user: u }) },
      { label: t("admin.users.resetLink"), icon: "mail", hidden: self || pending || u.status === "disabled", onClick: () => setAction({ kind: "link", user: u }) },
      { label: t("admin.users.unlock"), icon: "unlock", hidden: !u.locked, onClick: () => quick("unlock", u) },
      { label: t("admin.users.signOutAll"), icon: "logout", hidden: self || pending, onClick: () => setAction({ kind: "signout", user: u }) },
      { divider: true, hidden: self || pending },
      { label: t("admin.users.enable"), icon: "checkCircle", hidden: self || u.status !== "disabled", onClick: () => quick("enable", u) },
      { label: t("admin.users.disable"), icon: "ban", hidden: self || pending || u.status === "disabled", tone: "danger", onClick: () => setAction({ kind: "disable", user: u }) },
      { label: t("admin.users.delete"), icon: "trash", hidden: self || pending, tone: "danger", onClick: () => setAction({ kind: "delete", user: u }) },
    ];
  };

  return (
    <>
      <PageHead
        eyebrow={t("admin.eyebrow")}
        title={t("admin.users.title")}
        lede={t("admin.users.lede")}
        actions={
          <>
            <button type="button" className="btn" onClick={exportCsv}>
              <Icon name="download" size={16} /> {t("admin.users.export")}
            </button>
            <button type="button" className="btn btn--primary" onClick={() => setAdding(true)}>
              <Icon name="userPlus" size={16} /> {t("admin.users.add")}
            </button>
          </>
        }
      />

      <section className="card card--pad">
        <div className="card-head toolbar">
          <div className="seg seg--scroll" role="tablist" aria-label={t("admin.users.colStatus")}>
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={filter === f}
                className={`seg__btn${filter === f ? " is-active" : ""}`}
                onClick={() => setFilter(f)}
              >
                {t(`admin.users.filters.${f}`)}
                <span className={`seg__count${(f === "pending" || f === "locked") && counts[f] ? " seg__count--warn" : ""}`}>
                  {counts[f] ?? 0}
                </span>
              </button>
            ))}
          </div>
          <div className="toolbar__right">
            <select className="select select--sm" value={role} onChange={(e) => setRole(e.target.value)}
              aria-label={t("admin.users.colRole")}>
              <option value="">{t("admin.users.roleAll")}</option>
              {["admin", "pathologist", "viewer"].map((r) => (
                <option key={r} value={r}>{t(`roles.${r}`)}</option>
              ))}
            </select>
            <div className="searchbox searchbox--inline">
              <Icon name="search" size={16} />
              <input className="input" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder={t("admin.users.search")} aria-label={t("admin.users.search")} />
            </div>
          </div>
        </div>

        {error && !data ? (
          <LoadError error={error} onRetry={reload} t={t} />
        ) : loading && !data ? (
          <SkeletonRows rows={6} />
        ) : rows.length ? (
          <>
            <div className="table-wrap">
              <table className="data data--stack data--users">
                <thead>
                  <tr>
                    <th scope="col">{t("admin.users.colUser")}</th>
                    <th scope="col">{t("admin.users.colRole")}</th>
                    <th scope="col">{t("admin.users.colStatus")}</th>
                    <th scope="col">{t("admin.users.colLastSignIn")}</th>
                    <th scope="col">{t("admin.users.colCreated")}</th>
                    <th scope="col" className="num"><span className="sr-only">{t("admin.users.open")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((u) => (
                    <tr key={u.id} className={userState(u) === "locked" ? "is-flagged" : undefined}>
                      <td data-label={t("admin.users.colUser")}>
                        <UserCell user={u} you={isMe(u)} t={t} onOpen={() => openUser(u.id)} />
                      </td>
                      <td data-label={t("admin.users.colRole")}>
                        <RoleBadge role={u.role} t={t} />
                      </td>
                      <td data-label={t("admin.users.colStatus")}>
                        <StatusPill user={u} t={t} />
                      </td>
                      <td className="muted" data-label={t("admin.users.colLastSignIn")} title={stamp(u.last_login_at, locale)}>
                        {when(u.last_login_at, t, locale)}
                      </td>
                      <td className="muted" data-label={t("admin.users.colCreated")} title={stamp(u.created_at, locale)}>
                        {shortDate(u.created_at, locale)}
                      </td>
                      <td className="num cell-actions">
                        <ActionMenu label={t("admin.users.actionsFor", { name: u.name })} items={menuFor(u)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="table-foot">{t("admin.users.count", { n: rows.length, total: users.length })}</p>
          </>
        ) : (
          <div className="empty">
            <span className="empty__art">
              <Icon name="users" size={28} strokeWidth={1.5} />
            </span>
            <h3>{t("admin.users.empty")}</h3>
            <p>{t("admin.users.emptyBody")}</p>
          </div>
        )}
      </section>

      <AddUserDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={() => {
          reload();
          refreshBadge?.();
        }}
      />

      {userId ? <UserDrawer userId={userId} onClose={closeUser} onChanged={reload} /> : null}

      <UserActions action={action} onClose={() => setAction(null)} onDone={reload} />
    </>
  );
}
