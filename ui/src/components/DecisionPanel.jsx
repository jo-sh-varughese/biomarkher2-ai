/* ISH decision support: the evidence a pathologist weighs before ordering
   (or not ordering) ISH, laid out in the order of that decision.
   Built by app/decision.py from measured numbers only:
     where this case sits on the ASCO/CAP algorithm,
     the evidence for and against ISH, with its weight,
     whether the field can be trusted (quality checklist),
     how close the decisive cell share is to the 10% line (95% intervals),
     whether nearby cut points change the grade (robustness),
     how many cells would have to be read differently to change it,
     where to score ISH, and how to read the ISH result when it returns. */

import { useI18n } from "../i18n/I18nContext.jsx";

const GRADE_COLOR = { 0: "#6e82a0", "1+": "#d9b230", "2+": "#e08214", "3+": "#c81e28" };
const STATUS = {
  ok: { icon: "✓", cls: "ok" },
  warn: { icon: "!", cls: "warn" },
  fail: { icon: "✕", cls: "fail" },
  info: { icon: "i", cls: "info" },
};
const ISH_TONE = {
  required: "dec__ish--required",
  recommended: "dec__ish--recommended",
  not_indicated_by_ihc: "dec__ish--no",
  not_applicable: "dec__ish--na",
};
const SCALE = 40; // the interval bars show 0-40%: the 10% line is what matters

