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
import { Link, useNavigate } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import AnnotationLayer from "../components/AnnotationLayer.jsx";
import ZoomViewer from "../components/ZoomViewer.jsx";
import { HeatLegend, StackBar } from "../components/charts/Charts.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useToast } from "../state/ToastContext.jsx";
import {
  analyseField,
  downloadReport,
  readFileAsDataURL,
  saveAnnotation,
} from "../lib/api.js";
import {
  classForLabel,
  dateTime,
  dominantClass,
  LABEL_ORDER,
  pct,
  shortId,
  signed,
} from "../lib/format.js";
import { useI18n } from "../i18n/I18nContext.jsx";
import PrescorePanel from "../components/PrescorePanel.jsx";
import ExplainPanel from "../components/ExplainPanel.jsx";
import DecisionPanel from "../components/DecisionPanel.jsx";
import { resolveCaveats } from "../i18n/caveats.js";

/* The panels the server may return, in the order they should be offered.
   "ambiguity" only exists when a conformal calibration is loaded, and
   "isolate" only once a class is in focus (see focusName below), so the tab
   strip is filtered against what is actually available each render. */
// Shown as tabs on the viewer; the other views sit in its "More views" list.
const PRIMARY_VIEWS = ["original", "cells", "evidence", "isolate"];

const VIEWS = [
  { key: "original", hasNote: true },
  { key: "tissue", hasNote: true },
  { key: "model", hasNote: false },
  { key: "isolate", hasNote: true, dynamic: true },
  { key: "heatmap", hasNote: true },
  { key: "baseline", hasNote: true },
  { key: "ambiguity", hasNote: true },
  { key: "cells", hasNote: true },
  { key: "evidence", hasNote: true },
  { key: "regions", hasNote: true },
];

