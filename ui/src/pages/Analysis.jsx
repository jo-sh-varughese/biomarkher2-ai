/* ============================================================================
   Field analysis — the working screen.

   Layout follows the AIM-HER2 slide viewer: a review rail on the left holding
   the key result, the supporting measurements and the sign-off, with the
   imagery filling the rest. The one deliberate departure is the headline
   figure. AIM-HER2 shows "Algorithm Score: 2+ — do you accept?"; this model
   does not produce a score, so the Key Result leads with the FACT the
   dataset itself carries -- this field's own folder label, when there is
   one -- and reports the measurement for exactly that class: how much of it
   there is, and (via the "Where" panel) exactly where. The largest-area
   class is still shown when there is no dataset label to key off (an
   upload), but it is a fallback, not the headline concept: on a mostly
   negative field the largest class is rarely the one that mattered to
   whoever chose to score it. Dressing any of this up as a score would still
   be the single most dangerous thing this UI could do.
   ==========================================================================*/

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import AnnotationLayer from "../components/AnnotationLayer.jsx";
import { CompareBars, Donut, HeatLegend, StackBar } from "../components/charts/Charts.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useToast } from "../state/ToastContext.jsx";
import {
  analyseField,
  downloadReport,
  readFileAsDataURL,
  saveAnnotation,
  submitReview,
} from "../lib/api.js";
import {
  classForLabel,
  dateTime,
  dominantClass,
  isCannotAssess,
  LABEL_ORDER,
  pct,
  shortId,
  signed,
} from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";
import { resolveCaveats } from "../i18n/caveats.js";

/* The panels the server may return, in the order they should be offered.
   "ambiguity" only exists when a conformal calibration is loaded, and
   "isolate" only once a class is in focus (see focusName below), so the tab
   strip is filtered against what is actually available each render. */
const VIEWS = [
  { key: "original", hasNote: true },
  { key: "tissue", hasNote: true },
  { key: "model", hasNote: false },
  { key: "isolate", hasNote: true, dynamic: true },
  { key: "heatmap", hasNote: true },
  { key: "baseline", hasNote: true },
  { key: "ambiguity", hasNote: true },
];

