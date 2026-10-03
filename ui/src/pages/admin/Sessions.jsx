/* Everyone signed in right now, on every device, and a way to end any one
   of those sessions -- the lost phone, the shared workstation someone
   walked away from. */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Icon from "../../components/Icon.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { relativeTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import {
  LoadError,
  PageHead,
  RoleBadge,
  SkeletonRows,
  UserCell,
  device,
  deviceLabel,
  stamp,
  useAdmin,
  useLoad,
} from "./shared.jsx";

export default function Sessions() {
  const { api } = useAdmin();
  const { t, locale } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(null);
  const { data, error, loading, reload } = useLoad(() => api.sessions(), [api]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data?.sessions ?? []).filter(
      (s) =>
        !needle ||
        [s.user_name, s.user_email, s.ip, deviceLabel(s.user_agent, t)].some((v) => v?.toLowerCase().includes(needle)),
    );
  }, [data, query, t]);

  const revoke = async (session) => {
    setBusy(session.id);
    try {
      await api.revokeSession(session.id);
      toast.ok(t("admin.sessions.revoked"), `${session.user_name} · ${deviceLabel(session.user_agent, t)}`);
      await reload();
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHead
        eyebrow={t("admin.eyebrow")}
        title={t("admin.sessions.title")}
        lede={t("admin.sessions.lede")}
        actions={
          <button type="button" className="btn" onClick={reload} disabled={loading}>
            <Icon name="refresh" size={16} /> {t("admin.refresh")}
          </button>
        }
      />

      <section className="card card--pad">
        <div className="card-head toolbar">
          <span className="badge badge--outline">
            <Icon name="monitor" size={12} /> {t("admin.sessions.count", { n: data?.sessions?.length ?? 0 })}
          </span>
          <div className="toolbar__right">
            <div className="searchbox searchbox--inline">
              <Icon name="search" size={16} />
              <input className="input" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder={t("admin.sessions.search")} aria-label={t("admin.sessions.search")} />
            </div>
          </div>
        </div>

        {error && !data ? (
          <LoadError error={error} onRetry={reload} t={t} />
        ) : loading && !data ? (
          <SkeletonRows rows={5} />
        ) : rows.length ? (
          <div className="table-wrap">
            <table className="data data--stack">
              <thead>
                <tr>
                  <th scope="col">{t("admin.sessions.colUser")}</th>
                  <th scope="col">{t("admin.sessions.colDevice")}</th>
                  <th scope="col">{t("admin.sessions.colIp")}</th>
                  <th scope="col">{t("admin.sessions.colStarted")}</th>
                  <th scope="col">{t("admin.sessions.colSeen")}</th>
                  <th scope="col">{t("admin.sessions.colExpires")}</th>
                  <th scope="col" className="num"><span className="sr-only">{t("admin.sessions.revoke")}</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id}>
                    <td data-label={t("admin.sessions.colUser")}>
                      <UserCell
                        user={{ name: s.user_name, email: s.user_email, accent: "violet" }}
                        t={t}
                        onOpen={() => navigate(`/admin/users/${s.user_id}`)}
                      />
                    </td>
                    <td data-label={t("admin.sessions.colDevice")}>
                      <span className="device">
                        <Icon name={device(s.user_agent).icon} size={16} />
                        <span className="cell-stack">
                          <span>{deviceLabel(s.user_agent, t)}</span>
                          <span className="tiny muted">
                            <RoleBadge role={s.user_role} t={t} />
                            {s.current ? <span className="you-tag">{t("admin.sessions.thisDevice")}</span> : null}
                            {s.remember ? <span className="tiny muted"> · {t("admin.sessions.remembered")}</span> : null}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td className="mono muted" data-label={t("admin.sessions.colIp")}>{s.ip || "—"}</td>
                    <td className="muted" data-label={t("admin.sessions.colStarted")} title={stamp(s.created_at, locale)}>
                      {relativeTime(s.created_at, t, locale)}
                    </td>
                    <td data-label={t("admin.sessions.colSeen")} title={stamp(s.last_seen_at, locale)}>
                      {relativeTime(s.last_seen_at, t, locale)}
                    </td>
                    <td className="muted" data-label={t("admin.sessions.colExpires")}>{stamp(s.expires_at, locale)}</td>
                    <td className="num cell-actions">
                      {s.current ? null : (
                        <button type="button" className="btn btn--sm" onClick={() => revoke(s)} disabled={busy === s.id}
                          {...(busy === s.id ? { "data-busy": "" } : {})}>
                          <Icon name="logout" size={14} /> {t("admin.sessions.revoke")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            <span className="empty__art">
              <Icon name="monitor" size={28} strokeWidth={1.5} />
            </span>
            <h3>{t("admin.sessions.empty")}</h3>
          </div>
        )}
      </section>
    </>
  );
}
