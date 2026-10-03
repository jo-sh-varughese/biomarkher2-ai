/* Pathologist review -- the laboratory record of the pathologist's assessment.

   Opened from the bottom action bar of Field analysis or Whole slides, with
   what the system showed (image, AI pre-score, cell evidence, suggested next
   step) beside a structured form that follows the ASCO/CAP HER2 IHC
   reporting elements. Saves are appended to the review log on the server
   (app/review_record.py validates them): draft -> preliminary -> signed
   final; a signed report is never edited, only amended with a reason.

   The score is deliberately NOT pre-filled from the AI: the pathologist
   commits to their own read with the suggestion in view, not by accepting a
   default (automation bias is the failure this screen exists to avoid). */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import ZoomViewer from "../components/ZoomViewer.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useToast } from "../state/ToastContext.jsx";
import { submitReview } from "../lib/api.js";
import { dateTime, shortId } from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";

const SCORES = ["0", "1+", "2+", "3+", "cannot assess from this field"];
const PCTS = ["pct_complete_intense", "pct_complete_weak_moderate", "pct_incomplete_faint", "pct_no_staining"];
const GRADE_COLOR = { 0: "#6e82a0", "1+": "#d9b230", "2+": "#e08214", "3+": "#c81e28" };
const CATEGORY = { 0: "HER2-0", "1+": "HER2-low", "2+": "HER2 equivocal (IHC 2+)", "3+": "HER2-positive" };

const EMPTY = {
  accession: "", patient_ref: "", block: "", specimen_type: "", antibody_clone: "", fixation_ok: "",
  cold_ischaemia_ok: "", control_status: "", tissue_adequacy: "", invasive_cells_estimate: "",
  score: "", ultralow: false, pct_complete_intense: "", pct_complete_weak_moderate: "", pct_incomplete_faint: "",
  pct_no_staining: "", heterogeneous: false, staining_pattern: [], artefacts: [], ai_agreement: "",
  ai_disagreement_reason: "", cell_agreement: "", ish_decision: "", second_opinion: false, report_comment: "",
  internal_note: "", amend_reason: "",
};

