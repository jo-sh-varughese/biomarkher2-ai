/* The audit log: every sign-in, account change, setting change and export,
   newest first, with who did it, to whom, and from which address. Filters
   run on the server, which pages through the log 100 events at a time;
   "Export CSV" downloads exactly the filtered view. */

import { useEffect, useState } from "react";
import Icon from "../../components/Icon.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { relativeTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import { LoadError, PageHead, SkeletonRows, eventDetail, eventLabel, eventLook, stamp, useAdmin } from "./shared.jsx";

const CATEGORIES = ["all", "signin", "accounts", "security", "settings", "data"];
const RANGES = [
  ["d1", 1],
  ["d7", 7],
  ["d30", 30],
  ["all", 0],
];

export default function Audit() {
  const { api } = useAdmin();
  const { t, locale } = useI18n();
  const toast = useToast();
  const [category, setCategory] = useState("all");
  const [days, setDays] = useState(7);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [events, setEvents] = useState([]);
  const [next, setNext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query), 280);
    return () => clearTimeout(timer);
  }, [query]);

  const params = {
    category: category === "all" ? "" : category,
    days: days || "",
    q: debounced,
  };

  const load = async (before) => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.audit({ ...params, before, limit: 100 });
      setEvents((current) => (before ? [...current, ...page.events] : page.events));
      setNext(page.next);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .audit({ category: category === "all" ? "" : category, days: days || "", q: debounced, limit: 100 })
      .then((page) => {
        if (cancelled) return;
        setEvents(page.events);
        setNext(page.next);
      })
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [api, category, days, debounced]);

  const exportCsv = async () => {
    try {
      await api.exportFile("audit", params);
      toast.ok(t("admin.system.exported"));
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    }
  };

  return (
    <>
      <PageHead
        eyebrow={t("admin.eyebrow")}
        title={t("admin.audit.title")}
        lede={t("admin.audit.lede")}
        actions={
          <button type="button" className="btn" onClick={exportCsv}>
            <Icon name="download" size={16} /> {t("admin.audit.export")}
          </button>
        }
      />

      <section className="card card--pad">
        <div className="card-head toolbar">
          <div className="seg seg--scroll" role="tablist" aria-label={t("admin.audit.colEvent")}>
            {CATEGORIES.map((c) => (
              <button key={c} type="button" role="tab" aria-selected={category === c}
                className={`seg__btn${category === c ? " is-active" : ""}`} onClick={() => setCategory(c)}>
                {t(`admin.audit.categories.${c}`)}
              </button>
            ))}
          </div>
          <div className="toolbar__right">
            <select className="select select--sm" value={days} onChange={(e) => setDays(Number(e.target.value))}
              aria-label={t("admin.audit.colTime")}>
              {RANGES.map(([key, value]) => (
                <option key={key} value={value}>{t(`admin.audit.range.${key}`)}</option>
              ))}
            </select>
            <div className="searchbox searchbox--inline">
              <Icon name="search" size={16} />
              <input className="input" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder={t("admin.audit.search")} aria-label={t("admin.audit.search")} />
            </div>
          </div>
        </div>

        {error && !events.length ? (
          <LoadError error={error} onRetry={() => load()} t={t} />
        ) : loading && !events.length ? (
          <SkeletonRows rows={8} />
        ) : events.length ? (
          <>
            <div className="table-wrap">
              <table className="data data--stack data--audit">
                <thead>
                  <tr>
                    <th scope="col">{t("admin.audit.colTime")}</th>
                    <th scope="col">{t("admin.audit.colEvent")}</th>
                    <th scope="col">{t("admin.audit.colActor")}</th>
                    <th scope="col">{t("admin.audit.colTarget")}</th>
                    <th scope="col">{t("admin.audit.colIp")}</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => {
                    const { icon, tone } = eventLook(e.action);
                    const detail = eventDetail(e, t);
                    return (
                      <tr key={e.id}>
                        <td className="muted" data-label={t("admin.audit.colTime")} style={{ whiteSpace: "nowrap" }}
                          title={stamp(e.at, locale)}>
                          <span className="cell-stack">
                            <span>{stamp(e.at, locale)}</span>
                            <span className="tiny">{relativeTime(e.at, t, locale)}</span>
                          </span>
                        </td>
                        <td data-label={t("admin.audit.colEvent")}>
                          <span className="audit-event">
                            <span className={`event__icon tone-${tone}`} aria-hidden="true">
                              <Icon name={icon} size={14} />
                            </span>
                            <span className="cell-stack">
                              <b>{eventLabel(e, t)}</b>
                              {detail ? <span className="tiny muted">{detail}</span> : null}
                            </span>
                          </span>
                        </td>
                        <td data-label={t("admin.audit.colActor")}>
                          {e.actor ? (
                            <span className="cell-stack">
                              <span>{e.actor.name}</span>
                              <span className="tiny muted">{e.actor.email}</span>
                            </span>
                          ) : (
                            <span className="muted">
                              {e.action.startsWith("auth.login") || e.action.startsWith("access.") || e.action === "auth.locked"
                                ? t("admin.audit.anonymous")
                                : t("admin.audit.system")}
                            </span>
                          )}
                        </td>
                        <td className="muted" data-label={t("admin.audit.colTarget")}>{e.target?.email ?? "—"}</td>
                        <td className="mono muted" data-label={t("admin.audit.colIp")}>{e.ip || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="table-foot">
              <span>{t("admin.audit.showing", { n: events.length })}</span>
              {next ? (
                <button type="button" className="btn btn--sm" onClick={() => load(next)} disabled={loading}
                  {...(loading ? { "data-busy": "" } : {})}>
                  {t("admin.audit.loadMore")}
                </button>
              ) : null}
            </div>
          </>
        ) : (
          <div className="empty">
            <span className="empty__art">
              <Icon name="activity" size={28} strokeWidth={1.5} />
            </span>
            <h3>{t("admin.audit.empty")}</h3>
            <p>{t("admin.audit.emptyBody")}</p>
          </div>
        )}
      </section>
    </>
  );
}
