/* One case from the case database: every analysis run on it (AI pre-score
   with probabilities, cell evidence, stained area, ISH guidance, quality, and
   for a slide its fields and hotspots), every pathologist sign-off from the
   review log, and the regions marked on it. A pathologist sees their own runs
   and sign-offs; an administrator sees everyone's. */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { ScoreBadge } from "../components/Badges.jsx";
import { fetchCase } from "../lib/api.js";
import { dateTime, GRADE_COLOR, initials, pct, shortId } from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";
import { cellsAtLeast1 } from "./Cases.jsx";

const GRADES = ["0", "1+", "2+", "3+"];
const AGREE_KEY = { agree: "agree", disagree: "disagree", partly: "partial", "AI not shown": "not_shown" };

export default function CaseDetail() {
  const { caseId } = useParams();
  const { t, locale } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    fetchCase(caseId)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message || String(e)));
    return () => {
      live = false;
    };
  }, [caseId]);

  const back = (
    <Link className="btn btn--ghost btn--sm" to="/cases">
      <Icon name="chevronsLeft" size={14} /> {t("casedb.back")}
    </Link>
  );

  if (error) {
    return (
      <>
        <div className="page__head">{back}</div>
        <section className="card card--pad">
          <p className="prescore__warning" role="alert">{error}</p>
        </section>
      </>
    );
  }
  if (!data) return <div className="skeleton" style={{ height: 420, borderRadius: "var(--r-lg)" }} />;

  const { case: c, analyses, reviews, annotations } = data;
  const latest = analyses[0];

  return (
    <>
      <div className="page__head">
        <div>
          {back}
          <div className="eyebrow" style={{ marginTop: 10 }}>
            {t(`casedb.kind.${c.kind}`)} · <span className="mono">{c.case_id}</span>
          </div>
          <h1 className="casedetail__title">{c.name}</h1>
          <p className="lede">
            {t("casedb.source")}: <span className="mono">{c.source}</span>
            {c.dataset_label ? ` · ${t("casedb.datasetLabel")} ${c.dataset_label}` : ""} · {t("casedb.firstSeen")}{" "}
            {dateTime(c.created_at, locale)}
          </p>
        </div>
        <div className="page__actions">
          <Link className="btn" to={c.kind === "slide" ? "/slides" : "/analysis"}>
            <Icon name={c.kind === "slide" ? "layers" : "scan"} size={16} />{" "}
            {c.kind === "slide" ? t("casedb.openSlide") : t("casedb.openAnalysis")}
          </Link>
        </div>
      </div>

      <div className="casedetail__top">
        <section className="card card--pad casedetail__thumb">
          {c.thumbnail ? <img src={c.thumbnail} alt={c.name} /> : <span className="caselist__nothumb" />}
        </section>
        <section className="card card--pad casedetail__summary">
          <div className="casedetail__kpis">
            <Kpi label={t("casedb.col.ai")}>
              {latest?.ai_shown && latest.ai_category ? (
                <ScoreBadge score={latest.ai_category} classes={[]} t={t} />
              ) : latest ? (
                <span className="muted">{t("casedb.withheld")}</span>
              ) : (
                "—"
              )}
            </Kpi>
            <Kpi label={t("casedb.col.cells")}>
              {latest?.cell_category ? <ScoreBadge score={latest.cell_category} classes={[]} t={t} /> : "—"}
            </Kpi>
            <Kpi label={t("casedb.col.review")}>
              {reviews[0]?.score ? <ScoreBadge score={reviews[0].score} classes={[]} t={t} /> : (
                <span className="muted">{t("casedb.notReviewed")}</span>
              )}
            </Kpi>
            <Kpi label={t("casedb.ish")}>
              {latest?.ish_level ? t(`prescore.ish.${latest.ish_level}`) : "—"}
            </Kpi>
          </div>
          <p className="tiny muted">
            {t("casedb.analysesCount", { n: analyses.length })} · {t("casedb.reviewsCount", { n: reviews.length })}
            {data.scope === "all" ? ` · ${t("casedb.scopeAll")}` : ` · ${t("casedb.scopeOwn")}`}
          </p>
        </section>
      </div>

      <section className="card card--pad casedetail__section">
        <h2>{t("casedb.sectionReviews")}</h2>
        <p className="hint">{t("casedb.sectionReviewsSub")}</p>
        {reviews.length ? (
          <div className="casedetail__list">
            {reviews.map((r) => (
              <ReviewCard key={r.id} r={r} t={t} locale={locale} />
            ))}
          </div>
        ) : (
          <p className="hint">{t("casedb.noReviews")}</p>
        )}
      </section>

      <section className="card card--pad casedetail__section">
        <h2>{t("casedb.sectionAnalyses")}</h2>
        <p className="hint">{t("casedb.sectionAnalysesSub")}</p>
        {analyses.length ? (
          <div className="casedetail__list">
            {analyses.map((a) => (
              <AnalysisCard key={a.id} a={a} t={t} locale={locale} />
            ))}
          </div>
        ) : (
          <p className="hint">{t("casedb.noAnalyses")}</p>
        )}
      </section>

      <section className="card card--pad casedetail__section">
        <h2>{t("casedb.sectionRegions")}</h2>
        {annotations.length ? (
          <ul className="annot-list">
            {annotations.map((a, i) => (
              <li key={a.id ?? i}>
                <span className="annot-list__tag">{i + 1}</span>
                <div>
                  {a.score ? <b>{a.score}</b> : null}
                  {a.note ? <p>{a.note}</p> : null}
                  <span className="tiny muted">
                    {a.reviewer}
                    {a.recorded_at ? ` · ${dateTime(a.recorded_at, locale)}` : ""}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">{t("casedb.noRegions")}</p>
        )}
      </section>
    </>
  );
}

function Kpi({ label, children }) {
  return (
    <div className="casedetail__kpi">
      <span className="tiny muted">{label}</span>
      <div>{children}</div>
    </div>
  );
}

function Who({ name, when, locale, t }) {
  return (
    <span className="who">
      <span className="avatar avatar--sm">{initials(name || "?")}</span>
      <span className="casedetail__who">{t("casedb.ranBy", { name: name || "—", when: dateTime(when, locale) })}</span>
    </span>
  );
}

function Bars({ values }) {
  return (
    <div className="prescore__bars">
      {GRADES.map((g) => {
        const v = Number(values?.[g] ?? 0);
        return (
          <div key={g} className="prescore__bar">
            <span className="prescore__barlabel">{g}</span>
            <span className="prescore__track">
              <span style={{ width: `${Math.max(0, Math.min(100, v * 100))}%`, background: GRADE_COLOR[g] }} />
            </span>
            <span className="num tiny">{Math.round(v * 100)}%</span>
          </div>
        );
      })}
    </div>
  );
}

function AnalysisCard({ a, t, locale }) {
  const s = a.summary || {};
  const block = s.ai_prescore || {};
  const pre = block.prescore || {};
  const cells = s.cell_evidence || {};
  const guidance = s.guidance || {};
  const quality = s.quality || {};
  const fieldsByGrade = pre.heterogeneity?.fields_by_grade;
  const stain = s.model_percentages;

  return (
    <article className="casedetail__card">
      <header className="casedetail__cardhead">
        <Who name={a.user_name} when={a.at} locale={locale} t={t} />
        <span className="badge badge--outline">{t(`casedb.kind.${a.kind}`)}</span>
        {quality.assessable === false ? <span className="badge badge--danger">{t("casedb.notAssessable")}</span> : null}
      </header>

      <div className="casedetail__grid">
        <div>
          <h3>{t("casedb.aiPrescore")}</h3>
          {block.shown && pre.category ? (
            <>
              <p className="casedetail__big">
                <ScoreBadge score={pre.category} classes={[]} t={t} />
                {pre.confidence != null ? (
                  <span className="tiny muted"> {t("casedb.confidence", { pct: pct(pre.confidence * 100, 0) })}</span>
                ) : null}
                {pre.borderline ? <span className="badge badge--warn">{t("casedb.borderline")}</span> : null}
              </p>
              <Bars values={pre.probabilities} />
            </>
          ) : (
            <p className="hint">
              {t("casedb.aiWithheld")}
              {block.withheld_reasons?.length ? `: ${block.withheld_reasons[0]}` : ""}
            </p>
          )}
          {fieldsByGrade ? (
            <>
              <h4>{t("casedb.heterogeneity")}</h4>
              <Bars values={fieldsByGrade} />
            </>
          ) : null}
        </div>

        <div>
          <h3>{t("casedb.cellEvidence")}</h3>
          {cells.field_category || cells.measured_category ? (
            <>
              <p className="casedetail__big">
                <ScoreBadge score={cells.field_category || cells.measured_category} classes={[]} t={t} />
                <span className="tiny muted"> {t("casedb.cellsMeasured", { n: cells.cells_measured ?? 0 })}</span>
              </p>
              {cells.percent ? (
                <dl className="casedetail__kv">
                  {GRADES.map((g) => (
                    <div key={g}>
                      <dt>
                        <i style={{ background: GRADE_COLOR[g] }} /> {g}
                      </dt>
                      <dd>{pct(cells.percent[g])}</dd>
                    </div>
                  ))}
                  <div className="is-total">
                    <dt>≥1+</dt>
                    <dd>{pct(cellsAtLeast1(cells.percent))}</dd>
                  </div>
                </dl>
              ) : null}
              {cells.rule_applied ? <p className="hint">{cells.rule_applied}</p> : null}
            </>
          ) : (
            <p className="hint">—</p>
          )}
        </div>

        <div>
          {stain ? (
            <>
              <h3>{t("casedb.stainArea")}</h3>
              <dl className="casedetail__kv">
                {Object.entries(stain).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{pct(v)}</dd>
                  </div>
                ))}
                {s.tissue_percent != null ? (
                  <div className="is-total">
                    <dt>{t("casedb.tissue")}</dt>
                    <dd>{pct(s.tissue_percent)}</dd>
                  </div>
                ) : null}
              </dl>
            </>
          ) : null}
          {a.kind === "slide" ? (
            <>
              <h3>{t("casedb.col.stain")}</h3>
              <p className="hint">
                {t("casedb.slideFields", { n: s.fields_analysed ?? 0, r: s.fields_rejected ?? 0 })}
                {s.tissue?.usable_area_mm2 != null ? ` · ${s.tissue.usable_area_mm2} mm²` : ""}
              </p>
              {s.hotspots?.length ? (
                <>
                  <h4>{t("casedb.hotspots")}</h4>
                  <ul className="casedetail__hot">
                    {s.hotspots.map((h) => (
                      <li key={h.index}>
                        #{h.index + 1} · AI {h.prescore_category || "–"} · {t("casedb.col.cells")} {h.cell_category}
                        {h.attention != null ? ` · ${Math.round(h.attention * 100)}%` : ""}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </>
          ) : null}
          <h3>{t("casedb.ish")}</h3>
          <p className="hint">
            {guidance.ish?.level ? <b>{t(`prescore.ish.${guidance.ish.level}`)}</b> : "—"}
            {guidance.ish?.text ? ` — ${guidance.ish.text}` : ""}
          </p>
        </div>
      </div>

      {s.flags?.length || cells.flags?.length ? (
        <details className="casedetail__flags">
          <summary>{t("casedb.flags")} ({(s.flags?.length ?? 0) + (cells.flags?.length ?? 0)})</summary>
          <ul>
            {[...(s.flags ?? []), ...(cells.flags ?? [])].map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="tiny muted mono">{shortId(a.id)}</p>
    </article>
  );
}

function ReviewCard({ r, t, locale }) {
  const pctRows = [
    ["pct_complete_intense", "complete_intense"],
    ["pct_complete_weak_moderate", "complete_weak_moderate"],
    ["pct_incomplete_faint", "incomplete_faint"],
    ["pct_no_staining", "no_staining"],
  ].filter(([k]) => r[k] != null && r[k] !== "");
  const agree = AGREE_KEY[r.ai_agreement];
  return (
    <article className="casedetail__card">
      <header className="casedetail__cardhead">
        <Who name={r.reviewer} when={r.at} locale={locale} t={t} />
        <span className={`review__status review__status--${r.status ?? "final"}`}>
          {t(`review.status.${r.status ?? "final"}`)}
          {r.version > 1 ? ` · ${t("casedb.version", { n: r.version })}` : ""}
        </span>
      </header>
      <div className="casedetail__grid">
        <div>
          <h3>{t("casedb.reviewScore")}</h3>
          <p className="casedetail__big">
            <ScoreBadge score={r.score} classes={[]} t={t} />
            {r.her2_category ? <span className="tiny muted"> {r.her2_category}</span> : null}
          </p>
          {r.ai_agreement ? (
            <p className="hint">
              {t("casedb.reviewAi")}: <b>{agree ? t(`casedb.agree.${agree}`) : r.ai_agreement}</b>
              {r.ai_disagreement_reason ? ` — ${r.ai_disagreement_reason}` : ""}
            </p>
          ) : null}
          {r.ish_decision ? (
            <p className="hint">
              {t("casedb.reviewIsh")}: <b>{r.ish_decision}</b>
            </p>
          ) : null}
        </div>
        <div>
          {pctRows.length ? (
            <>
              <h3>{t("casedb.reviewPct")}</h3>
              <dl className="casedetail__kv">
                {pctRows.map(([k, label]) => (
                  <div key={k}>
                    <dt>{t(`casedb.cellPct.${label}`)}</dt>
                    <dd>{pct(Number(r[k]))}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : null}
        </div>
        <div>
          {r.report_comment ? (
            <>
              <h3>{t("casedb.reviewComment")}</h3>
              <p>{r.report_comment}</p>
            </>
          ) : null}
          {r.notes && r.notes !== r.report_comment ? (
            <>
              <h3>{t("casedb.reviewNotes")}</h3>
              <p>{r.notes}</p>
            </>
          ) : null}
        </div>
      </div>
    </article>
  );
}
