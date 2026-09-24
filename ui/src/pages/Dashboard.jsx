/* The overview. Every figure here is computed from the review log -- the
   server's own, when the backend is up -- so the tiles, the throughput chart,
   the assessment mix and the recent-sign-offs table always agree with each
   other and with the Case log. Nothing on this page is a hardcoded number. */

import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { ConcordBadge, ScoreBadge } from "../components/Badges.jsx";
import { ClassBars, ColumnChart, Donut, Sparkline, StackBar } from "../components/charts/Charts.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { avatarStyle, useAuth } from "../state/AuthContext.jsx";
import {
  classForLabel,
  dailyCounts,
  dominantClass,
  greetingKey,
  initials,
  isCannotAssess,
  LABEL_ORDER,
  labelForClassName,
  pct,
  periodCounts,
  relativeTime,
  runName,
  shortId,
} from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";

export default function Dashboard() {
  const { context, reviews, reviewsDemo, analysis } = usePortal();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t, locale } = useI18n();
  const classes = context?.classes ?? [];

  const stats = useMemo(() => {
    const total = reviews.length;
    const agreed = reviews.filter((r) => r.agrees).length;
    const flagged = total - agreed;
    const unassessable = reviews.filter((r) => isCannotAssess(r.score)).length;
    const mine = reviews.filter((r) => r.reviewer === user.name).length;
    return {
      total,
      agreed,
      flagged,
      unassessable,
      mine,
      concordance: total ? (agreed / total) * 100 : 0,
      week: periodCounts(reviews, 7),
      days: dailyCounts(reviews, 14),
    };
  }, [reviews, user.name]);

  // How the recorded pathologist assessments distribute across scores. This is
  // the reviewers' own tally, not the model's -- the model does not produce a
  // score, so it has no distribution to plot here.
  const distribution = useMemo(
    () => [
      ...LABEL_ORDER.map((label) => ({
        key: label,
        label,
        count: reviews.filter((r) => r.score === label).length,
        color: classForLabel(classes, label)?.color ?? "var(--accent)",
      })),
      {
        key: "cannot",
        label: t("analysis.cannotAssess"),
        count: stats.unassessable,
        color: "var(--text-3)",
      },
    ],
    [reviews, classes, stats.unassessable, t],
  );

  const recent = reviews.slice(0, 6);
  const shortDay = (d) => d.toLocaleDateString(locale, { day: "numeric", month: "short" });

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">
            {new Date().toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })}
          </div>
          <h1>
            {t(greetingKey())}, {user.name}
          </h1>
          <p className="lede">
            {stats.total === 0
              ? t("dash.ledeNone")
              : t(stats.total === 1 ? "dash.ledeOne" : "dash.lede", {
                  n: stats.total,
                  pct: pct(stats.concordance, 0),
                })}
          </p>
        </div>
        <div className="page__actions">
          <Link className="btn" to="/cases">
            <Icon name="clipboard" size={16} /> {t("dash.caseLog")}
          </Link>
          <Link className="btn btn--primary" to="/analysis">
            <Icon name="scan" size={16} /> {t("dash.analyseField")}
          </Link>
        </div>
      </div>

      <div className="grid-kpi stagger">
        <Kpi
          icon="clipboard"
          label={t("dash.kpiReviewed")}
          value={stats.total}
          trend={<Sparkline values={stats.days.map((d) => d.count)} width={96} height={34} />}
          foot={<Delta delta={stats.week.delta} text={t("dash.kpiDelta", { n: stats.week.current })} />}
        />
        <Kpi
          icon="checkCircle"
          label={t("dash.kpiConcordant")}
          value={pct(stats.concordance, 0)}
          meter={stats.concordance}
          foot={t("dash.kpiConcordantFoot", { a: stats.agreed, b: stats.total })}
        />
        <Kpi
          icon="alert"
          tone="warn"
          label={t("dash.kpiFlagged")}
          value={stats.flagged}
          foot={t("dash.kpiFlaggedFoot")}
        />
        <Kpi
          icon="eye"
          tone="muted"
          label={t("dash.kpiUnassessable")}
          value={stats.unassessable}
          foot={t("dash.kpiUnassessableFoot")}
        />
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <Bench analysis={analysis} classes={classes} t={t} navigate={navigate} />

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.throughput")}</h2>
                <p className="sub">{t("dash.throughputSub")}</p>
              </div>
              <span className="badge badge--outline">
                <Icon name="activity" size={12} /> {t("dash.throughputTotal", { n: stats.days.reduce((s, d) => s + d.count, 0) })}
              </span>
            </div>
            <ColumnChart data={stats.days} formatDay={shortDay} emptyLabel={t("dash.throughputEmpty")} />
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.recent")}</h2>
                <p className="sub">{t(reviewsDemo ? "dash.recentSubDemo" : "dash.recentSub")}</p>
              </div>
              <Link className="btn btn--ghost btn--sm" to="/cases">
                {t("dash.viewAll")} <Icon name="arrowRight" size={14} />
              </Link>
            </div>

            {recent.length ? (
              <div className="table-wrap">
                <table className="data data--stack data--compact">
                  <thead>
                    <tr>
                      <th scope="col">{t("table.field")}</th>
                      <th scope="col">{t("table.assessment")}</th>
                      <th scope="col">{t("table.reviewer")}</th>
                      <th scope="col">{t("table.concordant")}</th>
                      <th scope="col" className="num">{t("table.when")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((r) => (
                      <tr key={r.id} className={r.agrees ? undefined : "is-flagged"}>
                        <td data-label={t("table.field")}>
                          <span className="cell-stack">
                            <span className="mono cell-id" title={r.patch_id}>{shortId(r.patch_id)}</span>
                            <span className="tiny muted">
                              {t("table.datasetLabel")}: {r.dataset_label ?? "—"}
                            </span>
                          </span>
                        </td>
                        <td data-label={t("table.assessment")}>
                          <ScoreBadge score={r.score} classes={classes} t={t} />
                        </td>
                        <td data-label={t("table.reviewer")}>
                          <span className="who" title={r.reviewer}>
                            <span className="avatar avatar--sm" aria-hidden="true">{initials(r.reviewer)}</span>
                            <span className="who__name">{r.reviewer}</span>
                          </span>
                        </td>
                        <td data-label={t("table.concordant")}>
                          <ConcordBadge agrees={r.agrees} t={t} />
                        </td>
                        <td className="num muted tiny nowrap" data-label={t("table.when")}>
                          {relativeTime(r.at, t, locale)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="hint">{t("dash.noneRecorded")}</p>
            )}
          </section>
        </div>

        {/* ------------------------------------------------------- rail --- */}
        <div className="dash-col">
          <section className="card card--pad rise profile-card">
            <div className="profile-card__who">
              <span className="avatar avatar--lg" style={avatarStyle(user.accent)}>
                {initials(user.name)}
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="profile-card__name">{user.name}</div>
                <div className="tiny muted">{t(user.roleKey ?? "demo.role")}</div>
              </div>
            </div>
            <p className="tiny muted">{t(user.deptKey ?? "demo.department")}</p>
            <div className="profile-card__stats">
              <div>
                <b>{stats.mine}</b>
                <span>{t("dash.yours")}</span>
              </div>
              <div>
                <b>{stats.total}</b>
                <span>{t("dash.team")}</span>
              </div>
              <div>
                <b>{stats.week.current}</b>
                <span>{t("dash.thisWeek")}</span>
              </div>
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.mix")}</h2>
                <p className="sub">{t("dash.mixSub")}</p>
              </div>
            </div>
            <ClassBars rows={distribution} />
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.concordance")}</h2>
                <p className="sub">{t("dash.concordanceSub")}</p>
              </div>
            </div>
            <div className="concord">
              <Donut value={stats.concordance} size={92} stroke={10} label={t("dash.concordance")} />
              <p className="hint">{t("dash.concordanceNote")}</p>
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.deployment")}</h2>
                <p className="sub">{t("dash.deploymentSub")}</p>
              </div>
              <Link className="btn btn--ghost btn--sm" to="/model">
                {t("nav.model")} <Icon name="arrowRight" size={14} />
              </Link>
            </div>
            <dl className="spec-list spec-list--tight">
              <div>
                <dt>{t("common.run")}</dt>
                <dd className="mono" title={context?.provenance?.run}>
                  {context?.provenance?.run ? runName(context.provenance.run) : "—"}
                </dd>
              </div>
              <div>
                <dt>{t("common.epoch")}</dt>
                <dd className="mono">{context?.provenance?.epoch ?? "—"}</dd>
              </div>
              <div>
                <dt>{t("common.architecture")}</dt>
                <dd className="mono">{context?.provenance?.architecture?.toUpperCase() ?? "—"}</dd>
              </div>
              <div>
                <dt>{t("dash.source")}</dt>
                <dd>
                  <span className="status">
                    <span className="pulse-dot" data-tone={context?.demo ? "warn" : "ok"} />
                    {t(context?.demo ? "dash.sourceDemo" : "dash.sourceLive")}
                  </span>
                </dd>
              </div>
            </dl>
          </section>
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------- pieces --- */

function Bench({ analysis, classes, t, navigate }) {
  if (!analysis) {
    return (
      <section className="card card--pad rise">
        <div className="card-head">
          <div>
            <h2>{t("dash.benchOff")}</h2>
            <p className="sub">{t("dash.benchSubOff")}</p>
          </div>
        </div>
        <div className="empty" style={{ padding: "26px 16px" }}>
          <span className="empty__art">
            <Icon name="slides" size={28} strokeWidth={1.5} />
          </span>
          <p>{t("dash.benchEmpty")}</p>
          <button type="button" className="btn btn--primary" onClick={() => navigate("/analysis")}>
            <Icon name="scan" size={16} /> {t("dash.chooseField")}
          </button>
        </div>
      </section>
    );
  }

  // The same "what does the data say this field is, and how much of that is
  // here" framing as the Analysis page's Key Result -- the largest-area class
  // only stands in when there is no dataset label to key off.
  const labelled = analysis.dataset_label ? classForLabel(classes, analysis.dataset_label) : null;
  const fallback = labelled ? null : dominantClass(analysis.model_percentages);
  const focus = labelled ?? classes.find((c) => c.name === fallback?.[0]) ?? null;
  const focusLabel = focus ? labelForClassName(classes, focus.name) : null;
  const image = (focus && analysis.isolate?.[focus.name]) || analysis.images?.model;

  return (
    <section className="card bench rise">
      <div className="bench__media">
        {image ? <img src={image} alt={t("analysis.views.isolate", { label: focusLabel ?? "" })} /> : null}
        {focusLabel ? <span className="bench__chip">{t("analysis.views.isolate", { label: focusLabel })}</span> : null}
      </div>
      <div className="bench__body">
        <div className="card-head" style={{ marginBottom: 6 }}>
          <div style={{ minWidth: 0 }}>
            <h2>{t("dash.benchOn")}</h2>
            <p className="sub mono" title={analysis.patch_id}>
              {shortId(analysis.patch_id)} · {analysis.width}×{analysis.height}
            </p>
          </div>
          <Link className="btn btn--soft btn--sm" to="/analysis">
            {t("dash.open")} <Icon name="arrowRight" size={14} />
          </Link>
        </div>

        <div className="eyebrow">
          {analysis.dataset_label
            ? t("analysis.sourceLabel", { label: analysis.dataset_label })
            : t("dash.largestClass")}
        </div>
        <div className="bench__figure">
          <b style={{ "--mark": focus?.color }}>{focusLabel ?? "—"}</b>
          <span>
            {t("dash.measurementNotScore", { pct: pct(analysis.model_percentages?.[focus?.name]) })}
          </span>
        </div>

        <StackBar
          segments={classes
            .filter((c) => c.index > 0)
            .map((c) => ({ label: c.name, value: analysis.model_percentages?.[c.name] ?? 0, color: c.color }))}
          height={10}
        />
        <div className="legend legend--plain">
          {classes
            .filter((c) => c.index > 0)
            .map((c) => (
              <span key={c.name}>
                <i style={{ background: c.color }} />
                {c.name} <b className="num">{pct(analysis.model_percentages?.[c.name] ?? 0)}</b>
              </span>
            ))}
        </div>
      </div>
    </section>
  );
}

function Kpi({ icon, label, value, foot, trend, meter, tone }) {
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
      {meter != null ? (
        <div className="meter" aria-hidden="true">
          <span style={{ width: `${Math.max(0, Math.min(100, meter))}%` }} />
        </div>
      ) : null}
      <div className="kpi__foot">{foot}</div>
    </article>
  );
}

function Delta({ delta, text }) {
  const tone = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return (
    <>
      <span className={`trend trend--${tone}`}>
        <Icon name={delta < 0 ? "arrowDown" : "arrowUp"} size={12} />
        {delta > 0 ? `+${delta}` : delta}
      </span>
      <span>{text}</span>
    </>
  );
}
