import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { ColumnChart, Donut, Sparkline, StackBar } from "../components/charts/Charts.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { avatarStyle, useAuth } from "../state/AuthContext.jsx";
import { DEMO_THROUGHPUT } from "../lib/demo.js";
import { classColor, dominantClass, greetingKey, initials, pct, relativeTime } from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";

export default function Dashboard() {
  const { context, reviews, analysis } = usePortal();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t, locale } = useI18n();

  const stats = useMemo(() => {
    const total = reviews.length;
    const agreed = reviews.filter((r) => r.agrees).length;
    const flagged = reviews.filter((r) => !r.agrees).length;
    const unassessable = reviews.filter((r) => r.score === "Cannot assess").length;
    return {
      total,
      agreed,
      flagged,
      unassessable,
      concordance: total ? (agreed / total) * 100 : 0,
    };
  }, [reviews]);

  // How the recorded pathologist assessments distribute across scores. This is
  // the reviewers' own tally, not the model's -- the model does not produce a
  // score, so it has no distribution to plot here.
  const distribution = useMemo(() => {
    const buckets = ["0", "1+", "2+", "3+", "Cannot assess"];
    return buckets.map((label) => ({
      label: label === "Cannot assess" ? t("analysis.cannotAssess") : label,
      count: reviews.filter((r) => r.score === label).length,
      color:
        classColor(context?.classes, `HER2 ${label}`, null) ??
        (label === "Cannot assess" ? "var(--line-strong)" : "var(--accent)"),
    }));
  }, [reviews, context, t]);

  const maxBucket = Math.max(1, ...distribution.map((d) => d.count));
  const recent = reviews.slice(0, 6);

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{new Date().toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })}</div>
          <h1>
            {t(greetingKey())}, {user.name}
          </h1>
          <p className="lede">
            {t(stats.total === 1 ? "dash.ledeOne" : "dash.lede", {
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
          foot={<><span className="trend trend--up"><Icon name="arrowUp" size={12} /> 14</span> {t("dash.kpiReviewedFoot")}</>}
        />
        <Kpi
          icon="checkCircle"
          label={t("dash.kpiConcordant")}
          value={pct(stats.concordance, 0)}
          foot={t("dash.kpiConcordantFoot", { a: stats.agreed, b: stats.total })}
        />
        <Kpi
          icon="alert"
          label={t("dash.kpiFlagged")}
          value={stats.flagged}
          foot={t("dash.kpiFlaggedFoot")}
        />
        <Kpi
          icon="eye"
          label={t("dash.kpiUnassessable")}
          value={stats.unassessable}
          foot={t("dash.kpiUnassessableFoot")}
        />
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          {/* --- current field, or a prompt to load one --- */}
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t(analysis ? "dash.benchOn" : "dash.benchOff")}</h2>
                <p className="sub">
                  {analysis
                    ? t("dash.benchSubOn", { id: analysis.patch_id, w: analysis.width, h: analysis.height })
                    : t("dash.benchSubOff")}
                </p>
              </div>
              <Link className="btn btn--soft btn--sm" to="/analysis">
                {t(analysis ? "dash.open" : "dash.start")} <Icon name="arrowRight" size={14} />
              </Link>
            </div>

            {analysis ? (
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 260px", gap: 22, alignItems: "center" }}>
                <div style={{ display: "grid", gap: 16 }}>
                  <div>
                    <div className="eyebrow">{t("dash.largestClass")}</div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 4 }}>
                      <b
                        style={{
                          fontSize: "2.2rem",
                          fontWeight: 800,
                          letterSpacing: "-0.05em",
                          color: classColor(context?.classes, dominantClass(analysis.model_percentages)?.[0]),
                        }}
                      >
                        {dominantClass(analysis.model_percentages)?.[0]?.replace("HER2 ", "")}
                      </b>
                      <span className="muted tiny">
                        {t("dash.measurementNotScore", {
                          pct: pct(dominantClass(analysis.model_percentages)?.[1]),
                        })}
                      </span>
                    </div>
                  </div>

                  <StackBar
                    segments={(context?.classes ?? [])
                      .filter((c) => c.index > 0)
                      .map((c) => ({
                        label: c.name,
                        value: analysis.model_percentages?.[c.name] ?? 0,
                        color: c.color,
                      }))}
                    height={14}
                  />

                  <div className="legend">
                    {(context?.classes ?? [])
                      .filter((c) => c.index > 0)
                      .map((c) => (
                        <span key={c.name}>
                          <i style={{ background: c.color }} />
                          {c.name} · {pct(analysis.model_percentages?.[c.name] ?? 0)}
                        </span>
                      ))}
                  </div>
                </div>

                <img
                  src={analysis.images.model}
                  alt={t("analysis.views.model")}
                  style={{ borderRadius: "var(--r-md)", boxShadow: "var(--shadow-sm)", width: "100%" }}
                />
              </div>
            ) : (
              <div className="empty" style={{ padding: "32px 16px" }}>
                <span className="empty__art">
                  <Icon name="slides" size={28} strokeWidth={1.5} />
                </span>
                <p>
                  {t("dash.benchEmpty")}
                </p>
                <button type="button" className="btn btn--primary" onClick={() => navigate("/analysis")}>
                  <Icon name="scan" size={16} /> {t("dash.chooseField")}
                </button>
              </div>
            )}
          </section>

          {/* --- throughput --- */}
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.throughput")}</h2>
                <p className="sub">{t("dash.throughputSub")}</p>
              </div>
              <span className="badge badge--outline">
                <Icon name="activity" size={12} /> 14d
              </span>
            </div>
            <ColumnChart data={DEMO_THROUGHPUT} />
          </section>

          {/* --- recent --- */}
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.recent")}</h2>
                <p className="sub">{t("dash.recentSub")}</p>
              </div>
              <Link className="btn btn--ghost btn--sm" to="/cases">
                {t("dash.viewAll")} <Icon name="arrowRight" size={14} />
              </Link>
            </div>

            {recent.length ? (
              <div className="table-wrap">
                <table className="data data--stack">
                  <thead>
                    <tr>
                      <th scope="col">{t("table.field")}</th>
                      <th scope="col">{t("table.assessment")}</th>
                      <th scope="col">{t("table.datasetLabel")}</th>
                      <th scope="col">{t("table.reviewer")}</th>
                      <th scope="col">{t("table.concordant")}</th>
                      <th scope="col">{t("table.when")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((r) => (
                      <tr key={r.id} className={r.agrees ? undefined : "is-flagged"}>
                        <td className="mono" data-label={t("table.field")}>{r.patch_id}</td>
                        <td data-label={t("table.assessment")}>
                          <span className="badge badge--accent">{r.score}</span>
                        </td>
                        <td className="muted" data-label={t("table.datasetLabel")}>{r.dataset_label ?? "—"}</td>
                        <td data-label={t("table.reviewer")}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                            <span className="avatar avatar--sm">{initials(r.reviewer)}</span>
                            {r.reviewer}
                          </span>
                        </td>
                        <td data-label={t("table.concordant")}>
                          {r.agrees ? (
                            <span className="badge badge--ok">
                              <Icon name="check" size={11} /> {t("common.yes")}
                            </span>
                          ) : (
                            <span className="badge badge--warn">
                              <Icon name="alert" size={11} /> {t("table.flagged")}
                            </span>
                          )}
                        </td>
                        <td className="muted tiny" data-label={t("table.when")}>{relativeTime(r.at, t, locale)}</td>
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
          <section className="card card--pad rise">
            <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
              <span className="avatar avatar--lg" style={avatarStyle(user.accent)}>
                {initials(user.name)}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700 }}>{user.name}</div>
                <div className="tiny muted">{t(user.roleKey ?? "demo.role")}</div>
              </div>
            </div>
            <p className="tiny muted" style={{ marginTop: 12 }}>
              {t(user.deptKey ?? "demo.department")}
            </p>
            <hr className="divider" style={{ margin: "16px 0" }} />
            <div style={{ display: "flex", gap: 20 }}>
              <div>
                <div className="kpi__value" style={{ fontSize: "1.4rem" }}>
                  {stats.total}
                </div>
                <div className="tiny muted">{t("dash.signOffs")}</div>
              </div>
              <div>
                <div className="kpi__value" style={{ fontSize: "1.4rem" }}>
                  {stats.flagged}
                </div>
                <div className="tiny muted">{t("dash.flagged")}</div>
              </div>
              <div style={{ marginLeft: "auto" }}>
                <Sparkline values={DEMO_THROUGHPUT.map((d) => d.count)} width={104} height={38} />
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
            <div style={{ display: "grid", gap: 13 }}>
              {distribution.map((d) => (
                <div key={d.label} style={{ display: "grid", gap: 5 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                    <span style={{ fontWeight: 600 }}>
                      <span className="swatch" style={{ background: d.color }} />
                      {d.label}
                    </span>
                    <span className="num muted">{d.count}</span>
                  </div>
                  <div style={{ height: 7, borderRadius: 99, background: "var(--surface-sunken)", overflow: "hidden" }}>
                    <div
                      style={{
                        width: `${(d.count / maxBucket) * 100}%`,
                        height: "100%",
                        background: d.color,
                        borderRadius: 99,
                        transition: "width 700ms cubic-bezier(.32,.72,0,1)",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.concordance")}</h2>
                <p className="sub">{t("dash.concordanceSub")}</p>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <Donut value={stats.concordance} size={86} stroke={10} label={t("dash.concordance")} />
              <p className="hint">
                {t("dash.concordanceNote")}
              </p>
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("dash.deployment")}</h2>
                <p className="sub">{t("dash.deploymentSub")}</p>
              </div>
              <Link className="btn btn--ghost btn--sm" to="/model">
                {t("nav.model")}
              </Link>
            </div>
            <dl className="spec-list" style={{ fontSize: "0.75rem" }}>
              <div>
                <dt>{t("common.run")}</dt>
                <dd className="mono">{context?.provenance?.run ?? "—"}</dd>
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
                <dd>{t(context?.demo ? "dash.sourceDemo" : "dash.sourceLive")}</dd>
              </div>
            </dl>
          </section>
        </div>
      </div>
    </>
  );
}

function Kpi({ icon, label, value, foot }) {
  return (
    <article className="card kpi card--lift">
      <div className="kpi__top">
        <div>
          <div className="kpi__label">{label}</div>
          <div className="kpi__value" style={{ marginTop: 8 }}>
            {value}
          </div>
        </div>
        <span className="kpi__icon">
          <Icon name={icon} size={18} />
        </span>
      </div>
      <div className="kpi__foot">{foot}</div>
    </article>
  );
}