export default function Analysis() {
  const { context, analysis, setAnalysis, lastRequest, setLastRequest, recordReview } = usePortal();
  const { user } = useAuth();
  const toast = useToast();
  const { t, locale } = useI18n();

  const [patchId, setPatchId] = useState("");
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [running, setRunning] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [view, setView] = useState("model");
  const [compare, setCompare] = useState(false);
  // Drawing is a mode, not the default: with the layer always live, a swipe
  // on the image could never scroll a phone's page and a click could never
  // open the enlarged view.
  const [annotating, setAnnotating] = useState(false);
  const [open, setOpen] = useState({ input: true, key: true, supporting: true, signoff: true });

  const [score, setScore] = useState("");
  const [agrees, setAgrees] = useState(false);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const dialogRef = useRef(null);
  const [zoomed, setZoomed] = useState(null);
  const imgRef = useRef(null);
  // The intensity class currently in focus for "how much, and where" -- the
  // name string model_percentages/isolate are keyed by (e.g. "moderate
  // (2+)"), not the short dataset-style label ("2+") the picker shows.
  const [focusName, setFocusName] = useState(null);

  useEffect(() => {
    if (!patchId && context?.samples?.length) setPatchId(context.samples[0].id);
  }, [context, patchId]);

  useEffect(() => {
    if (!annotating) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape" && !/^(INPUT|TEXTAREA)$/.test(event.target?.tagName ?? "")) {
        setAnnotating(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [annotating]);

  const sample = context?.samples?.find((s) => s.id === patchId);
  const classes = context?.classes ?? [];

  const availableViews = useMemo(
    () =>
      VIEWS.filter((v) =>
        v.dynamic ? Boolean(analysis?.isolate?.[focusName]) : analysis?.images && v.key in analysis.images,
      ),
    [analysis, focusName],
  );

  useEffect(() => {
    if (availableViews.length && !availableViews.some((v) => v.key === view)) {
      setView(availableViews[0].key);
    }
  }, [availableViews, view]);

  /* ------------------------------------------------------------- run --- */

  const run = useCallback(async () => {
    setRunning(true);
    try {
      const body = file
        ? { image: await readFileAsDataURL(file), name: file.name }
        : { patch_id: patchId };
      if (!file && !patchId) throw new Error(t("toast.chooseFirst"));

      const data = await analyseField(body);
      // Default the class in focus to what the DATA says this field is,
      // not whatever the model happened to measure the most area for --
      // that is the whole point of this screen leading with it. Only an
      // upload, with no dataset label to key off, falls back to the
      // model's own largest class.
      const labeled = data.dataset_label ? classForLabel(classes, data.dataset_label) : null;
      const dominant = labeled ? null : dominantClass(data.model_percentages);
      const dominantCls = dominant ? classes.find((c) => c.name === dominant[0]) : null;
      const nextFocus = (labeled ?? dominantCls)?.name ?? null;

      setAnalysis(data);
      setLastRequest(body);
      setFocusName(nextFocus);
      setView(nextFocus && data.isolate?.[nextFocus] ? "isolate" : "model");
      setCompare(false);
      setAnnotating(false);
      setScore("");
      setAgrees(false);
      setNotes("");
      if (data.demo) {
        toast.info(t("toast.demoTitle"), t("toast.demoBody"));
      } else {
        toast.ok(t("toast.analysedTitle"), t("toast.analysedBody"));
      }
    } catch (err) {
      toast.error(t("toast.analysisFailed"), err.message || String(err));
    } finally {
      setRunning(false);
    }
  }, [file, patchId, classes, setAnalysis, setLastRequest, toast, t]);

  /* ---------------------------------------------------------- sign-off --- */

  const saveReview = async (event) => {
    event.preventDefault();
    if (!analysis) return;
    if (!score) {
      toast.error(t("toast.selectTitle"), t("toast.selectBody"));
      return;
    }
    setSaving(true);
    try {
      const payload = {
        patch_id: analysis.patch_id,
        score,
        agrees,
        reviewer: user.name,
        notes,
        measurements: {
          model: analysis.model_percentages,
          baseline: analysis.baseline_percentages,
          tissue_percent: analysis.tissue_percent,
        },
      };
      const result = await submitReview(payload);
      recordReview({
        patch_id: analysis.patch_id,
        score,
        agrees,
        reviewer: user.name,
        notes,
        dataset_label: analysis.dataset_label ?? sample?.folder_label ?? null,
        tissue_percent: analysis.tissue_percent,
      });
      toast.ok(
        t("toast.recordedTitle"),
        result.demo ? t("toast.recordedDemo") : t("toast.recordedLive", { log: result.log }),
      );
    } catch (err) {
      toast.error(t("toast.recordFailed"), err.message || String(err));
    } finally {
      setSaving(false);
    }
  };

  /* -------------------------------------------------------- annotate --- */

  const saveFieldAnnotation = useCallback(
    async (region) => {
      if (!analysis) return false;
      try {
        const result = await saveAnnotation({
          patch_id: analysis.patch_id,
          x: region.x,
          y: region.y,
          w: region.w,
          h: region.h,
          note: region.note,
          score: region.score,
          reviewer: user.name,
        });
        const saved = result.annotation;
        setAnalysis((prev) => (prev ? { ...prev, annotations: [...(prev.annotations ?? []), saved] } : prev));
        toast.ok(
          t("analysis.annotate.savedTitle"),
          result.demo ? t("analysis.annotate.savedDemo") : t("analysis.annotate.savedLive"),
        );
        return true;
      } catch (err) {
        toast.error(t("analysis.annotate.failedTitle"), err.message || String(err));
        return false;
      }
    },
    [analysis, user, setAnalysis, toast, t],
  );

  /* Switching the class in focus jumps straight to "Where" when there is
     one to show -- the picker's whole job is "show me this instead", so
     leaving the viewer on whatever tab it already happened to be on would
     mean an extra click for the thing the picker was just used to ask for. */
  const focusOn = (name) => {
    setFocusName(name);
    if (name && analysis?.isolate?.[name]) setView("isolate");
  };

  const exportReport = async () => {
    if (!lastRequest) return;
    setReporting(true);
    try {
      await downloadReport(lastRequest);
      toast.ok(t("toast.reportTitle"), t("toast.reportBody"));
    } catch (err) {
      toast.error(t("toast.reportFailed"), err.message || String(err));
    } finally {
      setReporting(false);
    }
  };

  /* -------------------------------------------------------- derived --- */

  const rows = useMemo(() => {
    if (!analysis) return [];
    return classes
      .filter((c) => c.index > 0)
      .map((c) => {
        const model = analysis.model_percentages?.[c.name] ?? 0;
        const baseline = analysis.baseline_percentages?.[c.name] ?? 0;
        return {
          label: c.name,
          color: c.color,
          model,
          baseline,
          delta: model - baseline,
          // The class this model is known to be weakest on is flagged in the
          // table itself, not only in a caveat at the foot of the page --
          // a footnote is the first thing a screenshot crops out.
          flagged: c.index === 3,
        };
      });
  }, [analysis, classes]);

  const focusClass = classes.find((c) => c.name === focusName) ?? null;
  const focusLabel = focusClass ? LABEL_ORDER[focusClass.index - 1] : null;
  const focusPercent = analysis?.model_percentages?.[focusName];
  const isolateImage = analysis?.isolate?.[focusName] ?? null;
  const caveats = resolveCaveats(analysis?.caveats, analysis?.demo, t);

  const toggleSection = (key) => setOpen((o) => ({ ...o, [key]: !o[key] }));

  const openZoom = (key) => {
    setZoomed(key);
    dialogRef.current?.showModal();
  };

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("analysis.steps")}</div>
          <h1>{t("analysis.title")}</h1>
          <p className="lede">{t("analysis.lede")}</p>
        </div>
        <div className="page__actions">
          <button
            type="button"
            className="btn"
            onClick={exportReport}
            disabled={!analysis || reporting}
            {...(reporting ? { "data-busy": "" } : {})}
          >
            <Icon name="download" size={16} /> {t("analysis.pdfReport")}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={run}
            disabled={running}
            {...(running ? { "data-busy": "" } : {})}
          >
            <Icon name="scan" size={16} /> {t("analysis.analyse")}
          </button>
        </div>
      </div>

      <div className="study">
        {/* ------------------------------------------------- review rail --- */}
        <div className="study__rail">
          <section className="card" style={{ padding: "4px 18px" }}>
            {/* --- input --- */}
            <Section
              id="input"
              title={t("analysis.source")}
              open={open.input}
              onToggle={toggleSection}
              badge={file ? <span className="badge badge--accent">{t("analysis.upload")}</span> : null}
            >
              <div className="field">
                <label htmlFor="patch">{t("analysis.samplePatch")}</label>
                <select
                  id="patch"
                  className="select"
                  value={file ? "" : patchId}
                  disabled={Boolean(file) || !context?.samples?.length}
                  onChange={(e) => setPatchId(e.target.value)}
                >
                  {context?.samples?.length ? (
                    context.samples.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.folder_label} — {shortId(s.id)}
                        {s.split ? ` (${s.split})` : ""}
                      </option>
                    ))
                  ) : (
                    <option value="">{t("analysis.noSamples")}</option>
                  )}
                </select>
                {sample && !file ? (
                  <p className="hint">{t("analysis.sampleHint", { label: sample.folder_label })}</p>
                ) : null}
              </div>

              <div className="or-rule">{t("analysis.or")}</div>

              <label
                className={`drop${dragOver ? " is-over" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const dropped = e.dataTransfer.files?.[0];
                  if (dropped) setFile(dropped);
                }}
              >
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/tiff"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                <span className="drop__icon">
                  <Icon name="upload" size={22} />
                </span>
                <b>{file ? file.name : t("analysis.dropTitle")}</b>
                <span>{t("analysis.dropSub")}</span>
              </label>

              {file ? (
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setFile(null)}>
                  <Icon name="x" size={14} /> {t("analysis.clearUpload")}
                </button>
              ) : null}
            </Section>

            {/* --- key result --- */}
            {analysis ? (
              <Section
                id="key"
                title={t("analysis.keyResult")}
                open={open.key}
                onToggle={toggleSection}
                badge={<span className="badge badge--outline">{t("analysis.measurement")}</span>}
              >
                <div className="key-result">
                  <div className="eyebrow">
                    {analysis.dataset_label
                      ? t("analysis.sourceLabel", { label: analysis.dataset_label })
                      : t("analysis.pickClassLabel")}
                  </div>

                  <div className="class-picker" role="group" aria-label={t("analysis.classPickerLabel")}>
                    {LABEL_ORDER.map((label) => {
                      const c = classForLabel(classes, label);
                      return (
                        <button
                          type="button"
                          key={label}
                          className={`class-pick${focusLabel === label ? " is-active" : ""}`}
                          style={{ "--pick-color": c?.color }}
                          onClick={() => focusOn(c?.name ?? null)}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>

                  <div className="key-result__value">
                    <b style={{ "--mark": focusClass?.color }}>{focusLabel ?? "—"}</b>
                    <span>{t("analysis.ofTissue", { pct: pct(focusPercent) })}</span>
                  </div>

                  {isolateImage ? (
                    <button type="button" className="key-result__where" onClick={() => setView("isolate")}>
                      <img src={isolateImage} alt="" />
                      <span>
                        {t("analysis.seeWhere")} <Icon name="arrowRight" size={12} />
                      </span>
                    </button>
                  ) : null}

                  <p className="hint" style={{ marginTop: 10 }}>
                    {t("analysis.notAScoreLead")} <b>{t("analysis.notAScoreBold")}</b>
                    {t("analysis.notAScoreRest")}
                  </p>
                </div>

                <div style={{ display: "grid", gap: 10 }}>
                  <StackBar
                    segments={rows.map((r) => ({ label: r.label, value: r.model, color: r.color }))}
                  />
                  <div className="legend legend--plain">
                    {rows.map((r) => (
                      <span key={r.label}>
                        <i style={{ background: r.color }} />
                        {r.label} <b className="num">{pct(r.model)}</b>
                      </span>
                    ))}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                  <Donut
                    value={analysis.tissue_percent}
                    label={`Tissue coverage ${pct(analysis.tissue_percent)}`}
                  />
                  <div>
                    <div style={{ fontSize: "0.8125rem", fontWeight: 600 }}>{t("analysis.tissueCoverage")}</div>
                    <p className="hint">
                      {t("analysis.tissueCoverageNote", {
                        pct: pct(analysis.tissue_percent),
                        w: analysis.width,
                        h: analysis.height,
                      })}
                    </p>
                  </div>
                </div>
              </Section>
            ) : null}

            {/* --- supporting --- */}
            {analysis ? (
              <Section
                id="supporting"
                title={t("analysis.supporting")}
                open={open.supporting}
                onToggle={toggleSection}
              >
                <CompareBars rows={rows} modelLabel={t("table.model")} baselineLabel={t("table.baseline")} />

                <div className="note note--caveat">
                  <span className="note__icon">
                    <Icon name="alert" size={15} />
                  </span>
                  <span>{caveats.model_limitation}</span>
                </div>

                <div style={{ display: "grid", gap: 10 }}>
                  <Stat
                    label={t("analysis.disagreement")}
                    value={pct(analysis.disagreement_percent)}
                    hint={t("analysis.disagreementHint")}
                  />
                  {analysis.conformal?.available ? (
                    <Stat
                      label={t("analysis.ambiguous", { alpha: analysis.conformal.alpha })}
                      value={pct(analysis.conformal.ambiguous_percent)}
                      hint={t("analysis.ambiguousHint")}
                    />
                  ) : null}
                </div>

                {analysis.conformal?.stale_calibration ? (
                  <div className="note note--danger" role="alert">
                    <span className="note__icon">
                      <Icon name="alert" size={16} />
                    </span>
                    <span>
                      {t("analysis.staleCalibration")}{" "}
                      <span className="mono">scripts/calibrate_conformal.py</span>
                    </span>
                  </div>
                ) : null}
              </Section>
            ) : null}

            {/* --- sign-off --- */}
            {analysis ? (
              <Section id="signoff" title={t("analysis.signoff")} open={open.signoff} onToggle={toggleSection}>
                <form onSubmit={saveReview} style={{ display: "grid", gap: 14 }}>
                  <div className="field">
                    <span className="field-label">{t("analysis.yourAssessment")}</span>
                    <div className="score-picker">
                      {(context?.review_choices ?? []).map((choice) => {
                        const cannot = isCannotAssess(choice);
                        return (
                          <label key={choice} className="score-opt">
                            <input
                              type="radio"
                              name="score"
                              value={choice}
                              checked={score === choice}
                              onChange={() => setScore(choice)}
                            />
                            <b>{cannot ? "—" : choice}</b>
                            {cannot ? <span>{t("analysis.cannotAssess")}</span> : null}
                          </label>
                        );
                      })}
                    </div>
                  </div>

                  <label className="check">
                    <input type="checkbox" checked={agrees} onChange={(e) => setAgrees(e.target.checked)} />
                    {t("analysis.agrees")}
                  </label>

                  <div className="field">
                    <label htmlFor="notes">{t("analysis.notesLabel")}</label>
                    <textarea
                      id="notes"
                      className="textarea"
                      rows={3}
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder={t("analysis.notesPlaceholder")}
                    />
                  </div>

                  <div className="tiny muted">
                    {t("analysis.signingAs")} <b>{user.name}</b> · {user.registration}
                  </div>

                  <button
                    type="submit"
                    className="btn btn--primary btn--block"
                    disabled={saving}
                    {...(saving ? { "data-busy": "" } : {})}
                  >
                    <Icon name="check" size={16} /> {t("analysis.record")}
                  </button>
                </form>
              </Section>
            ) : null}
          </section>
        </div>

        {/* ------------------------------------------------------ imagery --- */}
        <div className="study__main">
          <section className="card viewer">
            {analysis ? (
              <>
                <div className="viewer__bar">
                  <div className="viewer__tabs" role="tablist" aria-label={t("analysis.layers")}>
                    {availableViews.map((v) => (
                      <button
                        key={v.key}
                        type="button"
                        role="tab"
                        aria-selected={!compare && view === v.key}
                        className={`viewer__tab${!compare && view === v.key ? " is-active" : ""}`}
                        onClick={() => {
                          setView(v.key);
                          setCompare(false);
                        }}
                      >
                        {v.key === "isolate"
                          ? t("analysis.tabs.isolate", { label: focusLabel ?? "" })
                          : t(`analysis.tabs.${v.key}`)}
                      </button>
                    ))}
                  </div>
                  <div className="viewer__tools">
                    <button
                      type="button"
                      className={`tool tool--keep${annotating ? " is-on" : ""}`}
                      onClick={() => setAnnotating((v) => !v)}
                      aria-pressed={annotating}
                      disabled={compare}
                      title={t("analysis.annotate.toggleTitle")}
                    >
                      <Icon name="pen" size={15} />
                      <span>{t(annotating ? "analysis.annotate.done" : "analysis.annotate.toggle")}</span>
                    </button>
                    {analysis.images.baseline ? (
                      <button
                        type="button"
                        className={`tool${compare ? " is-on" : ""}`}
                        onClick={() => {
                          setCompare((v) => !v);
                          setAnnotating(false);
                        }}
                        aria-pressed={compare}
                        title={t("analysis.compareTitle")}
                      >
                        <Icon name="layers" size={15} />
                        <span>{t("analysis.compare")}</span>
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="tool tool--icon"
                      onClick={() => openZoom(view)}
                      aria-label={t("analysis.enlarge")}
                      title={t("analysis.enlarge")}
                    >
                      <Icon name="search" size={15} />
                    </button>
                  </div>
                </div>

                <div className={`viewer__stage${annotating ? " is-annotating" : ""}`}>
                  {compare && analysis.images.baseline ? (
                    <Wipe
                      base={analysis.images.model}
                      top={analysis.images.baseline}
                      alt={t("analysis.compareCaption")}
                    />
                  ) : (
                    <div className="viewer__frame">
                      <img
                        ref={imgRef}
                        src={view === "isolate" ? isolateImage : analysis.images[view]}
                        alt={
                          view === "isolate"
                            ? t("analysis.views.isolate", { label: focusLabel ?? "" })
                            : t(`analysis.views.${view}`)
                        }
                        onClick={() => openZoom(view)}
                      />
                      <AnnotationLayer
                        imgRef={imgRef}
                        annotations={analysis.annotations ?? []}
                        reviewChoices={context?.review_choices}
                        onSave={saveFieldAnnotation}
                        disabled={!annotating}
                      />
                    </div>
                  )}
                  {annotating && !compare ? (
                    <span className="viewer__mode" role="status">
                      <Icon name="pen" size={13} /> {t("analysis.annotate.hint")}
                    </span>
                  ) : null}
                </div>

                <div className="viewer__caption">
                  <div className="viewer__caption-text">
                    <b>
                      {compare
                        ? t("analysis.compareCaption")
                        : view === "isolate"
                          ? t("analysis.views.isolate", { label: focusLabel ?? "" })
                          : t(`analysis.views.${view}`)}
                    </b>
                    <span>{compare ? t("analysis.compareNote") : viewNote(view, context, t)}</span>
                  </div>
                  {!compare && view === "heatmap" ? (
                    <HeatLegend
                      legend={context?.heatmap_legend}
                      title={t("analysis.heatLegend")}
                      lowLabel={t("analysis.heatLow")}
                    />
                  ) : null}
                  {compare || view === "model" || view === "baseline" ? (
                    <div className="legend legend--plain">
                      {classes
                        .filter((c) => c.index > 0)
                        .map((c) => (
                          <span key={c.name}>
                            <i style={{ background: c.color }} />
                            {c.name}
                          </span>
                        ))}
                    </div>
                  ) : null}
                  {!compare && view === "isolate" && focusClass ? (
                    <div className="legend legend--plain">
                      <span>
                        <i style={{ background: focusClass.color }} />
                        {focusClass.name} <b className="num">{pct(focusPercent)}</b>
                      </span>
                    </div>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="empty">
                <span className="empty__art">
                  <Icon name="scan" size={30} strokeWidth={1.5} />
                </span>
                <h3>{t("analysis.emptyTitle")}</h3>
                <p>{t("analysis.emptyBody")}</p>
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={run}
                  disabled={running}
                  {...(running ? { "data-busy": "" } : {})}
                >
                  <Icon name="scan" size={16} /> {t("analysis.analyse")}
                </button>
              </div>
            )}
          </section>

          {analysis ? (
            <section className="card card--pad">
              <div className="card-head">
                <div>
                  <h2>{t("analysis.tableTitle")}</h2>
                  <p className="sub">{t("analysis.tableSub")}</p>
                </div>
                <span className="badge badge--outline">
                  {analysis.width}×{analysis.height}
                </span>
              </div>

              <div className="table-wrap">
                <table className="data data--stack">
                  <thead>
                    <tr>
                      <th scope="col">{t("table.intensityClass")}</th>
                      <th scope="col" className="num">{t("table.model")}</th>
                      <th scope="col" className="num">{t("table.baseline")}</th>
                      <th scope="col" className="num">{t("table.difference")}</th>
                      <th scope="col">{t("table.share")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.label} className={row.flagged ? "is-flagged" : undefined}>
                        <td data-label={t("table.intensityClass")}>
                          <span className="swatch" style={{ background: row.color }} />
                          {row.label}
                          {row.flagged ? (
                            <span className="badge badge--warn" style={{ marginLeft: 8 }}>
                              {t("analysis.leastReliable")}
                            </span>
                          ) : null}
                        </td>
                        <td className="num" data-label={t("table.model")}>{pct(row.model, 2)}</td>
                        <td className="num" data-label={t("table.baseline")}>{pct(row.baseline, 2)}</td>
                        <td
                          data-label={t("table.difference")}
                          className={`num delta ${
                            Math.abs(row.delta) < 0.005
                              ? "delta--zero"
                              : row.delta > 0
                                ? "delta--up"
                                : "delta--down"
                          }`}
                        >
                          {signed(row.delta)}
                        </td>
                        {/* Decoration only -- the same number is in the Model
                            cell, so it is dropped rather than stacked. */}
                        <td style={{ minWidth: 120 }} data-hide-sm="" data-label={t("table.share")}>
                          <div
                            style={{
                              height: 6,
                              borderRadius: 99,
                              background: "var(--surface-sunken)",
                              overflow: "hidden",
                            }}
                          >
                            <div
                              style={{
                                width: `${Math.min(100, row.model)}%`,
                                height: "100%",
                                background: row.color,
                                borderRadius: 99,
                              }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="hint" style={{ marginTop: 14 }}>
                {t("analysis.summary", { pct: pct(analysis.disagreement_percent) })}
                {analysis.conformal?.available
                  ? t("analysis.summaryConformal", {
                      alpha: analysis.conformal.alpha,
                      pct: pct(analysis.conformal.ambiguous_percent),
                    })
                  : ""}
              </p>
            </section>
          ) : null}

          {/* The marked regions, listed rather than only findable by hunting
              for their (small, easy to miss) numbered boxes on the image. */}
          {analysis && (analysis.annotations ?? []).length ? (
            <section className="card card--pad">
              <div className="card-head">
                <div>
                  <h2>{t("analysis.annotate.title")}</h2>
                  <p className="sub">{t("analysis.annotate.listSub")}</p>
                </div>
                <span className="badge badge--outline">{analysis.annotations.length}</span>
              </div>
              <ul className="annot-list">
                {analysis.annotations.map((a, i) => (
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
            </section>
          ) : null}

          {/* The caveats travel with the measurements. Keeping them on the
              same screen -- not one page away -- is the whole reason the
              original single-page tool put them at the foot of the results. */}
          {analysis ? (
            <section className="card card--pad">
              <div className="card-head">
                <div>
                  <h2>{t("analysis.caveatsTitle")}</h2>
                  <p className="sub">{t("analysis.caveatsSub")}</p>
                </div>
                <Link className="btn btn--ghost btn--sm" to="/method">
                  {t("analysis.fullMethod")} <Icon name="arrowRight" size={14} />
                </Link>
              </div>
              <dl className="caveats">
                {["not_a_score", "denominator", "targets"].map((key) =>
                  caveats[key] ? (
                    <div key={key}>
                      <dt>{t(`method.caveatTitles.${key}`)}</dt>
                      <dd>{caveats[key]}</dd>
                    </div>
                  ) : null,
                )}
              </dl>
            </section>
          ) : null}
        </div>
      </div>

      {/* ------------------------------------------------------- lightbox --- */}
      <dialog
        ref={dialogRef}
        className="lightbox"
        onClick={(e) => {
          if (e.target === dialogRef.current) dialogRef.current.close();
        }}
        onClose={() => setZoomed(null)}
      >
        <div className="lightbox__head">
          <div>
            <b>
              {zoomed === "isolate"
                ? t("analysis.views.isolate", { label: focusLabel ?? "" })
                : zoomed
                  ? t(`analysis.views.${zoomed}`)
                  : ""}
            </b>
            <div className="tiny muted mono" title={analysis?.patch_id}>{shortId(analysis?.patch_id)}</div>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--icon btn--sm"
            onClick={() => dialogRef.current?.close()}
            aria-label={t("common.close")}
          >
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="lightbox__body">
          {zoomed && analysis ? (
            <img src={zoomed === "isolate" ? isolateImage : analysis.images[zoomed]} alt="" />
          ) : null}
        </div>
      </dialog>
    </>
  );
}

/* -------------------------------------------------------------- pieces --- */

function Section({ id, title, open, onToggle, badge, children }) {
  return (
    <div className="acc" data-open={open}>
      <button type="button" className="acc__btn" onClick={() => onToggle(id)} aria-expanded={open}>
        <span className="acc__chev">
          <Icon name="chevronRight" size={14} />
        </span>
        {title}
        {badge ? <span className="acc__badge">{badge}</span> : null}
      </button>
      {open ? <div className="acc__body">{children}</div> : null}
    </div>
  );
}

function Stat({ label, value, hint }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: 12,
        paddingBottom: 10,
        borderBottom: "1px solid var(--line-soft)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: "0.75rem", fontWeight: 600 }}>{label}</div>
        <p className="hint">{hint}</p>
      </div>
      <div className="num" style={{ fontSize: "1.05rem", fontWeight: 800, letterSpacing: "-0.03em" }}>
        {value}
      </div>
    </div>
  );
}

/* A draggable wipe between two registered images. Pointer events cover mouse,
   pen and touch in one path, and setPointerCapture keeps the drag alive when
   the cursor leaves the element. */
function Wipe({ base, top, alt }) {
  const ref = useRef(null);
  const [wipe, setWipe] = useState(50);

  const move = (event) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const next = ((event.clientX - box.left) / box.width) * 100;
    setWipe(Math.max(0, Math.min(100, next)));
  };

  return (
    <div
      className="compare"
      ref={ref}
      style={{ "--wipe": `${wipe}%` }}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        move(e);
      }}
      onPointerMove={(e) => {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) move(e);
      }}
    >
      <img src={base} alt={alt} draggable="false" />
      <img className="compare__top" src={top} alt="" draggable="false" />
      <span className="compare__handle" />
    </div>
  );
}

function viewNote(key, context, t) {
  const entry = VIEWS.find((v) => v.key === key);
  if (entry?.hasNote) return t(`analysis.views.${key}Note`);
  // The model panel names the architecture that produced it, which is a
  // run-time fact from the server rather than something to hardcode.
  const arch = context?.provenance?.architecture;
  return t("analysis.modelNote", {
    arch: arch ? arch.toUpperCase() : t("analysis.theModel"),
  });
}
