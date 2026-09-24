import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { ConcordBadge, ScoreBadge } from "../components/Badges.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { dateTime, initials, isCannotAssess, pct, shortId } from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";

/* A seeded demo row carries a string key; a row the pathologist actually
   typed carries their own words, which are never translated. */
const noteOf = (r, t) => (r.noteKey ? t(r.noteKey) : r.notes || "");

const FILTERS = [
  { id: "all", key: "cases.all" },
  { id: "flagged", key: "cases.flagged" },
  { id: "concordant", key: "cases.concordant" },
  { id: "unassessable", key: "cases.unassessable" },
];

export default function Cases() {
  const { reviews, reviewsDemo, context } = usePortal();
  const { t, locale } = useI18n();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("all");
  const query = params.get("q") ?? "";
  const classes = context?.classes ?? [];

  const counts = useMemo(
    () => ({
      all: reviews.length,
      flagged: reviews.filter((r) => !r.agrees).length,
      concordant: reviews.filter((r) => r.agrees).length,
      unassessable: reviews.filter((r) => isCannotAssess(r.score)).length,
    }),
    [reviews],
  );

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return reviews.filter((r) => {
      if (filter === "flagged" && r.agrees) return false;
      if (filter === "concordant" && !r.agrees) return false;
      if (filter === "unassessable" && !isCannotAssess(r.score)) return false;
      if (!needle) return true;
      return [r.patch_id, r.reviewer, noteOf(r, t), r.score]
        .filter(Boolean)
        .some((field) => field.toLowerCase().includes(needle));
    });
  }, [reviews, filter, query, t]);

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("cases.eyebrow")}</div>
          <h1>{t("cases.title")}</h1>
          <p className="lede">
            {t("cases.lede", { path: "/api/review" })}
          </p>
        </div>
        <div className="page__actions">
          <Link className="btn btn--primary" to="/analysis">
            <Icon name="scan" size={16} /> {t("dash.analyseField")}
          </Link>
        </div>
      </div>

      <section className="card card--pad">
        <div className="card-head" style={{ flexWrap: "wrap" }}>
          <div className="seg" role="tablist" aria-label={t("cases.filterLabel")}>
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={filter === f.id}
                className={`seg__btn${filter === f.id ? " is-active" : ""}`}
                onClick={() => setFilter(f.id)}
              >
                {t(f.key)}
                <span className="seg__count">{counts[f.id]}</span>
              </button>
            ))}
          </div>
          {reviewsDemo ? (
            <span className="badge badge--warn">
              <span className="dot" /> {t("cases.demoRows")}
            </span>
          ) : null}

          <div className="searchbox searchbox--inline">
            <Icon name="search" size={16} />
            <input
              className="input"
              type="search"
              value={query}
              placeholder={t("cases.search")}
              aria-label={t("cases.searchLabel")}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                if (e.target.value) next.set("q", e.target.value);
                else next.delete("q");
                setParams(next, { replace: true });
              }}
            />
          </div>
        </div>

        {rows.length ? (
          <div className="table-wrap">
            <table className="data data--stack">
              <thead>
                <tr>
                  <th scope="col">{t("table.field")}</th>
                  <th scope="col">{t("table.assessment")}</th>
                  <th scope="col">{t("table.datasetLabel")}</th>
                  <th scope="col" className="num">{t("table.tissue")}</th>
                  <th scope="col">{t("table.reviewer")}</th>
                  <th scope="col">{t("table.concordant")}</th>
                  <th scope="col">{t("table.notes")}</th>
                  <th scope="col">{t("table.recorded")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={r.agrees ? undefined : "is-flagged"}>
                    <td className="mono cell-id" data-label={t("table.field")} title={r.patch_id}>
                      {shortId(r.patch_id)}
                    </td>
                    <td data-label={t("table.assessment")}>
                      <ScoreBadge score={r.score} classes={classes} t={t} />
                    </td>
                    <td className="muted" data-label={t("table.datasetLabel")}>{r.dataset_label ?? "—"}</td>
                    <td className="num" data-label={t("table.tissue")}>
                      {r.tissue_percent != null ? pct(r.tissue_percent) : "—"}
                    </td>
                    <td data-label={t("table.reviewer")}>
                      <span className="who">
                        <span className="avatar avatar--sm">{initials(r.reviewer)}</span>
                        <span className="who__name">{r.reviewer}</span>
                      </span>
                    </td>
                    <td data-label={t("table.concordant")}>
                      <ConcordBadge agrees={r.agrees} t={t} />
                    </td>
                    <td className="muted" style={{ maxWidth: 260 }} data-label={t("table.notes")} data-block="">
                      {noteOf(r, t) || <span style={{ opacity: 0.45 }}>—</span>}
                    </td>
                    <td className="muted tiny" style={{ whiteSpace: "nowrap" }} data-label={t("table.recorded")}>
                      {dateTime(r.at, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            <span className="empty__art">
              <Icon name="clipboard" size={28} strokeWidth={1.5} />
            </span>
            <h3>{t("cases.emptyTitle")}</h3>
            <p>{t("cases.emptyBody")}</p>
          </div>
        )}
      </section>

      <p className="footer-note" dangerouslySetInnerHTML={{ __html: t("cases.footnote") }} />
    </>
  );
}
