/* "Why this result" -- the explanation for one field, in the order a
   pathologist reasons (app/explain.py builds it from measured numbers only):
   what the AI looked at, what the cells show, which ASCO/CAP rule that
   meets, whether the two agree, how sure the system is, what could change
   the answer. Then the criteria check, real example cells per category with
   the measured membrane ring drawn on, the distributions behind the counts,
   and the definitions of every cut point used. */

import { useI18n } from "../i18n/I18nContext.jsx";

const GRADES = ["3+", "2+", "1+", "0"];
const GRADE_COLOR = { 0: "#6e82a0", "1+": "#d9b230", "2+": "#e08214", "3+": "#c81e28" };

export default function ExplainPanel({ explanation, onShowView }) {
  const { t } = useI18n();
  if (!explanation) return null;
  const { steps = [], criteria = [], examples = {}, distributions = {}, definitions = [] } = explanation;
  const maxComp = Math.max(1, ...(distributions.completeness ?? []).map((d) => d.count));
  const maxInt = Math.max(1, ...(distributions.intensity ?? []).map((d) => d.count));

  return (
    <section className="card card--pad explain" aria-labelledby="explain-title">
      <div className="card-head">
        <div>
          <h2 id="explain-title">{t("explain.title")}</h2>
          <p className="sub">{t("explain.sub")}</p>
        </div>
        {onShowView ? (
          <div className="explain__views">
            <button type="button" className="btn btn--sm" onClick={() => onShowView("evidence")}>{t("explain.showEvidence")}</button>
            <button type="button" className="btn btn--sm" onClick={() => onShowView("regions")}>{t("explain.showRegions")}</button>
            <button type="button" className="btn btn--sm" onClick={() => onShowView("cells")}>{t("explain.showCells")}</button>
          </div>
        ) : null}
      </div>

      {/* reasoning, step by step */}
      <ol className="explain__steps">
        {steps.map((s) => (
          <li key={s.title}>
            <b>{s.title}</b>
            <p>{s.text}</p>
          </li>
        ))}
      </ol>

      {/* ASCO/CAP criteria check */}
      <h3 className="explain__h">{t("explain.criteria")}</h3>
      <div className="table-wrap">
        <table className="data explain__criteria">
          <thead>
            <tr>
              <th scope="col">{t("explain.grade")}</th>
              <th scope="col">{t("explain.definition")}</th>
              <th scope="col" className="num">{t("explain.measured")}</th>
              <th scope="col">{t("explain.met")}</th>
            </tr>
          </thead>
          <tbody>
            {criteria.map((c) => (
              <tr key={c.grade} className={c.met ? "is-met" : undefined}>
                <td><b style={{ color: GRADE_COLOR[c.grade] }}>IHC {c.grade}</b></td>
                <td>{c.definition}</td>
                <td className="num">{Number(c.measured).toFixed(1)}%</td>
                <td>{c.met ? <span className="badge badge--ok">✓ {t("explain.yes")}</span> : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* example cells per category */}
      <h3 className="explain__h">{t("explain.examples")}</h3>
      <p className="hint">{t("explain.examplesSub")}</p>
      <div className="explain__gallery">
        {GRADES.map((g) => (
          <div key={g} className="explain__cat">
            <div className="explain__cathead" style={{ borderColor: GRADE_COLOR[g] }}>
              <b style={{ color: GRADE_COLOR[g] }}>{t(`prescore.cellGrades.${g}`)}</b>
            </div>
            {(examples[g] ?? []).length ? (
              <div className="explain__cells">
                {examples[g].map((e, i) => (
                  <figure key={i} className="explain__cell">
                    <img src={e.image} alt="" />
                    <figcaption>
                      {t("explain.ring", { pct: e.completeness })} · {e.level}
                      {e.atypical ? ` · ${t("explain.atypical")}` : ""}
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <p className="hint">{t("explain.noneOfThese")}</p>
            )}
          </div>
        ))}
      </div>

      {/* distributions */}
      <div className="explain__dists">
        <div>
          <h3 className="explain__h">{t("explain.completeness")}</h3>
          {(distributions.completeness ?? []).map((d) => (
            <div key={d.label} className="explain__bar">
              <span>{d.label}</span>
              <span className="explain__track"><span style={{ width: `${(100 * d.count) / maxComp}%` }} /></span>
              <span className="num">{d.count}</span>
            </div>
          ))}
        </div>
        <div>
          <h3 className="explain__h">{t("explain.intensity")}</h3>
          {(distributions.intensity ?? []).map((d) => (
            <div key={d.label} className="explain__bar">
              <span>{d.label}</span>
              <span className="explain__track"><span style={{ width: `${(100 * d.count) / maxInt}%` }} /></span>
              <span className="num">{d.count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* definitions */}
      <details className="explain__defs">
        <summary>{t("explain.howMeasured")}</summary>
        <dl>
          {definitions.map((d) => (
            <div key={d.term}>
              <dt>{d.term}</dt>
              <dd>{d.text}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
