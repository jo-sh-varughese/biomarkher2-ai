import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { ConcordBadge, ScoreBadge } from "../components/Badges.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { fetchCases } from "../lib/api.js";
import { dateTime, initials, isCannotAssess, pct, shortId } from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";

/* The Case log. "Cases" is the case database: one row per field or slide,
   with the latest AI pre-score, cell evidence, stained tissue and sign-off;
   clicking a row opens everything on that case. "Sign-offs" is the review log
   itself, one row per signed review. A pathologist sees only their own cases
   and sign-offs; an administrator sees everyone's and can narrow to one
   person. The server decides that scope -- this page only renders it. */

const TABS = ["cases", "signoffs"];

export default function Cases() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const tab = TABS.includes(params.get("tab")) ? params.get("tab") : "cases";

  const setTab = (next) => {
    const p = new URLSearchParams(params);
    p.set("tab", next);
    p.delete("q");
    setParams(p, { replace: true });
  };

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("cases.eyebrow")}</div>
          <h1>{t("cases.title")}</h1>
        </div>
        <div className="page__actions">
          <Link className="btn btn--primary" to="/analysis">
            <Icon name="scan" size={16} /> {t("dash.analyseField")}
          </Link>
        </div>
      </div>

      <div className="seg seg--page" role="tablist" aria-label={t("cases.title")}>
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`seg__btn${tab === key ? " is-active" : ""}`}
            onClick={() => setTab(key)}
          >
            {t(key === "cases" ? "casedb.tabCases" : "casedb.tabSignoffs")}
          </button>
        ))}
      </div>

      {tab === "cases" ? <CaseList /> : <SignoffLog />}
    </>
  );
}

/* ------------------------------------------------------------ cases --- */