export default function Analysis() {
  const { context, analysis, setAnalysis, lastRequest, setLastRequest, setReviewTarget } = usePortal();
  const navigate = useNavigate();
  const { user, can } = useAuth();
  const toast = useToast();
  const { t, locale } = useI18n();
  // A viewer can analyse and export but never record a score or mark a
  // region; the server refuses both for that role, so the controls say so
  // up front instead of failing on submit.
  const canAnnotate = can("annotate");

  const [patchId, setPatchId] = useState("");
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [running, setRunning] = useState(false);
  const [reporting, setReporting] = useState(false);
  // Tumour site: the breast ASCO/CAP rules only apply to breast cancer.
  const [site, setSite] = useState("breast");
  const [view, setView] = useState("model");
  const [compare, setCompare] = useState(false);
  // Drawing is a mode, not the default: with the layer always live, a swipe
  // on the image could never scroll a phone's page and a click could never
  // open the enlarged view.
  const [annotating, setAnnotating] = useState(false);
  // The result is the AI pre-score + cell evidence panel; the stain-area
  // measurements support it and start folded so they are not read as a second
  // answer (a user saw "1+" here beside an AI "3+", 2026-10-02).
  const [detail, setDetail] = useState("decision");

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

  // The analysis survives navigation (it lives in PortalContext) but this
  // page's focus did not: coming back showed "—" and 0.0% in the stained-area
  // box. Restore the default focus whenever there is an analysis without one.
  useEffect(() => {
    if (!analysis || focusName || !classes.length) return;
    const labeled = analysis.dataset_label ? classForLabel(classes, analysis.dataset_label) : null;
    const dominant = labeled ? null : dominantClass(analysis.model_percentages);
    const next = labeled ?? (dominant ? classes.find((c) => c.name === dominant[0]) : null);
    if (next) setFocusName(next.name);
  }, [analysis, focusName, classes]);

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
        ? { image: await readFileAsDataURL(file), name: file.name, specimen: site }
        : { patch_id: patchId, specimen: site };
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
      // The pathologist reads the tissue first; the maps are one click away.
      setView("original");
      setDetail("decision");
      setCompare(false);
      setAnnotating(false);
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
  }, [file, patchId, site, classes, setAnalysis, setLastRequest, toast, t]);

  /* --------------------------------------------------- new analysis --- */

  const newAnalysis = () => {
    setAnalysis(null);
    setLastRequest(null);
    setFile(null);
    setFocusName(null);
    setAnnotating(false);
    setCompare(false);

    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const showView = (key) => {
    if (!analysis?.images?.[key]) return;
    setView(key);
    setCompare(false);
    document.querySelector(".viewer")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  /* ----------------------------------------------------------- review --- */

  const openReview = () => {
    if (!analysis) return;
    setReviewTarget({
      kind: "field",
      id: analysis.patch_id,
      case_id: analysis.case_id,
      label: analysis.display_name || analysis.patch_id,
      image: analysis.images?.original,
      ai_prescore: analysis.ai_prescore,
      cell_evidence: analysis.cell_evidence,
      guidance: analysis.guidance,
      quality: analysis.quality,
      measurements: {
        model: analysis.model_percentages,
        baseline: analysis.baseline_percentages,
        tissue_percent: analysis.tissue_percent,
      },
    });
    navigate("/review");
  };

  /* -------------------------------------------------------- annotate --- */

  const saveFieldAnnotation = useCallback(
    async (region) => {
      if (!analysis) return false;
      try {
        const result = await saveAnnotation({
          patch_id: analysis.patch_id,
          case_id: analysis.case_id,
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


  const openZoom = (key) => {
    setZoomed(key);
    dialogRef.current?.showModal();
  };

  /* The viewer's own tab strip carries the views a pathologist reaches for
     first; the rest sit in one "More views" list, so ten equal-weight tabs no
     longer compete for attention. */
  const primaryViews = availableViews.filter((v) => PRIMARY_VIEWS.includes(v.key));
  const moreViews = availableViews.filter((v) => !PRIMARY_VIEWS.includes(v.key));
  const viewTitle = (key) =>
    key === "isolate" ? t("analysis.views.isolate", { label: focusLabel ?? "" }) : t(`analysis.views.${key}`);
  const annotations = analysis?.annotations ?? [];
  const detailTabs = analysis
    ? [
        analysis.cell_evidence?.decision_support ? "decision" : null,
        analysis.cell_evidence?.explanation ? "explain" : null,
        "area",
        "regions",
        "limits",
      ].filter(Boolean)
    : [];
  const activeDetail = detailTabs.includes(detail) ? detail : detailTabs[0];

  const viewer = analysis ? (
    <section className="card viewer">
      <div className="viewer__bar">
        <div className="viewer__tabs" role="tablist" aria-label={t("analysis.layers")}>
          {primaryViews.map((v) => (
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
              {v.key === "isolate" ? t("analysis.tabs.isolate", { label: focusLabel ?? "" }) : t(`analysis.tabs.${v.key}`)}
            </button>
          ))}
          {moreViews.length ? (
            <select
              className={`viewer__more${moreViews.some((v) => v.key === view) && !compare ? " is-active" : ""}`}
              aria-label={t("field.moreViews")}
              value={moreViews.some((v) => v.key === view) ? view : ""}
              onChange={(e) => {
                if (!e.target.value) return;
                setView(e.target.value);
                setCompare(false);
              }}
            >
              <option value="">{t("field.moreViews")}…</option>
              {moreViews.map((v) => (
                <option key={v.key} value={v.key}>{viewTitle(v.key)}</option>
              ))}
            </select>
          ) : null}
        </div>
        <div className="viewer__tools">
          <button
            type="button"
            className={`tool tool--keep${annotating ? " is-on" : ""}`}
            onClick={() => setAnnotating((v) => !v)}
            aria-pressed={annotating}
            disabled={compare || !canAnnotate}
            title={canAnnotate ? t("analysis.annotate.toggleTitle") : t("roleGate.annotate")}
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
          <button type="button" className="tool" onClick={() => openZoom(view)} title={t("analysis.enlarge")}>
            <Icon name="search" size={15} />
            <span>{t("analysis.enlarge")}</span>
          </button>
        </div>
      </div>

      <div className={`viewer__stage${annotating ? " is-annotating" : ""}`}>
        {compare && analysis.images.baseline ? (
          <Wipe base={analysis.images.model} top={analysis.images.baseline} alt={t("analysis.compareCaption")} />
        ) : (
          <div className="viewer__frame">
            <img
              ref={imgRef}
              src={view === "isolate" ? isolateImage : analysis.images[view]}
              alt={viewTitle(view)}
              onClick={() => openZoom(view)}
            />
            <AnnotationLayer
              imgRef={imgRef}
              annotations={annotations}
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
          <b>{compare ? t("analysis.compareCaption") : viewTitle(view)}</b>
          <span>{compare ? t("analysis.compareNote") : viewNote(view, context, t)}</span>
        </div>
        {!compare && view === "heatmap" ? (
          <HeatLegend legend={context?.heatmap_legend} title={t("analysis.heatLegend")} lowLabel={t("analysis.heatLow")} />
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
    </section>
  ) : null;

  return (
    <>
      <div className="page__head page__head--compact">
        <div>
          <div className="eyebrow">{t("field.eyebrow")}</div>
          <h1>{t("analysis.title")}</h1>
          <p className="lede">{analysis ? t("field.ledeDone") : t("field.ledeEmpty")}</p>
        </div>
      </div>

      {analysis ? (
        <>
          <section className="card current-field" aria-live="polite">
            <span className="current-field__label">{t("analysis.current")}</span>
            <b className="mono" title={analysis.patch_id}>{analysis.display_name || shortId(analysis.patch_id)}</b>
            {analysis.dataset_label ? (
              <span className="badge badge--outline">{t("analysis.sourceLabel", { label: analysis.dataset_label })}</span>
            ) : null}
          </section>

          {/* Image and answer side by side: the pathologist reads the tissue
              and the suggestion together, without scrolling between them. */}
          <div className="result-top">
            <div className="result-top__image">{viewer}</div>
            <div className="result-top__answer">
              <PrescorePanel analysis={analysis} />
            </div>
          </div>

          <section className="card details" aria-labelledby="details-title">
            <div className="details__head">
              <h2 id="details-title">{t("field.detailsTitle")}</h2>
              <div className="details__tabs" role="tablist">
                {detailTabs.map((key) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={activeDetail === key}
                    className={`details__tab${activeDetail === key ? " is-active" : ""}`}
                    onClick={() => setDetail(key)}
                  >
                    {t(`field.tabs.${key}`)}
                    {key === "regions" && annotations.length ? <span className="details__count">{annotations.length}</span> : null}
                  </button>
                ))}
              </div>
            </div>

            <div className="details__body" role="tabpanel">
              {activeDetail === "decision" ? (
                <DecisionPanel decision={analysis.cell_evidence.decision_support} guidance={analysis.guidance} />
              ) : null}
              {activeDetail === "explain" ? (
                <ExplainPanel explanation={analysis.cell_evidence.explanation} onShowView={showView} />
              ) : null}
              {activeDetail === "area" ? (
                <AreaDetails
                  analysis={analysis}
                  classes={classes}
                  rows={rows}
                  focusLabel={focusLabel}
                  focusClass={focusClass}
                  focusPercent={focusPercent}
                  onFocus={(name) => {
                    focusOn(name);
                    document.querySelector(".viewer")?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                  caveats={caveats}
                  t={t}
                />
              ) : null}
              {activeDetail === "regions" ? (
                annotations.length ? (
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
                  <p className="hint">{t("field.noRegions")}</p>
                )
              ) : null}
              {activeDetail === "limits" ? (
                <>
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
                  <Link className="btn btn--ghost btn--sm" to="/method" style={{ marginTop: 12 }}>
                    {t("analysis.fullMethod")} <Icon name="arrowRight" size={14} />
                  </Link>
                </>
              ) : null}
            </div>
          </section>
        </>
      ) : (
        <div className="study study--empty">
          <div className="study__rail">
            <section className="card card--pad source">
              <h2 className="source__title">{t("analysis.source")}</h2>
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
                {sample && !file ? <p className="hint">{t("analysis.sampleHint", { label: sample.folder_label })}</p> : null}
              </div>

              <div className="or-rule">{t("analysis.or")}</div>

              <label
                className={`drop${dragOver ? " is-over" : ""}${file ? " has-file" : ""}`}
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
                <input type="file" accept="image/png,image/jpeg,image/tiff" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
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

              <div className="field">
                <label htmlFor="tumour-site">{t("analysis.tumourSite")}</label>
                <select id="tumour-site" className="select" value={site} onChange={(e) => setSite(e.target.value)}>
                  <option value="breast">{t("analysis.sites.breast")}</option>
                  <option value="gastric">{t("analysis.sites.gastric")}</option>
                  <option value="other">{t("analysis.sites.other")}</option>
                </select>
                <p className="hint">{t("analysis.tumourSiteHint")}</p>
              </div>

              <button
                type="button"
                className="btn btn--primary btn--lg btn--block"
                onClick={run}
                disabled={running}
                {...(running ? { "data-busy": "" } : {})}
              >
                <Icon name="scan" size={18} /> {t("analysis.analyse")}
              </button>
            </section>
          </div>
          <div className="study__main">
            <section className="card viewer">
              <div className="empty">
                <span className="empty__art">
                  <Icon name="scan" size={30} strokeWidth={1.5} />
                </span>
                <h3>{t("analysis.emptyTitle")}</h3>
                <p>{t("field.emptyBody")}</p>
              </div>
            </section>
          </div>
        </div>
      )}

      {/* --------------------------------------------------- action bar --- */}
      {analysis ? (
        <div className="actionbar" role="toolbar" aria-label={t("review.title")}>
          <div className="actionbar__info">
            {analysis.quality?.assessable === false ? (
              <b className="actionbar__blocked">{t("prescore.notAssessableShort")}</b>
            ) : null}
            {analysis.quality?.assessable !== false && analysis.ai_prescore?.shown && analysis.ai_prescore?.prescore ? (
              <>
                <span className="tiny muted">{t("prescore.label")}</span>{" "}
                <b>IHC {analysis.ai_prescore.prescore.category}</b>
              </>
            ) : null}
            {analysis.cell_evidence?.field_category ? (
              <span className="actionbar__score">
                {" "}· {t("review.cellEvidence")} IHC {analysis.cell_evidence.field_category}
              </span>
            ) : null}
            {analysis.guidance?.ish && analysis.quality?.assessable !== false ? (
              <span className="actionbar__score"> · {t(`prescore.ish.${analysis.guidance.ish.level}`)}</span>
            ) : null}
          </div>
          <div className="actionbar__buttons">
            <button type="button" className="btn" onClick={newAnalysis}>
              <Icon name="refresh" size={16} /> {t("analysis.another")}
            </button>
            <button type="button" className="btn" onClick={exportReport} disabled={reporting}
              {...(reporting ? { "data-busy": "" } : {})}>
              <Icon name="download" size={16} /> {t("analysis.pdfReport")}
            </button>
            <button type="button" className="btn btn--primary" onClick={openReview}>
              <Icon name="stethoscope" size={16} /> {t("review.open")}
            </button>
          </div>
        </div>
      ) : null}

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
            <ZoomViewer src={zoomed === "isolate" ? isolateImage : analysis.images[zoomed]} alt="" />
          ) : null}
        </div>
      </dialog>
    </>
  );
}

/* -------------------------------------------------------------- pieces --- */



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

/* The stained-area measurements, in one place: which intensity class to show
   on the image, the shares of tissue, the model beside the threshold
   baseline, and the caveat for 2+. A measurement of AREA, kept apart from the
   AI pre-score so it is not read as a second answer. */
function AreaDetails({ analysis, classes, rows, focusLabel, focusClass, focusPercent, onFocus, caveats, t }) {
  return (
    <div className="area">
      <p className="area__lead">{t("field.areaLead")}</p>
      <p className="hint">
        {t("field.tissueLine", { pct: pct(analysis.tissue_percent), w: analysis.width, h: analysis.height })}
      </p>

      <div className="area__pick">
        <span className="area__picklabel">{t("field.inspect")}:</span>
        <div className="class-picker" role="group" aria-label={t("analysis.classPickerLabel")}>
          {LABEL_ORDER.map((label) => {
            const c = classForLabel(classes, label);
            return (
              <button
                type="button"
                key={label}
                className={`class-pick${focusLabel === label ? " is-active" : ""}`}
                style={{ "--pick-color": c?.color }}
                onClick={() => onFocus(c?.name ?? null)}
              >
                {t(`analysis.intensityNames.${label}`)}
              </button>
            );
          })}
        </div>
        {focusClass ? (
          <span className="area__focus">
            <i style={{ background: focusClass.color }} /> {t("analysis.ofTissue", { pct: pct(focusPercent) })}
          </span>
        ) : null}
      </div>

      <StackBar
        segments={[
          ...rows.map((r) => ({ label: r.label, value: r.model, color: r.color })),
          ...(analysis.model_unclassified_percent
            ? [{ label: t("analysis.unclassified"), value: analysis.model_unclassified_percent, color: "var(--line)" }]
            : []),
        ]}
      />

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">{t("table.intensityClass")}</th>
              <th scope="col" className="num">{t("table.model")}</th>
              <th scope="col" className="num">{t("table.baseline")}</th>
              <th scope="col" className="num">{t("table.difference")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className={row.flagged ? "is-flagged" : undefined}>
                <td>
                  <span className="swatch" style={{ background: row.color }} />
                  {row.label}
                  {row.flagged ? (
                    <span className="badge badge--warn" style={{ marginLeft: 8 }}>
                      {t("analysis.leastReliable")}
                    </span>
                  ) : null}
                </td>
                <td className="num">{pct(row.model, 1)}</td>
                <td className="num">{pct(row.baseline, 1)}</td>
                <td className={`num delta ${Math.abs(row.delta) < 0.05 ? "delta--zero" : row.delta > 0 ? "delta--up" : "delta--down"}`}>
                  {signed(row.delta)}
                </td>
              </tr>
            ))}
            {analysis.model_unclassified_percent ? (
              <tr className="row-muted">
                <td>
                  <span className="swatch" style={{ background: "var(--line)" }} />
                  {t("analysis.unclassified")}
                </td>
                <td className="num">{pct(analysis.model_unclassified_percent, 1)}</td>
                <td className="num">{pct(0, 1)}</td>
                <td className="num" />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <p className="hint">
        {t("analysis.summary", { pct: pct(analysis.disagreement_percent) })}
        {analysis.conformal?.available
          ? t("analysis.summaryConformal", { alpha: analysis.conformal.alpha, pct: pct(analysis.conformal.ambiguous_percent) })
          : ""}
      </p>

      <div className="note note--caveat">
        <span className="note__icon">
          <Icon name="alert" size={15} />
        </span>
        <span>{caveats.model_limitation}</span>
      </div>

      {analysis.conformal?.stale_calibration ? (
        <div className="note note--danger" role="alert">
          <span className="note__icon">
            <Icon name="alert" size={16} />
          </span>
          <span>{t("analysis.staleCalibration")} <span className="mono">scripts/calibrate_conformal.py</span></span>
        </div>
      ) : null}
    </div>
  );
}
