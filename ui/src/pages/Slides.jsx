/* Whole-slide HER2 analysis.

   Left: the slides on the server. Centre: a zoomable OpenSeadragon viewer of
   the chosen slide, with the invasive-tumour map and the per-field grade map
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

const OVERLAYS = ["tumour_overlay", "grade_overlay"];

export default function Slides() {
  const { t } = useI18n();
  const { setReviewTarget } = usePortal();
  const navigate = useNavigate();
  const [slides, setSlides] = useState(null);
  const [error, setError] = useState(null);
  const [current, setCurrent] = useState(null);
  const [info, setInfo] = useState(null);
  const [job, setJob] = useState(null);
  const [overlay, setOverlay] = useState("tumour_overlay");
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
      label: name || current,
      image: result.images?.overview,
      ai_prescore: result.ai_prescore,
      cell_evidence: result.cell_evidence,
      guidance: result.guidance,
      measurements: { tumour: result.tumour, excluded: result.excluded, fields: result.fields?.length },
    });
    navigate("/review");
  };

  const zoomTo = (h) => {
    const v = viewer.current;
    if (!v || !info) return;
    const w = info.info.width;
    v.viewport.fitBounds(new OpenSeadragon.Rect(h.x / w, h.y / w, h.size / w, h.size / w));
  };

  return (
    <div className="page slides">
      <header className="page-head">
        <div>
          <h1>{t("slides.title")}</h1>
          <p className="sub">{t("slides.sub")}</p>
        </div>
      </header>
      {error ? <p className="prescore__warning" role="alert">{error}</p> : null}

      <div className="study">
        <div className="study__rail">
          <section className="card card--pad">
            <h2>{t("slides.list")}</h2>
            {slides === null ? (
              <p className="hint">{t("slides.loading")}</p>
            ) : slides.length === 0 ? (
              <p className="hint">{t("slides.empty")}</p>
            ) : (
              <ul className="slides__list">
                {slides.map((s) => (
                  <li key={s.id}>
                    <button type="button" className={`slides__item${current === s.id ? " is-active" : ""}`} onClick={() => setCurrent(s.id)}>
                      <Icon name="layers" size={14} /> <span>{s.name}</span>
                      <span className="hint">{s.size_mb} MB</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {info ? (
            <section className="card card--pad">
              <h2>{t("slides.details")}</h2>
              <p className="hint">
                {info.info.width}×{info.info.height} px · {info.info.mpp ? `${info.info.mpp.toFixed(3)} µm/px` : t("slides.mppUnknown")} ·{" "}
                {info.info.vendor}
              </p>
              {!info.magnification_ok ? <p className="prescore__flag">{t("slides.lowMag")}</p> : null}
              <button type="button" className="btn btn--primary btn--block" onClick={analyse}
                disabled={job && ["queued", "running"].includes(job.status)}>
                <Icon name="scan" size={16} /> {t("slides.analyse")}
              </button>
              {job && ["queued", "running"].includes(job.status) ? (
                <div className="slides__progress" aria-live="polite">
                  <div className="prescore__track"><span style={{ width: `${Math.round(job.fraction * 100)}%`, background: "var(--accent, #2a78d6)" }} /></div>
                  <p className="hint">{job.stage} · {Math.round(job.elapsed_s)} s</p>
                </div>
              ) : null}
              {job?.status === "error" ? <p className="prescore__warning">{job.error}</p> : null}
              {result ? (
                <>
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
                  <button type="button" className="btn btn--block" onClick={report}>
                    <Icon name="download" size={16} /> {t("slides.report")}
                  </button>
                </>
              ) : null}
            </section>
          ) : null}
        </div>

        <div className="study__main">
          <section className="card viewer">
            <div ref={viewerEl} className="slides__osd" aria-label={t("slides.viewer")}>
              {!current ? <p className="hint slides__placeholder">{t("slides.pick")}</p> : null}
            </div>
          </section>
          {result ? (
            <>
              <PrescorePanel analysis={result} />
              {result.cell_evidence?.decision_support ? (
                <DecisionPanel decision={result.cell_evidence.decision_support} guidance={result.guidance} />
              ) : null}
              {result.cell_evidence?.explanation ? <ExplainPanel explanation={result.cell_evidence.explanation} /> : null}
              {result.flags?.length ? (
                <section className="card card--pad">
                  <h2>{t("slides.flags")}</h2>
                  <ul>{result.flags.map((f) => <li key={f}>{f}</li>)}</ul>
                </section>
              ) : null}
              {result.hotspots?.length ? (
                <section className="card card--pad">
                  <h2>{t("slides.hotspots")}</h2>
                  <p className="sub">{t("slides.hotspotsSub")}</p>
                  <div className="slides__hotspots">
                    {result.hotspots.map((h) => (
                      <button key={h.index} type="button" className="slides__hotspot" onClick={() => zoomTo(h)}>
                        <img src={h.cells_image} alt="" />
                        <span>
                          {t("slides.field", { n: h.index + 1 })} · AI {h.prescore_category || "–"} · {t("slides.cells")} {h.cell_category}
                          {h.attention != null ? ` · ${Math.round(h.attention * 100)}%` : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </div>
      </div>

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
