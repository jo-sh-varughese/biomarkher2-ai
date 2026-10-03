/* The admin console's landing page: the state of access at a glance, and
   the things that need an administrator today (access requests waiting,
   accounts locked out) actionable right here rather than two clicks away. */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../../components/Icon.jsx";
import { ClassBars, ColumnChart, Sparkline } from "../../components/charts/Charts.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { dailyCounts, relativeTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import { EventRow, LoadError, PageHead, SkeletonRows, UserCell, useAdmin, useLoad } from "./shared.jsx";

const ROLE_COLORS = { admin: "var(--accent)", pathologist: "#2dd4bf", viewer: "var(--text-3)" };

export default function Overview() {
  const { api, refreshBadge } = useAdmin();
  const { t, locale } = useI18n();
  const toast = useToast();
  const { data, error, loading, reload } = useLoad(() => api.overview(), [api]);
  const [roleFor, setRoleFor] = useState({});
  const [busyId, setBusyId] = useState(null);

  const days = useMemo(
    () => dailyCounts((data?.signins.last_14_days ?? []).map((at) => ({ at })), 14),
    [data],
  );
  const shortDay = (d) => d.toLocaleDateString(locale, { day: "numeric", month: "short" });

  const act = async (id, action, okKey) => {
    setBusyId(id);
    try {
      await action();
      toast.ok(t(okKey));
      await reload();
      refreshBadge();
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    } finally {
      setBusyId(null);
    }
  };

  const head = (
    <PageHead
      eyebrow={t("admin.eyebrow")}
      title={t("admin.overview.title")}
      lede={t("admin.overview.lede")}
      actions={
        <>
          <button type="button" className="btn" onClick={reload} disabled={loading}>
            <Icon name="refresh" size={16} /> {t("admin.refresh")}
          </button>
          <Link className="btn btn--primary" to="/admin/users?new=1">
            <Icon name="userPlus" size={16} /> {t("admin.overview.addUser")}
          </Link>
        </>
      }
    />
  );

  if (error && !data) {
    return (
      <>
        {head}
        <section className="card card--pad">
          <LoadError error={error} onRetry={reload} t={t} />
        </section>
      </>
    );
  }

  if (!data) {
    return (
      <>
        {head}
        <div className="grid-kpi">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="skeleton" style={{ height: 132, borderRadius: "var(--r-lg)" }} />
          ))}
        </div>
        <section className="card card--pad" style={{ marginTop: 20 }}>
          <SkeletonRows rows={4} />
        </section>
      </>
    );
  }

  const u = data.users;
  const roleRows = ["admin", "pathologist", "viewer"].map((role) => ({
    key: role,
    label: t(`roles.${role}`),
    count: u.by_role[role] ?? 0,
    color: ROLE_COLORS[role],
  }));
  const attention = [...data.pending.map((x) => ({ ...x, kind: "pending" })), ...data.locked.map((x) => ({ ...x, kind: "locked" }))];

  return (
    <>
      {head}

      <div className="grid-kpi stagger">
        <Kpi icon="users" label={t("admin.overview.kpiUsers")} value={u.by_status.active ?? 0}
          foot={t("admin.overview.kpiUsersFoot", { n: u.total })} />
        <Kpi icon="monitor" label={t("admin.overview.kpiOnline")} value={data.sessions.users_online}
          foot={t("admin.overview.kpiOnlineFoot", { n: data.sessions.active })} />
        <Kpi icon="login" label={t("admin.overview.kpiSignins")} value={data.signins.week}
          trend={<Sparkline values={days.map((d) => d.count)} width={96} height={34} />}
          foot={t("admin.overview.kpiSigninsFoot", { n: data.signins.failed_week })}
          tone={data.signins.failed_week > 5 ? "warn" : undefined} />
        <Kpi icon="userPlus" label={t("admin.overview.kpiPending")} value={data.pending.length}
          tone={data.pending.length ? "warn" : "muted"}
          foot={<Link to="/admin/users?status=pending">{t("admin.overview.kpiPendingFoot")} →</Link>} />
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("admin.overview.signins")}</h2>
                <p className="sub">{t("admin.overview.signinsSub")}</p>
              </div>
              <span className="badge badge--outline">
                <Icon name="activity" size={12} /> {t("admin.overview.signinsTotal", { n: data.signins.last_14_days.length })}
              </span>
            </div>
            <ColumnChart data={days} formatDay={shortDay} emptyLabel={t("admin.overview.signinsEmpty")} />
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("admin.overview.recent")}</h2>
                <p className="sub">{t("admin.overview.recentSub")}</p>
              </div>
              <Link className="btn btn--ghost btn--sm" to="/admin/audit">
                {t("admin.overview.viewAll")} <Icon name="arrowRight" size={14} />
              </Link>
            </div>
            {data.recent.length ? (
              <ul className="event-list">
                {data.recent.map((event) => (
                  <EventRow key={event.id} event={event} t={t} locale={locale} />
                ))}
              </ul>
            ) : (
              <p className="hint">{t("admin.audit.empty")}</p>
            )}
          </section>
        </div>

        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("admin.overview.attention")}</h2>
                <p className="sub">{t("admin.overview.attentionSub")}</p>
              </div>
              {attention.length ? <span className="count count--warn">{attention.length}</span> : null}
            </div>
            {attention.length ? (
              <ul className="attention">
                {attention.map((item) => (
                  <li key={`${item.kind}-${item.id}`} className="attention__item">
                    <UserCell user={item} t={t} />
                    <p className="attention__why">
                      <Icon name={item.kind === "pending" ? "userPlus" : "lock"} size={13} />
                      {item.kind === "pending"
                        ? t("admin.overview.requested", { when: relativeTime(item.created_at, t, locale) })
                        : t("admin.overview.lockedUntil", {
                            time: new Date(item.locked_until).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }),
                          })}
                    </p>
                    {item.kind === "pending" && item.request_note ? (
                      <blockquote className="attention__note">{item.request_note}</blockquote>
                    ) : null}
                    <div className="attention__actions">
                      {item.kind === "pending" ? (
                        <>
                          <select
                            className="select select--sm"
                            aria-label={t("admin.form.role")}
                            value={roleFor[item.id] ?? "pathologist"}
                            onChange={(e) => setRoleFor((r) => ({ ...r, [item.id]: e.target.value }))}
                          >
                            {["pathologist", "viewer", "admin"].map((role) => (
                              <option key={role} value={role}>{t(`roles.${role}`)}</option>
                            ))}
                          </select>
                          <button type="button" className="btn btn--primary btn--sm" disabled={busyId === item.id}
                            onClick={() => act(item.id, () => api.approve(item.id, roleFor[item.id] ?? "pathologist"), "admin.drawer.approved")}>
                            <Icon name="check" size={14} /> {t("admin.overview.approve")}
                          </button>
                          <button type="button" className="btn btn--ghost btn--sm" disabled={busyId === item.id}
                            onClick={() => act(item.id, () => api.deleteUser(item.id), "admin.drawer.rejected")}>
                            {t("admin.overview.reject")}
                          </button>
                        </>
                      ) : (
                        <button type="button" className="btn btn--sm" disabled={busyId === item.id}
                          onClick={() => act(item.id, () => api.unlock(item.id), "admin.drawer.unlocked")}>
                          <Icon name="unlock" size={14} /> {t("admin.overview.unlock")}
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="all-clear">
                <Icon name="checkCircle" size={18} /> {t("admin.overview.attentionEmpty")}
              </div>
            )}
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("admin.overview.roles")}</h2>
                <p className="sub">{t("admin.overview.rolesSub")}</p>
              </div>
            </div>
            <ClassBars rows={roleRows} />
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("admin.overview.health")}</h2>
              </div>
            </div>
            <dl className="spec-list health-list">
              {[
                ["mustChange", u.must_change_password, "key"],
                ["neverSignedIn", u.never_signed_in, "clock"],
                ["locked", u.locked, "lock"],
                ["disabled", u.by_status.disabled ?? 0, "ban"],
              ].map(([key, n, icon]) => (
                <div key={key}>
                  <dt><Icon name={icon} size={14} /> {t(`admin.overview.${key}`)}</dt>
                  <dd className={n ? "num strong" : "num muted"}>{n}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </div>
    </>
  );
}

function Kpi({ icon, label, value, foot, trend, tone }) {
  return (
    <article className={`card kpi${tone ? ` kpi--${tone}` : ""}`}>
      <div className="kpi__top">
        <span className="kpi__icon">
          <Icon name={icon} size={17} />
        </span>
        <div className="kpi__label">{label}</div>
      </div>
      <div className="kpi__mid">
        <div className="kpi__value">{value}</div>
        {trend}
      </div>
      <div className="kpi__foot">{foot}</div>
    </article>
  );
}
