/* AI pre-score, ISH guidance and cell-level ASCO/CAP evidence for one field.

   Reading order is the pathologist's: what the system suggests (or why it is
   withheld at this site), what to do next and why, then the cell counts the
   suggestion can be checked against. Every value comes from the server's
   analysis payload (app/analysis.py); nothing is computed or re-worded here. */

import { useI18n } from "../i18n/I18nContext.jsx";

const GRADES = ["0", "1+", "2+", "3+"];
const GRADE_COLOR = { 0: "#6e82a0", "1+": "#d9b230", "2+": "#e08214", "3+": "#c81e28" };
const ISH_TONE = {
  required: { fg: "#b3261e", bg: "rgba(179,38,30,0.08)" },
  recommended: { fg: "#9a5b00", bg: "rgba(224,130,20,0.10)" },
  not_indicated_by_ihc: { fg: "#1e6b45", bg: "rgba(30,107,69,0.09)" },
  not_applicable: { fg: "var(--text-3)", bg: "var(--surface-2)" },
};

const pct = (v) => `${Math.round(v * 100)}%`;

export default function PrescorePanel({ analysis }) {
  const { t } = useI18n();
  const pre = analysis?.ai_prescore;
  const guide = analysis?.guidance;
  const cells = analysis?.cell_evidence;
  if (!guide && !cells) return null;
  const quality = analysis?.quality;
  const blocked = quality && quality.assessable === false;
  const shown = !blocked && pre?.shown && pre?.prescore;
  const p = shown ? pre.prescore : null;
  const tone = ISH_TONE[guide?.ish?.level] || ISH_TONE.not_applicable;

  return (
    <section className="card card--pad prescore" aria-labelledby="prescore-title">
      <div className="card-head">
        <div>
          <h2 id="prescore-title">{t("prescore.title")}</h2>
          <p className="sub">{t("prescore.sub")}</p>
        </div>
        {pre?.site ? (
          <span className={`badge ${pre.validated ? "badge--ok" : "badge--outline"}`}>
            {t("prescore.siteStatus", { site: pre.site, status: (pre.gate_status || "").replace("_", " ") })}
          </span>
        ) : null}
      </div>

      {/* ------------------------------------- field quality: not assessable --- */}
      {blocked ? (
        <div className="prescore__blocked" role="alert">
          <strong>{t("prescore.notAssessableTitle")}</strong>
          <p className="hint">{t("prescore.notAssessableBody")}</p>
          <div className="prescore__label">{t("prescore.reasons")}</div>
          <ul>{quality.reasons.filter((r) => r.level === "block").map((r) => <li key={r.code}>{r.text}</li>)}</ul>
          {guide?.next_steps?.length ? (
            <>
              <div className="prescore__label">{t("prescore.whatToDo")}</div>
              <ul>{guide.next_steps.map((c) => <li key={c}>{c}</li>)}</ul>
            </>
          ) : null}
        </div>
      ) : null}
      {quality?.notes?.length ? (
        <p className="hint">{t("prescore.qualityNotes")}: {quality.notes.join(" ")}</p>
      ) : null}

      {/* ---------------------------------------------------- pre-score --- */}
      {blocked ? null : p ? (
        <div className="prescore__hero">
          <div>
            <div className="prescore__label">{t("prescore.label")}</div>
            <div className="prescore__grade" style={{ color: GRADE_COLOR[p.category] }}>IHC {p.category}</div>
            <p className="hint">
              {t("prescore.confidence", { value: pct(p.confidence) })} ·{" "}
              {t("field.nextLikely", { grade: p.runner_up, p: pct(p.probabilities?.[p.runner_up] ?? 0) })}
            </p>
            {p.prediction_set?.available ? (
              <p className="prescore__set" title={t("prescore.setHint", { n: p.prediction_set.n_cases })}>
                {t("prescore.set", { pct: Math.round(p.prediction_set.coverage * 100) })}{" "}
                <b>{p.prediction_set.grades.length ? p.prediction_set.grades.map((g) => `IHC ${g}`).join(` ${t("prescore.or")} `) : "—"}</b>
              </p>
            ) : null}
            {p.borderline ? <p className="prescore__flag">{t("prescore.borderline")}</p> : null}
            {p.heterogeneity?.heterogeneous ? <p className="prescore__flag">{t("prescore.heterogeneous")}</p> : null}
          </div>
          <div className="prescore__bars" aria-label={t("prescore.probabilities")}>
            <div className="prescore__label">{t("prescore.probabilities")}</div>
            {GRADES.map((g) => (
              <div key={g} className="prescore__bar">
                <span className="prescore__barlabel">{g}</span>
                <span className="prescore__track">
                  <span style={{ width: pct(p.probabilities[g] || 0), background: GRADE_COLOR[g] }} />
                </span>
                <span className="num">{pct(p.probabilities[g] || 0)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : pre?.available ? (
        <div className="prescore__notice">
          <strong>{t("prescore.withheldTitle")}</strong>
          <p className="hint">{t("prescore.withheldBody")}</p>
          <ul>{(pre.withheld_reasons || []).map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      ) : (
        <p className="hint">{t("prescore.noModel")}</p>
      )}
      {pre?.warning ? <p className="prescore__warning" role="alert">{t("prescore.research")}</p> : null}
      {p ? (
        <p className="hint">
          {t("prescore.confirm")}{p.model?.head_version ? ` · ${t("prescore.version", { v: p.model.head_version })}` : ""}
        </p>
      ) : null}

      {/* ----------------------------------------------------- guidance --- */}
      {guide && !blocked ? (
        <div className="prescore__ish" style={{ borderColor: tone.fg, background: tone.bg }}>
          <div className="prescore__ishhead">
            <strong style={{ color: tone.fg }}>{t(`prescore.ish.${guide.ish.level}`)}</strong>
            <span className="hint">
              {guide.suggested_range} · {t("prescore.basis", { basis: guide.basis })}
            </span>
          </div>
          <p>{guide.ish.text}</p>
          {guide.cautions?.length ? (
            <>
              <div className="prescore__label">{t("prescore.cautions")}</div>
              <ul>{guide.cautions.map((c) => <li key={c}>{c}</li>)}</ul>
            </>
          ) : null}
          {guide.next_steps?.length ? (
            <>
              <div className="prescore__label">{t("prescore.steps")}</div>
              <ul>{guide.next_steps.map((c) => <li key={c}>{c}</li>)}</ul>
            </>
          ) : null}
        </div>
      ) : null}

      {/* ------------------------------------------------ cell evidence --- */}
      {cells && !blocked ? (
        <div className="prescore__cells">
          <div className="prescore__label">{t("prescore.cellsTitle")}</div>
          <p className="hint">{t("prescore.cellsSub")}</p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">{t("prescore.cellsMeasured")}: {cells.cells_measured}</th>
                  <th scope="col" className="num">%</th>
                </tr>
              </thead>
              <tbody>
                {GRADES.map((g) => (
                  <tr key={g}>
                    <td>
                      <span className="swatch" style={{ background: GRADE_COLOR[g] }} />
                      {t(`prescore.cellGrades.${g}`)}
                    </td>
                    <td className="num">{(cells.percent?.[g] ?? 0).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">
            <strong>{t("prescore.fieldCategory", { grade: cells.field_category })}</strong> — {cells.rule_applied}
            {cells.her2_low ? ` · ${t("prescore.her2Low")}` : ""}
            {cells.her2_ultralow ? ` · ${t("prescore.ultralow")}` : ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}
