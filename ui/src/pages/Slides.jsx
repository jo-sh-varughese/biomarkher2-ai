/* Whole-slide HER2 analysis.

   Left: the slides on the server. Centre: a zoomable OpenSeadragon viewer of
   the chosen slide, with the excluded-tissue map (controls, ink) and the per-field grade map
   as switchable overlays once the slide has been analysed. Below: the same
   pre-score / ISH guidance / cell-evidence panel the field view uses, at
   slide level, and the hotspot fields that weighed most. */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import OpenSeadragon from "openseadragon";
import PrescorePanel from "../components/PrescorePanel.jsx";
import DecisionPanel from "../components/DecisionPanel.jsx";
import ExplainPanel from "../components/ExplainPanel.jsx";
import Icon from "../components/Icon.jsx";
import { useI18n } from "../i18n/I18nContext.jsx";
import { apiRequest, downloadFile } from "../lib/api.js";
import { usePortal } from "../state/PortalContext.jsx";

const OVERLAYS = ["excluded_overlay", "grade_overlay"];

export default function Slides() {
  const { t } = useI18n();
  const { setReviewTarget } = usePortal();
  const navigate = useNavigate();
  const [slides, setSlides] = useState(null);
  const [error, setError] = useState(null);
  const [current, setCurrent] = useState(null);
  const [info, setInfo] = useState(null);
  const [job, setJob] = useState(null);
  const [overlay, setOverlay] = useState("excluded_overlay");
  const [detail, setDetail] = useState("decision");
  const viewerEl = useRef(null);
  const viewer = useRef(null);
  const overlayItem = useRef(null);

  useEffect(() => {
    apiRequest("/api/slides").then((d) => setSlides(d.slides)).catch((e) => setError(e.message));
  }, []);

  /* open the viewer on the chosen slide */
  useEffect(() => {
    if (!current || !viewerEl.current) return undefined;
    setInfo(null);
    setJob(null);
    apiRequest(`/api/slides/${current}/info`).then(setInfo).catch((e) => setError(e.message));
    apiRequest(`/api/slides/${current}/analysis`).then(setJob).catch(() => {});
    const v = OpenSeadragon({
      element: viewerEl.current,
      tileSources: `/api/slides/${current}/dzi`,
      prefixUrl: "https://cdn.jsdelivr.net/npm/openseadragon@4.1/build/openseadragon/images/",
      showNavigator: true,
      navigatorPosition: "BOTTOM_RIGHT",
      showNavigationControl: false,
      gestureSettingsMouse: { clickToZoom: false },
      crossOriginPolicy: false,
      loadTilesWithAjax: true,
      ajaxWithCredentials: true,
    });
    viewer.current = v;
    overlayItem.current = null;
    return () => {
      v.destroy();
      viewer.current = null;
    };
  }, [current]);

  /* poll while analysing */
  useEffect(() => {
    if (!current || !job || !["queued", "running"].includes(job.status)) return undefined;
    const id = setInterval(() => {
      apiRequest(`/api/slides/${current}/analysis`).then(setJob).catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [current, job]);

  /* draw the chosen overlay over the whole slide */
  const result = job?.status === "done" ? job.result : null;
  useEffect(() => {
    const v = viewer.current;
    if (!v || !result) return;
    const draw = () => {
      if (overlayItem.current) {
        v.world.removeItem(overlayItem.current);
        overlayItem.current = null;
      }
      if (!overlay) return;
      v.addTiledImage({
        tileSource: { type: "image", url: result.images[overlay] },
        x: 0,
        y: 0,
        width: 1,
        opacity: 0.45,
        success: (ev) => {
          overlayItem.current = ev.item;
        },
      });
    };
    if (v.world.getItemCount() > 0) draw();
    else v.addOnceHandler("open", draw);
  }, [result, overlay]);

  const analyse = async () => {
    try {
      setJob(await apiRequest(`/api/slides/${current}/analyze`, { method: "POST", body: {} }));
    } catch (e) {
      setError(e.message);
    }
  };

  const report = async () => {
    try {
      await downloadFile(`/api/slides/${current}/report`, "her2_slide_report.pdf");
    } catch (e) {
      setError(e.message);
    }
  };

  const openReview = () => {
    if (!result) return;
    const name = slides?.find((s) => s.id === current)?.name;
    setReviewTarget({
      kind: "slide",
      id: result.slide?.path || name || current,
      case_id: result.case_id,
      label: name || current,
      image: result.images?.overview,
      ai_prescore: result.ai_prescore,
      cell_evidence: result.cell_evidence,
      guidance: result.guidance,
      measurements: { tissue: result.tissue, stain_control: result.stain_control, excluded: result.excluded, fields: result.fields?.length },
    });
    navigate("/review");
  };

  const zoomTo = (h) => {
    const v = viewer.current;
    if (!v || !info) return;
    const w = info.info.width;
    v.viewport.fitBounds(new OpenSeadragon.Rect(h.x / w, h.y / w, h.size / w, h.size / w));
  };

  const running = job && ["queued", "running"].includes(job.status);
  const isHE = (name) => /(^|[_\-. ])(HE|H&E)([_\-. ]|$)/i.test(name) && !/HER2/i.test(name);
  const detailTabs = result
    ? [
        result.cell_evidence?.decision_support ? "decision" : null,
        result.cell_evidence?.explanation ? "explain" : null,
        result.hotspots?.length ? "hotspots" : null,
        result.flags?.length ? "flags" : null,
      ].filter(Boolean)
    : [];
  const activeDetail = detailTabs.includes(detail) ? detail : detailTabs[0];

  return (
    <div className="slides">
      <div className="page__head page__head--compact">
        <div>
          <div className="eyebrow">{t("slides.eyebrow")}</div>
          <h1>{t("slides.title")}</h1>
          <p className="lede">{t("slides.sub")}</p>
        </div>
      </div>
      {error ? <p className="prescore__warning" role="alert">{error}</p> : null}

      <div className="study">
        <div className="study__rail">
          <section className="card card--pad">
            <h2 className="source__title">{t("slides.list")}</h2>
            {slides === null ? (
              <p className="hint">{t("slides.loading")}</p>
            ) : slides.length === 0 ? (
              <p className="hint">{t("slides.empty")}</p>
            ) : (
              <ul className="slides__list">
                {slides.map((s) => (
                  <li key={s.id}>
                    <button type="button" className={`slides__item${current === s.id ? " is-active" : ""}`} onClick={() => setCurrent(s.id)}>
                      <Icon name="layers" size={16} />
                      <span className="slides__name">
                        <span>{s.name}</span>
                        {isHE(s.name) ? <span className="slides__he">{t("slides.heStain")}</span> : null}
                      </span>
                      <span className="hint">{s.size_mb} MB</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {info ? (
            <section className="card card--pad">
              <h2 className="source__title">{t("slides.details")}</h2>
              <p className="hint">
                {info.info.width}×{info.info.height} px · {info.info.mpp ? `${info.info.mpp.toFixed(3)} µm/px` : t("slides.mppUnknown")} ·{" "}
                {info.info.vendor}
              </p>
              {!info.magnification_ok ? <p className="prescore__flag">{t("slides.lowMag")}</p> : null}
              <button type="button" className="btn btn--primary btn--lg btn--block" onClick={analyse} disabled={running}
                {...(running ? { "data-busy": "" } : {})}>
                <Icon name="scan" size={18} /> {t("slides.analyse")}
              </button>
              {running ? (
                <div className="slides__progress" aria-live="polite">
                  <div className="prescore__track"><span style={{ width: `${Math.round(job.fraction * 100)}%`, background: "var(--accent, #2a78d6)" }} /></div>
                  <p className="hint">{job.stage} · {Math.round(job.elapsed_s)} s</p>
                </div>
              ) : null}
              {job?.status === "error" ? <p className="prescore__warning">{job.error}</p> : null}
              {result ? (
                <>
                  <div className="slides__overlaylabel">{t("slides.overlay")}</div>
                  <div className="toggle-row" role="group" aria-label={t("slides.overlay")}>
                    {OVERLAYS.map((o) => (
                      <button key={o} type="button" className={`chip${overlay === o ? " is-active" : ""}`} onClick={() => setOverlay(o)}>
                        {t(`slides.${o}`)}
                      </button>
                    ))}
                    <button type="button" className={`chip${!overlay ? " is-active" : ""}`} onClick={() => setOverlay(null)}>
                      {t("slides.noOverlay")}
                    </button>
                  </div>
                </>
              ) : null}
            </section>
          ) : null}
        </div>

        <div className="study__main">
          <section className="card viewer">
            <div ref={viewerEl} className={`slides__osd${current ? "" : " is-empty"}`} aria-label={t("slides.viewer")}>
              {!current ? (
                <div className="empty slides__placeholder">
                  <span className="empty__art">
                    <Icon name="layers" size={30} strokeWidth={1.5} />
                  </span>
                  <h3>{t("slides.pickTitle")}</h3>
                  <p>{t("slides.pickBody")}</p>
                </div>
              ) : null}
            </div>
          </section>
          {result ? <PrescorePanel analysis={result} /> : null}
        </div>
      </div>

      {result && detailTabs.length ? (
        <section className="card details" aria-labelledby="slide-details-title">
          <div className="details__head">
            <h2 id="slide-details-title">{t("field.detailsTitle")}</h2>
            <div className="details__tabs" role="tablist">
              {detailTabs.map((key) => (
                <button key={key} type="button" role="tab" aria-selected={activeDetail === key}
                  className={`details__tab${activeDetail === key ? " is-active" : ""}`} onClick={() => setDetail(key)}>
                  {key === "decision" || key === "explain" ? t(`field.tabs.${key}`) : t(`slides.${key}Tab`)}
                </button>
              ))}
            </div>
          </div>
          <div className="details__body" role="tabpanel">
            {activeDetail === "decision" ? (
              <DecisionPanel decision={result.cell_evidence.decision_support} guidance={result.guidance} />
            ) : null}
            {activeDetail === "explain" ? <ExplainPanel explanation={result.cell_evidence.explanation} /> : null}
            {activeDetail === "flags" ? <ul className="slides__flags">{result.flags.map((f) => <li key={f}>{f}</li>)}</ul> : null}
            {activeDetail === "hotspots" ? (
              <>
                <p className="hint">{t("slides.hotspotsSub")}</p>
                <div className="slides__hotspots">
                  {result.hotspots.map((h) => (
                    <button key={h.index} type="button" className="slides__hotspot" onClick={() => {
                      zoomTo(h);
                      viewerEl.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                    }}>
                      <img src={h.cells_image} alt="" />
                      <span>
                        {t("slides.field", { n: h.index + 1 })} · AI {h.prescore_category || "–"} · {t("slides.cells")} {h.cell_category}
                        {h.attention != null ? ` · ${Math.round(h.attention * 100)}%` : ""}
                      </span>
                    </button>
                  ))}
                </div>
              </>
            ) : null}
          </div>
        </section>
      ) : null}

      {result ? (
        <div className="actionbar" role="toolbar" aria-label={t("review.title")}>
          <div className="actionbar__info">
            <b>{slides?.find((s) => s.id === current)?.name}</b>
            {result.guidance?.ish ? <span className="actionbar__score"> · {t(`prescore.ish.${result.guidance.ish.level}`)}</span> : null}
          </div>
          <div className="actionbar__buttons">
            <button type="button" className="btn" onClick={report}>
              <Icon name="download" size={16} /> {t("slides.report")}
            </button>
            <button type="button" className="btn btn--primary" onClick={openReview}>
              <Icon name="stethoscope" size={16} /> {t("review.openSlide")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