const elapsed = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export default function Review() {
  const { context, reviewTarget: target, reviews, reloadReviews, recordReview } = usePortal();
  const { user, can } = useAuth();
  const toast = useToast();
  const { t, locale } = useI18n();
  const canReview = can("review");
  const opts = context?.review_options;
  const enums = opts?.enums ?? {};
  const multi = opts?.multi ?? {};

  const [form, setForm] = useState(EMPTY);
  const [amends, setAmends] = useState(null);
  const [saving, setSaving] = useState(null);
  const [attest, setAttest] = useState(false);
  const [now, setNow] = useState(Date.now());
  const started = useRef(new Date());
  const confirmRef = useRef(null);

  const ai = target?.ai_prescore;
  const aiShown = Boolean(ai?.shown && ai?.prescore);
  const cells = target?.cell_evidence;
  const guide = target?.guidance;

  /* a new case: fresh form and clock */
  useEffect(() => {
    setForm({ ...EMPTY, ai_agreement: target && !aiShown ? "AI not shown" : "" });
    setAmends(null);
    setAttest(false);
    started.current = new Date();
  }, [target, aiShown]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const history = useMemo(
    () => (target ? reviews.filter((r) => r.patch_id === target.id) : []),
    [reviews, target],
  );
  const latest = history[0];

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
  const toggleIn = (key, value) =>
    setForm((f) => ({ ...f, [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value] }));
  const pctTotal = PCTS.reduce((sum, k) => sum + (Number(form[k]) || 0), 0);
  const category = form.score === "0" && form.ultralow ? "HER2-ultralow" : CATEGORY[form.score] ?? "not applicable";
  const needsReason = ["disagree", "partly"].includes(form.ai_agreement);

  const startAmend = (r) => {
    const next = { ...EMPTY };
    for (const k of Object.keys(EMPTY)) if (r[k] != null) next[k] = r[k];
    next.score = r.score;
    next.amend_reason = "";
    setForm(next);
    setAmends(r);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const save = async (status) => {
    if (!form.score) {
      toast.error(t("review.failed"), t("review.scoreRequired"));
      return;
    }
    setSaving(status);
    try {
      const payload = {
        ...form,
        status,
        attest: status === "final" ? attest : false,
        her2_category: category,
        patch_id: target.id,
        kind: target.kind,
        // A draft or preliminary record is continued, not duplicated: the next
        // save supersedes it as the next version. A signed one is only changed
        // through an explicit amendment (with a reason).
        amends: amends?.id || (latest && latest.status && latest.status !== "final" ? latest.id : ""),
        started_at: started.current.toISOString(),
        agrees: form.ai_agreement === "agree",
        notes: form.report_comment,
        ai_snapshot: {
          kind: target.kind,
          shown: aiShown,
          prescore: aiShown ? ai.prescore.category : null,
          confidence: aiShown ? ai.prescore.confidence : null,
          site: ai?.site ?? null,
          gate_status: ai?.gate_status ?? null,
          cell_category: cells?.field_category ?? null,
          cells_measured: cells?.cells_measured ?? null,
          ish_suggestion: guide?.ish?.level ?? null,
        },
        measurements: target.measurements ?? {},
      };
      for (const k of PCTS) if (payload[k] === "") delete payload[k];
      const result = await submitReview(payload);
      if (result.demo) recordReview({ ...payload, reviewer: user.name, at: new Date().toISOString() });
      else await reloadReviews();
      toast.ok(t("review.saved"), t("review.savedBody", { status: t(`review.status.${status}`), n: result.version ?? 1 }));
      if (status === "final") {
        confirmRef.current?.close();
        setAmends(null);
        setAttest(false);
      }
    } catch (err) {
      toast.error(t("review.failed"), err.message || String(err));
    } finally {
      setSaving(null);
    }
  };

  /* ------------------------------------------------------- no target --- */
  if (!target) {
    return (
      <>
        <div className="page__head">
          <div>
            <div className="eyebrow">{t("review.eyebrow")}</div>
            <h1>{t("review.title")}</h1>
            <p className="lede">{t("review.lede")}</p>
          </div>
        </div>
        <section className="card card--pad">
          <div className="empty">
            <span className="empty__art"><Icon name="stethoscope" size={30} strokeWidth={1.5} /></span>
            <h3>{t("review.nothingTitle")}</h3>
            <p>{t("review.nothingBody")}</p>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
              <Link className="btn btn--primary" to="/analysis"><Icon name="scan" size={16} /> {t("review.goAnalyse")}</Link>
              <Link className="btn" to="/slides"><Icon name="layers" size={16} /> {t("review.goSlides")}</Link>
            </div>
          </div>
        </section>
        <Worklist reviews={reviews} t={t} locale={locale} />
      </>
    );
  }

  /* ---------------------------------------------------------- review --- */
  const statusKey = latest?.status ?? "none";
  return (
    <div className="review">
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("review.eyebrow")}</div>
          <h1>{t("review.title")}</h1>
          <p className="lede">{t("review.lede")}</p>
        </div>
        <div className="page__actions">
          <button type="button" className="btn" onClick={() => window.print()}>
            <Icon name="printer" size={16} /> {t("review.actions.print")}
          </button>
        </div>
      </div>

      {/* case banner */}
      <section className="card review__banner">
        <span className="badge badge--outline">{target.kind === "slide" ? t("review.slide") : t("review.field")}</span>
        <b className="mono review__id" title={target.id}>{target.label || shortId(target.id)}</b>
        <span className={`review__status review__status--${statusKey}`}>
          {t(`review.status.${statusKey}`)}
          {latest ? ` · ${t("review.versionOf", { n: latest.version ?? 1 })}` : ""}
        </span>
        <span className="review__timer">
          <Icon name="clock" size={14} /> {t("review.timer", { time: elapsed(now - started.current.getTime()) })}
        </span>
        <span className="review__who">{user.name}{user.registration ? ` · ${user.registration}` : ""}</span>
      </section>

      <div className="review__grid">
        {/* ---------------------------------------------- reference --- */}
        <aside className="review__ref">
          <section className="card card--pad">
            <h2>{t("review.reference")}</h2>
            {target.image ? (
              <>
                <ZoomViewer src={target.image} alt={target.label} className="review__zoom" />
                <p className="hint">{t("review.zoomHint")}</p>
              </>
            ) : null}
            <dl className="review__facts">
              <div>
                <dt>{t("review.aiPrescore")}</dt>
                <dd>
                  {aiShown ? (
                    <b style={{ color: GRADE_COLOR[ai.prescore.category] }}>
                      IHC {ai.prescore.category} · {Math.round(ai.prescore.confidence * 100)}%
                    </b>
                  ) : ai?.available ? t("review.aiWithheld") : t("review.aiNone")}
                </dd>
              </div>
              {cells ? (
                <div>
                  <dt>{t("review.cellEvidence")}</dt>
                  <dd>
                    <b>IHC {cells.field_category}</b> · {t("review.cellsMeasured", { n: cells.cells_measured })}
                    <div className="tiny muted">
                      0 {cells.percent?.["0"]?.toFixed?.(1)}% · 1+ {cells.percent?.["1+"]?.toFixed?.(1)}% · 2+{" "}
                      {cells.percent?.["2+"]?.toFixed?.(1)}% · 3+ {cells.percent?.["3+"]?.toFixed?.(1)}%
                    </div>
                  </dd>
                </div>
              ) : null}
              {guide ? (
                <div>
                  <dt>{t("review.suggested")}</dt>
                  <dd>{guide.ish?.text}</dd>
                </div>
              ) : null}
            </dl>
            {(guide?.cautions ?? []).length ? (
              <ul className="review__cautions">{guide.cautions.slice(0, 6).map((c) => <li key={c}>{c}</li>)}</ul>
            ) : null}
          </section>

          <section className="card card--pad">
            <h2>{t("review.history")}</h2>
            {history.length ? (
              <ol className="review__history">
                {history.map((r) => (
                  <li key={r.id}>
                    <div>
                      <span className={`review__status review__status--${r.status ?? "final"}`}>
                        {t(`review.status.${r.status ?? "final"}`)}
                      </span>{" "}
                      <b>IHC {r.score}</b> · v{r.version ?? 1}
                      <div className="tiny muted">{r.reviewer} · {dateTime(r.at, locale)}</div>
                      {r.amend_reason ? <div className="tiny">↳ {r.amend_reason}</div> : null}
                    </div>
                    {canReview ? (
                      <button type="button" className="btn btn--ghost btn--sm" onClick={() => startAmend(r)}>
                        <Icon name="pen" size={13} /> {t("review.amendThis")}
                      </button>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="hint">{t("review.historyEmpty")}</p>
            )}
          </section>
        </aside>

        {/* --------------------------------------------------- form --- */}
        <form className="review__form" onSubmit={(e) => e.preventDefault()}>
          {!canReview ? <div className="note note--info">{t("review.cannotReview")}</div> : null}
          {amends ? (
            <div className="note note--caveat review__amending">
              <span>{t("review.viewing", { id: amends.id, n: amends.version ?? 1 })}</span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => { setAmends(null); setForm({ ...EMPTY }); }}>
                {t("review.cancelAmend")}
              </button>
            </div>
          ) : null}
          <fieldset disabled={!canReview} className="bare-fieldset review__sections">
            <Card title={t("review.sections.specimen")}>
              <div className="review__row">
                <Text id="accession" t={t} form={form} set={set} placeholder />
                <Text id="patient_ref" t={t} form={form} set={set} placeholder />
                <Text id="block" t={t} form={form} set={set} placeholder small />
              </div>
              <div className="review__row">
                <Select id="specimen_type" t={t} form={form} set={set} options={enums.specimen_type} />
                <Select id="antibody_clone" t={t} form={form} set={set} options={enums.antibody_clone} />
              </div>
              <div className="review__row">
                <Choice id="fixation_ok" t={t} form={form} set={set} options={enums.fixation_ok} />
                <Choice id="cold_ischaemia_ok" t={t} form={form} set={set} options={enums.cold_ischaemia_ok} />
              </div>
            </Card>

            <Card title={t("review.sections.controls")}>
              <div className="review__row">
                <Choice id="control_status" t={t} form={form} set={set} options={enums.control_status} />
                <Choice id="tissue_adequacy" t={t} form={form} set={set} options={enums.tissue_adequacy} />
              </div>
              <Text id="invasive_cells_estimate" t={t} form={form} set={set} placeholder small />
            </Card>

            <Card title={t("review.sections.assessment")}>
              <div className="field">
                <span className="field-label">{t("review.fields.score")}</span>
                <div className="score-picker">
                  {SCORES.map((s) => (
                    <label key={s} className="score-opt">
                      <input type="radio" name="review-score" checked={form.score === s} onChange={() => set("score")(s)} />
                      <b>{s.startsWith("cannot") ? "—" : s}</b>
                      {s.startsWith("cannot") ? <span>{t("analysis.cannotAssess")}</span> : null}
                    </label>
                  ))}
                </div>
              </div>
              {form.score === "0" ? (
                <label className="check">
                  <input type="checkbox" checked={form.ultralow} onChange={(e) => set("ultralow")(e.target.checked)} />
                  {t("review.fields.ultralow")}
                </label>
              ) : null}
              <div className="review__category">
                {t("review.fields.her2_category")}: <b>{form.score ? category : "—"}</b>
              </div>
              <div className="field">
                <span className="field-label">{t("review.fields.percentages")}</span>
                <div className="review__pcts">
                  {PCTS.map((k) => (
                    <label key={k} className="review__pct">
                      <span>{t(`review.fields.${k}`)}</span>
                      <span className="review__pctin">
                        <input className="input" type="number" min="0" max="100" step="1" inputMode="numeric"
                          value={form[k]} onChange={(e) => set(k)(e.target.value)} />
                        %
                      </span>
                    </label>
                  ))}
                </div>
                <p className={`hint${pctTotal > 100 ? " review__bad" : ""}`}>{t("review.fields.pctTotal", { n: pctTotal })}</p>
              </div>
              <label className="check">
                <input type="checkbox" checked={form.heterogeneous} onChange={(e) => set("heterogeneous")(e.target.checked)} />
                {t("review.fields.heterogeneous")}
              </label>
              <Multi id="staining_pattern" t={t} form={form} toggle={toggleIn} options={multi.staining_pattern} />
              <Multi id="artefacts" t={t} form={form} toggle={toggleIn} options={multi.artefacts} />
            </Card>

            <Card title={t("review.sections.concordance")}>
              <div className="review__row">
                <Choice id="ai_agreement" t={t} form={form} set={set} options={enums.ai_agreement} />
                <Choice id="cell_agreement" t={t} form={form} set={set} options={enums.cell_agreement} />
              </div>
              {needsReason ? <Area id="ai_disagreement_reason" t={t} form={form} set={set} rows={2} /> : null}
            </Card>

            <Card title={t("review.sections.decision")}>
              <Choice id="ish_decision" t={t} form={form} set={set} options={enums.ish_decision} />
              <label className="check">
                <input type="checkbox" checked={form.second_opinion} onChange={(e) => set("second_opinion")(e.target.checked)} />
                {t("review.fields.second_opinion")}
              </label>
            </Card>

            <Card title={t("review.sections.comments")}>
              <Area id="report_comment" t={t} form={form} set={set} rows={3} placeholder />
              <Area id="internal_note" t={t} form={form} set={set} rows={2} placeholder />
              {amends ? <Area id="amend_reason" t={t} form={form} set={set} rows={2} placeholder /> : null}
            </Card>
          </fieldset>
        </form>
      </div>

      {/* bottom action bar */}
      {canReview ? (
        <div className="actionbar" role="toolbar" aria-label={t("review.sections.signoff")}>
          <div className="actionbar__info">
            <span className="tiny muted">{t("review.signingAs")}</span> <b>{user.name}</b>
            {form.score ? <span className="actionbar__score"> · IHC {form.score} · {category}</span> : null}
          </div>
          <div className="actionbar__buttons">
            <button type="button" className="btn" disabled={Boolean(saving)} onClick={() => save("draft")}
              {...(saving === "draft" ? { "data-busy": "" } : {})}>
              {t("review.actions.draft")}
            </button>
            <button type="button" className="btn" disabled={Boolean(saving)} onClick={() => save("preliminary")}
              {...(saving === "preliminary" ? { "data-busy": "" } : {})}>
              {t("review.actions.preliminary")}
            </button>
            <button type="button" className="btn btn--primary" disabled={Boolean(saving)}
              onClick={() => (form.score ? confirmRef.current?.showModal() : toast.error(t("review.failed"), t("review.scoreRequired")))}>
              <Icon name="check" size={16} /> {amends ? t("review.actions.amend") : t("review.actions.final")}
            </button>
          </div>
        </div>
      ) : null}

      <dialog ref={confirmRef} className="confirm-sign" onClick={(e) => { if (e.target === confirmRef.current) confirmRef.current.close(); }}>
        <h2>{t("review.confirmTitle")}</h2>
        <p>{t("review.confirmBody")}</p>
        <p><b>IHC {form.score}</b> · {category}{form.ish_decision ? ` · ISH: ${form.ish_decision}` : ""}</p>
        <label className="check">
          <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
          {t("review.fields.attest")}
        </label>
        <div className="confirm-sign__buttons">
          <button type="button" className="btn" onClick={() => confirmRef.current?.close()}>{t("common.cancel")}</button>
          <button type="button" className="btn btn--primary" disabled={!attest || Boolean(saving)} onClick={() => save("final")}
            {...(saving === "final" ? { "data-busy": "" } : {})}>
            <Icon name="check" size={16} /> {amends ? t("review.actions.amend") : t("review.actions.final")}
          </button>
        </div>
      </dialog>
    </div>
  );
}

/* ------------------------------------------------------------ pieces --- */

function Card({ title, children }) {
  return (
    <section className="card card--pad review__card">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Text({ id, t, form, set, placeholder, small }) {
  return (
    <div className={`field${small ? " review__small" : ""}`}>
      <label htmlFor={`rv-${id}`}>{t(`review.fields.${id}`)}</label>
      <input id={`rv-${id}`} className="input" value={form[id]} onChange={(e) => set(id)(e.target.value)}
        placeholder={placeholder ? t(`review.fields.${id}Ph`) : undefined} />
    </div>
  );
}

function Area({ id, t, form, set, rows, placeholder }) {
  return (
    <div className="field">
      <label htmlFor={`rv-${id}`}>{t(`review.fields.${id}`)}</label>
      <textarea id={`rv-${id}`} className="textarea" rows={rows} value={form[id]} onChange={(e) => set(id)(e.target.value)}
        placeholder={placeholder ? t(`review.fields.${id}Ph`) : undefined} />
    </div>
  );
}

function Select({ id, t, form, set, options = [] }) {
  return (
    <div className="field">
      <label htmlFor={`rv-${id}`}>{t(`review.fields.${id}`)}</label>
      <select id={`rv-${id}`} className="select" value={form[id]} onChange={(e) => set(id)(e.target.value)}>
        <option value="">—</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

function Choice({ id, t, form, set, options = [] }) {
  return (
    <div className="field">
      <span className="field-label">{t(`review.fields.${id}`)}</span>
      <div className="chips" role="radiogroup" aria-label={t(`review.fields.${id}`)}>
        {options.map((o) => (
          <button key={o} type="button" role="radio" aria-checked={form[id] === o}
            className={`chip-btn${form[id] === o ? " is-on" : ""}`} onClick={() => set(id)(form[id] === o ? "" : o)}>
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

function Multi({ id, t, form, toggle, options = [] }) {
  return (
    <div className="field">
      <span className="field-label">{t(`review.fields.${id}`)}</span>
      <div className="chips">
        {options.map((o) => (
          <button key={o} type="button" aria-pressed={form[id].includes(o)}
            className={`chip-btn${form[id].includes(o) ? " is-on" : ""}`} onClick={() => toggle(id, o)}>
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

function Worklist({ reviews, t, locale }) {
  return (
    <section className="card card--pad">
      <h2>{t("review.worklist")}</h2>
      {reviews.length ? (
        <div className="table-wrap">
          <table className="data data--stack">
            <thead>
              <tr>
                <th scope="col">{t("table.field")}</th>
                <th scope="col">{t("table.assessment")}</th>
                <th scope="col">Status</th>
                <th scope="col">ISH</th>
                <th scope="col">{t("table.reviewer")}</th>
                <th scope="col">{t("table.recorded")}</th>
              </tr>
            </thead>
            <tbody>
              {reviews.slice(0, 15).map((r) => (
                <tr key={r.id}>
                  <td className="mono cell-id" title={r.patch_id}>{r.accession ? `${r.accession} · ` : ""}{shortId(r.patch_id)}</td>
                  <td><b>IHC {r.score}</b></td>
                  <td><span className={`review__status review__status--${r.status ?? "final"}`}>{t(`review.status.${r.status ?? "final"}`)}</span></td>
                  <td className="muted">{r.ish_decision ?? "—"}</td>
                  <td>{r.reviewer}</td>
                  <td className="muted tiny">{dateTime(r.at, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="hint">{t("review.worklistEmpty")}</p>
      )}
    </section>
  );
}
