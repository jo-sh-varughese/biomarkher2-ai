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
import { apiRequest, downloadFile, uploadFile } from "../lib/api.js";
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
  // Pathologist-marked invasive tumour, as level-0 slide boxes {x, y, w, h}. When present, the
  // analysis places its fields only inside them (wsi/analysis.py SlideAnalyzer.run regions=...).
  const [regions, setRegions] = useState([]);
  const [marking, setMarking] = useState(false);
  const [draft, setDraft] = useState(null);
  const [uploading, setUploading] = useState(null); // upload progress 0..1, null when idle
  const fileInput = useRef(null);
  const drawStart = useRef(null);
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
    setRegions([]);
    setMarking(false);
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

  /* marked regions are drawn as viewer overlays, so they stay put while panning and zooming */
  useEffect(() => {
    const v = viewer.current;
    if (!v) return undefined;
    const draw = () => {
      v.clearOverlays();
      regions.forEach((g, i) => {
        const el = document.createElement("div");
        el.className = "slides__roi";
        el.dataset.n = String(i + 1);
        v.addOverlay({ element: el, location: v.viewport.imageToViewportRectangle(g.x, g.y, g.w, g.h) });
      });
    };
    if (v.world.getItemCount() > 0) draw();
    else v.addOnceHandler("open", draw);
    return undefined;
  }, [regions, current]);

  /* panning is off while marking, so a drag draws a box instead of moving the slide */
  useEffect(() => {
    viewer.current?.setMouseNavEnabled(!marking);
  }, [marking]);

  const toImage = (event) => {
    const v = viewer.current;
    const box = viewerEl.current?.getBoundingClientRect();
    if (!v || !box) return null;
    const p = v.viewport.viewerElementToImageCoordinates(new OpenSeadragon.Point(event.clientX - box.left, event.clientY - box.top));
    return { x: p.x, y: p.y, sx: event.clientX - box.left, sy: event.clientY - box.top };
  };

  const drawDown = (event) => {
    const p = toImage(event);
    if (!p) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drawStart.current = p;
    setDraft({ left: p.sx, top: p.sy, width: 0, height: 0 });
  };
  const drawMove = (event) => {
    const a = drawStart.current;
    const p = a && toImage(event);
    if (!p) return;
    setDraft({ left: Math.min(a.sx, p.sx), top: Math.min(a.sy, p.sy), width: Math.abs(p.sx - a.sx), height: Math.abs(p.sy - a.sy) });
  };
  const drawUp = (event) => {
    const a = drawStart.current;
    const p = a && toImage(event);
    drawStart.current = null;
    setDraft(null);
    if (!p || !info) return;
    const x0 = Math.max(0, Math.min(a.x, p.x));
    const y0 = Math.max(0, Math.min(a.y, p.y));
    const x1 = Math.min(info.info.width, Math.max(a.x, p.x));
    const y1 = Math.min(info.info.height, Math.max(a.y, p.y));
    // ignore a click or a sliver: a region must be at least ~250 um across at 0.25 um/px
    if (x1 - x0 < 1000 || y1 - y0 < 1000) return;
    setRegions((list) => [...list, { x: Math.round(x0), y: Math.round(y0), w: Math.round(x1 - x0), h: Math.round(y1 - y0) }]);
  };

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

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // so the same file can be chosen again
    if (!file) return;
    setError(null);
    setUploading(0);
    try {
      const added = await uploadFile(`/api/slides/upload?name=${encodeURIComponent(file.name)}`, file, setUploading);
      const d = await apiRequest("/api/slides");
      setSlides(d.slides);
      setCurrent(added.id);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(null);
    }
  };

  const analyse = async () => {
    try {
      setMarking(false);
      setJob(await apiRequest(`/api/slides/${current}/analyze`, { method: "POST", body: regions.length ? { regions } : {} }));
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
            <input ref={fileInput} type="file" hidden onChange={upload}
              accept=".svs,.ndpi,.mrxs,.scn,.tif,.tiff,.bif,.vms,.vmu,.svslide,.png,.jpg,.jpeg" />
            <button type="button" className="btn btn--block" onClick={() => fileInput.current?.click()}
              disabled={uploading !== null} {...(uploading !== null ? { "data-busy": "" } : {})}>
              <Icon name="upload" size={16} /> {uploading !== null ? t("slides.uploading", { pct: Math.round(uploading * 100) }) : t("slides.upload")}
            </button>
            {uploading !== null ? (
              <div className="slides__progress" aria-live="polite">
                <div className="prescore__track"><span style={{ width: `${Math.round(uploading * 100)}%`, background: "var(--accent, #2a78d6)" }} /></div>
              </div>
            ) : null}
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
              <div className="slides__regions">
                <div className="toggle-row">
                  <button type="button" className={`chip${marking ? " is-active" : ""}`} onClick={() => setMarking((m) => !m)}
                    disabled={running}>
                    <Icon name="pen" size={14} /> {marking ? t("slides.doneMarking") : t("slides.markRegions")}
                  </button>
                  {regions.length ? (
                    <button type="button" className="chip" onClick={() => setRegions([])} disabled={running}>
                      <Icon name="x" size={14} /> {t("slides.clearRegions")}
                    </button>
                  ) : null}
                </div>
                <p className="hint">{regions.length ? t("slides.regionsCount", { n: regions.length }) : t("slides.regionsHint")}</p>
              </div>
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
            {marking && current ? (
              <div className="slides__drawlayer" onPointerDown={drawDown} onPointerMove={drawMove} onPointerUp={drawUp}
                onPointerCancel={() => { drawStart.current = null; setDraft(null); }}>
                <span className="viewer__mode" role="status"><Icon name="pen" size={13} /> {t("slides.markingMode")}</span>
                {draft ? <span className="slides__roi slides__roi--draft" style={draft} /> : null}
              </div>
            ) : null}
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