export default function DecisionPanel({ decision, guidance }) {
  const { t } = useI18n();
  if (!decision) return null;
  if (decision.not_assessable) {
    return (
      <section className="card card--pad dec" aria-labelledby="dec-title">
        <div className="card-head">
          <div>
            <h2 id="dec-title">{t("prescore.notAssessableTitle")}</h2>
            <p className="sub">{t("prescore.notAssessableBody")}</p>
          </div>
        </div>
        <h3 className="dec__h">{t("decision.qc")}</h3>
        <ul className="dec__qc">
          {decision.qc.map((q) => {
            const st = STATUS[q.status] ?? STATUS.info;
            return (
              <li key={q.check + q.detail} className={`dec__qc--${st.cls}`}>
                <span className="dec__qcicon" aria-label={q.status}>{st.icon}</span>
                <b>{q.check}</b>
                <span>{q.detail}</span>
              </li>
            );
          })}
        </ul>
      </section>
    );
  }
  const rob = decision.robustness ?? {};
  const level = guidance?.ish?.level ?? "not_applicable";

  return (
    <section className="card card--pad dec" aria-labelledby="dec-title">
      <div className="card-head">
        <div>
          <h2 id="dec-title">{t("decision.title")}</h2>
          <p className="sub">{t("decision.sub")}</p>
        </div>
      </div>

      {/* the answer first */}
      <div className={`dec__ish ${ISH_TONE[level] ?? ""}`}>
        <div className="dec__ishlabel">{t(`prescore.ish.${level}`)}</div>
        <div>{guidance?.ish?.text}</div>
        <div className="tiny muted">{t("decision.basis", { basis: decision.basis })}</div>
      </div>

      {/* ASCO/CAP pathway with this case's step lit */}
      <h3 className="dec__h">{t("decision.pathway")}</h3>
      <ol className="dec__path">
        {decision.pathway.map((s) => (
          <li key={s.grade} className={s.taken ? "is-taken" : undefined} style={{ "--g": GRADE_COLOR[s.grade] }}>
            <b>IHC {s.grade}</b>
            <span className="dec__pathres">{s.result}</span>
            <span className="dec__pathact">{s.action}</span>
            {s.taken ? <span className="dec__here">{t("decision.thisCase")}</span> : null}
          </li>
        ))}
      </ol>

      {/* evidence for / against */}
      <div className="dec__evidence">
        <div>
          <h3 className="dec__h">{t("decision.for")}</h3>
          {decision.evidence_for_ish.length ? (
            <ul className="dec__list">
              {decision.evidence_for_ish.map((e) => (
                <li key={e.text}><span className={`dec__w dec__w--${e.weight}`}>{e.weight}</span>{e.text}</li>
              ))}
            </ul>
          ) : <p className="hint">{t("decision.none")}</p>}
        </div>
        <div>
          <h3 className="dec__h">{t("decision.against")}</h3>
          {decision.evidence_against_ish.length ? (
            <ul className="dec__list">
              {decision.evidence_against_ish.map((e) => (
                <li key={e.text}><span className={`dec__w dec__w--${e.weight}`}>{e.weight}</span>{e.text}</li>
              ))}
            </ul>
          ) : <p className="hint">{t("decision.none")}</p>}
        </div>
      </div>

      {decision.her2_low_boundary ? (
        <div className="note note--caveat dec__low">
          <b>{t("decision.lowTitle")}</b> {decision.her2_low_boundary}
        </div>
      ) : null}

      {/* quality checklist */}
      <h3 className="dec__h">{t("decision.qc")}</h3>
      <ul className="dec__qc">
        {decision.qc.map((q) => {
          const st = STATUS[q.status] ?? STATUS.info;
          return (
            <li key={q.check + q.detail} className={`dec__qc--${st.cls}`}>
              <span className="dec__qcicon" aria-label={q.status}>{st.icon}</span>
              <b>{q.check}</b>
              <span>{q.detail}</span>
            </li>
          );
        })}
      </ul>

      {/* statistical certainty */}
      <h3 className="dec__h">{t("decision.certainty")}</h3>
      <p className="hint">{t("decision.certaintySub")}</p>
      <div className="dec__ci">
        {decision.certainty.map((c) => (
          <div key={c.measure} className="dec__cirow">
            <span className="dec__cilabel">{c.measure}</span>
            <span className="dec__citrack" aria-label={`${c.share}% (95% interval ${c.low}-${c.high}%)`}>
              <span className="dec__cirule" style={{ left: `${(10 / SCALE) * 100}%` }} />
              <span className="dec__cirange" style={{
                left: `${Math.min(100, (c.low / SCALE) * 100)}%`,
                width: `${Math.max(1, Math.min(100, (c.high / SCALE) * 100) - Math.min(100, (c.low / SCALE) * 100))}%`,
              }} />
              <span className="dec__cidot" style={{ left: `${Math.min(100, (c.share / SCALE) * 100)}%` }} />
            </span>
            <span className="num dec__cival">{c.share}% <span className="muted">[{c.low}–{c.high}]</span></span>
            <span className={`dec__cireading${c.near ? " is-near" : ""}`}>{c.reading}</span>
          </div>
        ))}
        <div className="dec__ciaxis"><span>0%</span><span style={{ left: `${(10 / SCALE) * 100}%` }}>10%</span><span>{SCALE}%+</span></div>
      </div>

      {/* robustness + what would change it */}
      <div className="dec__two">
        <div>
          <h3 className="dec__h">{t("decision.robust")}</h3>
          {rob.runs ? (
            <>
              <p className="dec__big">{t("decision.robustValue", { pct: rob.stable_percent, runs: rob.runs, grade: rob.baseline_grade })}</p>
              <div className="dec__robbar">
                {Object.entries(rob.by_grade).filter(([, v]) => v).map(([g, v]) => (
                  <span key={g} style={{ flex: v, background: GRADE_COLOR[g] }} title={`${g}: ${v}`}>{g} · {v}</span>
                ))}
              </div>
              <p className="hint">{t("decision.robustSub")}</p>
            </>
          ) : <p className="hint">{t("decision.none")}</p>}
        </div>
        <div>
          <h3 className="dec__h">{t("decision.whatIf")}</h3>
          <ul className="dec__list">{decision.what_if.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      </div>

      {/* where to score ISH */}
      {decision.ish_targets?.length ? (
        <>
          <h3 className="dec__h">{t("decision.targets")}</h3>
          <p className="hint">{t("decision.targetsSub")}</p>
          <div className="dec__targets">
            {decision.ish_targets.map((r) => (
              <figure key={`${r.row}-${r.col}`}>
                <img src={r.image} alt="" />
                <figcaption>
                  {t("decision.region", { row: r.row, col: r.col })} · <b style={{ color: GRADE_COLOR[r.grade] }}>{r.grade}</b> · {t("decision.weight", { w: r.weight })}
                </figcaption>
              </figure>
            ))}
          </div>
        </>
      ) : null}

      {/* ISH result reference */}
      <details className="dec__groups">
        <summary>{t("decision.groups")}</summary>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>{t("decision.group")}</th><th>{t("decision.criteria")}</th><th>{t("decision.result")}</th></tr></thead>
            <tbody>
              {decision.ish_groups.map((g) => (
                <tr key={g.group}><td><b>{g.group}</b></td><td>{g.criteria}</td><td>{g.result}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