function CaseList() {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const person = params.get("person") ?? "";
  const query = params.get("q") ?? "";
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    let live = true;
    setError(null);
    fetchCases(isAdmin ? person : "")
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message || String(e)));
    return () => {
      live = false;
    };
  }, [person, isAdmin]);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = data?.cases ?? [];
    if (!needle) return list;
    return list.filter((c) =>
      [c.name, c.source, c.case_id, c.dataset_label, ...(c.people ?? []).map((p) => p.name)]
        .filter(Boolean)
        .some((f) => String(f).toLowerCase().includes(needle)),
    );
  }, [data, query]);

  if (error) {
    return (
      <section className="card card--pad">
        <p className="prescore__warning" role="alert">
          {t("casedb.unavailable")} <span className="tiny muted">({error})</span>
        </p>
      </section>
    );
  }

  return (
    <section className="card card--pad">
      <p className="lede caselist__lede">{data?.scope === "all" ? t("casedb.ledeAll") : t("casedb.ledeOwn")}</p>
      <div className="card-head" style={{ flexWrap: "wrap" }}>
        <span className={`badge ${data?.scope === "all" ? "badge--accent" : "badge--outline"}`}>
          <Icon name={data?.scope === "all" ? "users" : "user"} size={12} />{" "}
          {data?.scope === "all" ? t("casedb.scopeAll") : t("casedb.scopeOwn")}
        </span>
        {isAdmin && data?.people?.length ? (
          <label className="caselist__person">
            <span>{t("casedb.person")}</span>
            <select className="select" value={person} onChange={(e) => setParam("person", e.target.value)}>
              <option value="">{t("casedb.everyone")}</option>
              {data.people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="searchbox searchbox--inline">
          <Icon name="search" size={16} />
          <input
            className="input"
            type="search"
            value={query}
            placeholder={t("casedb.search")}
            aria-label={t("casedb.search")}
            onChange={(e) => setParam("q", e.target.value)}
          />
        </div>
      </div>

      {data === null ? (
        <div className="skeleton" style={{ height: 240, borderRadius: "var(--r-lg)" }} />
      ) : rows.length ? (
        <div className="table-wrap">
          <table className="data data--stack caselist">
            <thead>
              <tr>
                <th scope="col">{t("casedb.col.case")}</th>
                <th scope="col">{t("casedb.col.ai")}</th>
                <th scope="col">{t("casedb.col.cells")}</th>
                <th scope="col">{t("casedb.col.stain")}</th>
                <th scope="col">{t("casedb.col.review")}</th>
                <th scope="col">{t("casedb.col.people")}</th>
                <th scope="col">{t("casedb.col.updated")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const a = c.last_analysis;
                const r = c.last_review;
                const open = () => navigate(`/cases/${c.case_id}`);
                return (
                  <tr
                    key={c.case_id}
                    className="caselist__row"
                    tabIndex={0}
                    onClick={open}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        open();
                      }
                    }}
                  >
                    <td data-label={t("casedb.col.case")}>
                      <span className="caselist__case">
                        {c.thumbnail ? <img src={c.thumbnail} alt="" /> : <span className="caselist__nothumb" />}
                        <span>
                          <b className="caselist__name" title={c.source}>{c.name}</b>
                          <span className="tiny muted">
                            {t(`casedb.kind.${c.kind}`)} · <span className="mono">{shortId(c.case_id)}</span>
                            {c.dataset_label ? ` · ${t("casedb.datasetLabel")} ${c.dataset_label}` : ""}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td data-label={t("casedb.col.ai")}>
                      {a?.ai_shown && a.ai_category ? (
                        <ScoreBadge score={a.ai_category} classes={[]} t={t} />
                      ) : a ? (
                        <span className="muted tiny">{t("casedb.withheld")}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td data-label={t("casedb.col.cells")}>
                      {a?.cell_category ? (
                        <ScoreBadge score={a.cell_category} classes={[]} t={t} />
                      ) : a?.not_assessable ? (
                        <span className="badge badge--danger">{t("casedb.notAssessable")}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="num" data-label={t("casedb.col.stain")}>
                      <StainSummary stain={a?.stain} t={t} />
                    </td>
                    <td data-label={t("casedb.col.review")}>
                      {r ? (
                        <span className="caselist__review">
                          {r.score ? <ScoreBadge score={r.score} classes={[]} t={t} /> : null}
                          <span className={`review__status review__status--${r.status ?? "final"}`}>
                            {t(`review.status.${r.status ?? "final"}`)}
                            {r.version > 1 ? ` · v${r.version}` : ""}
                          </span>
                        </span>
                      ) : (
                        <span className="muted tiny">{t("casedb.notReviewed")}</span>
                      )}
                    </td>
                    <td data-label={t("casedb.col.people")}>
                      <span className="caselist__people">
                        {(c.people ?? []).slice(0, 3).map((p) => (
                          <span key={p.id} className="avatar avatar--sm" title={p.name}>
                            {initials(p.name)}
                          </span>
                        ))}
                        <span className="tiny muted">
                          {(c.people ?? []).map((p) => p.name).join(", ")}
                        </span>
                      </span>
                    </td>
                    <td className="muted tiny" style={{ whiteSpace: "nowrap" }} data-label={t("casedb.col.updated")}>
                      {dateTime(c.updated_at, locale)}
                      <div>
                        {t("casedb.analysesCount", { n: c.analyses })} · {t("casedb.reviewsCount", { n: c.reviews })}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">
          <span className="empty__art">
            <Icon name="clipboard" size={28} strokeWidth={1.5} />
          </span>
          <h3>{data?.cases?.length ? t("casedb.noMatch") : t("casedb.emptyTitle")}</h3>
          {data?.cases?.length ? null : <p>{t("casedb.emptyBody")}</p>}
        </div>
      )}
    </section>
  );
}

/* Stained tissue: a field's tissue share and its cells with any membrane
   staining (>= 1+); a slide has no single tissue %, so only the cells. */
export function cellsAtLeast1(percent) {
  if (!percent) return null;
  return ["1+", "2+", "3+"].reduce((sum, k) => sum + (Number(percent[k]) || 0), 0);
}

function StainSummary({ stain, t }) {
  if (!stain) return "—";
  const positive = cellsAtLeast1(stain.cell_percent);
  return (
    <span className="caselist__stain">
      {positive != null ? <b>{pct(positive)}</b> : null}
      {positive != null ? <span className="tiny muted"> ≥1+ cells</span> : null}
      {stain.tissue_percent != null ? (
        <div className="tiny muted">
          {t("casedb.tissue")} {pct(stain.tissue_percent)}
        </div>
      ) : null}
    </span>
  );
}

/* --------------------------------------------------------- sign-offs --- */

/* A seeded demo row carries a string key; a row the pathologist actually
   typed carries their own words, which are never translated. */
const noteOf = (r, t) => (r.noteKey ? t(r.noteKey) : r.notes || "");

const FILTERS = [
  { id: "all", key: "cases.all" },
  { id: "flagged", key: "cases.flagged" },
  { id: "concordant", key: "cases.concordant" },
  { id: "unassessable", key: "cases.unassessable" },
];

function SignoffLog() {
  const { reviews, reviewsDemo, context, reloadReviews } = usePortal();
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("all");
  const query = params.get("q") ?? "";
  const classes = context?.classes ?? [];

  useEffect(() => {
    reloadReviews?.();
  }, [reloadReviews]);

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
      return [r.patch_id, r.reviewer, noteOf(r, t), r.score, r.accession, r.ish_decision]
        .filter(Boolean)
        .some((field) => field.toLowerCase().includes(needle));
    });
  }, [reviews, filter, query, t]);

  return (
    <>
      <section className="card card--pad">
        <p className="lede caselist__lede">{t("cases.lede", { path: "/api/review" })}</p>
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
                  <th scope="col">{t("cases.statusCol")}</th>
                  <th scope="col">ISH</th>
                  <th scope="col">{t("table.datasetLabel")}</th>
                  <th scope="col">{t("table.reviewer")}</th>
                  <th scope="col">{t("table.concordant")}</th>
                  <th scope="col">{t("table.notes")}</th>
                  <th scope="col">{t("table.recorded")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const linked = /^case_[0-9a-f]{16}$/.test(r.case_id ?? "");
                  const classNames = [r.agrees ? "" : "is-flagged", linked ? "caselist__row" : ""].filter(Boolean).join(" ");
                  return (
                    <tr
                      key={r.id}
                      className={classNames || undefined}
                      {...(linked
                        ? { tabIndex: 0, onClick: () => navigate(`/cases/${r.case_id}`),
                            onKeyDown: (e) => e.key === "Enter" && navigate(`/cases/${r.case_id}`) }
                        : {})}
                    >
                      <td className="mono cell-id" data-label={t("table.field")} title={r.patch_id}>
                        {shortId(r.patch_id)}
                      </td>
                      <td data-label={t("table.assessment")}>
                        <ScoreBadge score={r.score} classes={classes} t={t} />
                      </td>
                      <td data-label={t("cases.statusCol")}>
                        <span className={`review__status review__status--${r.status ?? "final"}`}>
                          {t(`review.status.${r.status ?? "final"}`)}
                          {r.version > 1 ? ` · v${r.version}` : ""}
                        </span>
                        {r.accession ? <div className="tiny muted mono">{r.accession}</div> : null}
                      </td>
                      <td className="muted" data-label="ISH">{r.ish_decision ?? "—"}</td>
                      <td className="muted" data-label={t("table.datasetLabel")}>{r.dataset_label ?? "—"}</td>
                      <td data-label={t("table.reviewer")}>
                        <span className="who">
                          <span className="avatar avatar--sm">{initials(r.reviewer)}</span>
                          <span className="who__name">{r.reviewer}</span>
                        </span>
                      </td>
                      <td data-label={t("table.concordant")}>
                        <ConcordBadge agrees={r.agrees} t={t} />
                      </td>
                      <td className="muted cases__note" data-label={t("table.notes")} data-block="" title={noteOf(r, t)}>
                        <span className="clamp2">{noteOf(r, t) || <span style={{ opacity: 0.45 }}>—</span>}</span>
                      </td>
                      <td className="muted tiny" style={{ whiteSpace: "nowrap" }} data-label={t("table.recorded")}>
                        {dateTime(r.at, locale)}
                      </td>
                    </tr>
                  );
                })}
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
