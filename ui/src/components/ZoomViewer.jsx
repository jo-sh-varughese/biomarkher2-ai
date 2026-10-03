/* A real zoom-and-pan view of one image (wheel / pinch to zoom, drag to
   move, buttons for keyboard and touch users). Built on OpenSeadragon, the
   same engine as the whole-slide viewer, so a field and a slide behave the
   same way under the pathologist's hand. It fills its parent: give the
   parent a height. */

import { useEffect, useRef } from "react";
import OpenSeadragon from "openseadragon";
import Icon from "./Icon.jsx";
import { useI18n } from "../i18n/I18nContext.jsx";

export default function ZoomViewer({ src, alt = "", className = "" }) {
  const { t } = useI18n();
  const el = useRef(null);
  const viewer = useRef(null);

  useEffect(() => {
    if (!src || !el.current) return undefined;
    const v = OpenSeadragon({
      element: el.current,
      tileSources: { type: "image", url: src, buildPyramid: false },
      showNavigationControl: false,
      showNavigator: false,
      maxZoomPixelRatio: 4,
      visibilityRatio: 0.6,
      gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
      gestureSettingsTouch: { pinchToZoom: true },
      animationTime: 0.4,
      crossOriginPolicy: false,
    });
    viewer.current = v;
    // OpenSeadragon measures its box once; the dialog it lives in can still be
    // animating open, so refit when the box settles.
    const ro = new ResizeObserver(() => v.viewport?.goHome(true));
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      v.destroy();
      viewer.current = null;
    };
  }, [src]);

  const zoom = (factor) => {
    const v = viewer.current;
    if (!v) return;
    v.viewport.zoomBy(factor);
    v.viewport.applyConstraints();
  };

  return (
    <div className={`zoomview ${className}`}>
      <div ref={el} className="zoomview__canvas" role="img" aria-label={alt} />
      <div className="zoomview__tools" role="group" aria-label={t("review.zoomHint")}>
        <button type="button" className="tool tool--icon" onClick={() => zoom(1.5)} aria-label="Zoom in" title="Zoom in">
          <Icon name="plus" size={15} />
        </button>
        <button type="button" className="tool tool--icon" onClick={() => zoom(1 / 1.5)} aria-label="Zoom out" title="Zoom out">
          <Icon name="minus" size={15} />
        </button>
        <button type="button" className="tool tool--icon" onClick={() => viewer.current?.viewport.goHome()} aria-label="Fit" title="Fit">
          <Icon name="maximize" size={15} />
        </button>
      </div>
    </div>
  );
}
