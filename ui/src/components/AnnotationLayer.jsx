/* ============================================================================
   Field annotations -- draw a box on the image, attach a note and/or a
   score to just that region.

   Coordinates are stored as fractions of the image (0-1), measured off the
   <img> element's OWN rendered box (via imgRef), not the surrounding stage.
   That is what makes a saved box line up correctly after a browser resize,
   and what lets the exact same box be drawn over the "original", "model" or
   "baseline" view without knowing which one was active when it was drawn --
   the region is a fact about the field, not about one rendering of it.

   This is a narrower, more targeted cousin of the whole-field sign-off
   already at the bottom of the review rail: that one is "here is my overall
   read of this field"; this one is "look here specifically". Saved
   annotations are permanent, like the sign-off log -- there is no edit or
   delete once the server has accepted one, only while it is still a draft.
   ========================================================================= */

import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";
import { useT } from "../i18n/I18nContext.jsx";

const MIN_BOX = 0.015; // fraction of the image's shorter dimension

export default function AnnotationLayer({ imgRef, annotations, reviewChoices, onSave, disabled }) {
  const layerRef = useRef(null);
  const dragging = useRef(false);
  const t = useT();

  const [draft, setDraft] = useState(null); // live drag rectangle, fractions
  const [pending, setPending] = useState(null); // finished rectangle awaiting note/score
  const [activeId, setActiveId] = useState(null);
  const [saving, setSaving] = useState(false);

  // Leaving draw mode abandons a box that was drawn but never saved; saved
  // ones stay on screen and clickable (see .annot-layer.is-disabled).
  useEffect(() => {
    if (disabled) {
      setPending(null);
      setDraft(null);
      dragging.current = false;
    } else {
      setActiveId(null);
    }
  }, [disabled]);

  const fractionAt = useCallback(
    (event) => {
      const rect = imgRef.current?.getBoundingClientRect();
      if (!rect || !rect.width || !rect.height) return null;
      return {
        x: clamp01((event.clientX - rect.left) / rect.width),
        y: clamp01((event.clientY - rect.top) / rect.height),
      };
    },
    [imgRef],
  );

  const start = (event) => {
    if (disabled || pending) return;
    const p = fractionAt(event);
    if (!p) return;
    event.preventDefault();
    dragging.current = true;
    layerRef.current?.setPointerCapture(event.pointerId);
    setActiveId(null);
    setDraft({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };

  const move = (event) => {
    if (!dragging.current) return;
    const p = fractionAt(event);
    if (!p) return;
    setDraft((d) => (d ? { ...d, x1: p.x, y1: p.y } : d));
  };

  const end = () => {
    if (!dragging.current) return;
    dragging.current = false;
    setDraft((d) => {
      if (!d) return null;
      const region = rectFrom(d);
      // A drag under ~1.5% of the frame reads as a stray click, not a
      // deliberate region -- drop it instead of opening a form for it.
      if (region.w > MIN_BOX && region.h > MIN_BOX) setPending(region);
      return null;
    });
  };

  const cancel = () => setPending(null);

  const submit = async (note, score) => {
    if (!pending) return;
    setSaving(true);
    const ok = await onSave({ ...pending, note, score });
    setSaving(false);
    if (ok) setPending(null);
  };

  return (
    <div
      ref={layerRef}
      className={`annot-layer${disabled ? " is-disabled" : ""}`}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={() => {
        dragging.current = false;
        setDraft(null);
      }}
    >
      {annotations.map((a, i) => (
        <button
          type="button"
          key={a.id ?? i}
          className={`annot-box${activeId === (a.id ?? i) ? " is-active" : ""}`}
          style={boxStyle(a)}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            setActiveId((cur) => (cur === (a.id ?? i) ? null : a.id ?? i));
          }}
        >
          <span className="annot-box__tag">{i + 1}</span>
        </button>
      ))}

      {draft ? <span className="annot-box annot-box--draft" style={boxStyle(rectFrom(draft))} /> : null}

      {pending ? (
        <div className="annot-form" style={popoverStyle(pending)} onPointerDown={(e) => e.stopPropagation()}>
          <AnnotationForm reviewChoices={reviewChoices} saving={saving} t={t} onCancel={cancel} onSubmit={submit} />
        </div>
      ) : null}

      {activeId != null
        ? (() => {
            const a = annotations.find((x, i) => (x.id ?? i) === activeId);
            if (!a) return null;
            return (
              <div
                className="annot-popover"
                style={popoverStyle(a)}
                onPointerDown={(e) => e.stopPropagation()}
              >
                <div className="annot-popover__head">
                  {a.score ? <b>{a.score}</b> : null}
                  <button
                    type="button"
                    className="btn btn--ghost btn--icon btn--sm"
                    onClick={() => setActiveId(null)}
                    aria-label={t("common.close")}
                  >
                    <Icon name="x" size={13} />
                  </button>
                </div>
                {a.note ? <p>{a.note}</p> : null}
                <span className="tiny muted">{a.reviewer}</span>
              </div>
            );
          })()
        : null}
    </div>
  );
}

function AnnotationForm({ reviewChoices, saving, t, onCancel, onSubmit }) {
  const [note, setNote] = useState("");
  const [score, setScore] = useState("");

  const submit = (event) => {
    event.preventDefault();
    onSubmit(note.trim(), score);
  };

  return (
    <form onSubmit={submit} className="annot-form__body">
      <textarea
        autoFocus
        rows={2}
        className="textarea"
        placeholder={t("analysis.annotate.notePlaceholder")}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="score-picker score-picker--compact">
        {/* "Cannot assess" is a whole-field sign-off answer (see the review
            rail below) -- a region too small or unclear to score here just
            gets a note and no score, rather than a fifth button that would
            need its own layout exception in this compact grid. */}
        {(reviewChoices ?? [])
          .filter((choice) => choice !== "cannot assess from this field")
          .map((choice) => (
            <label key={choice} className="score-opt">
              <input
                type="radio"
                name="annot-score"
                value={choice}
                checked={score === choice}
                onChange={() => {}}
                // A radio's onChange only fires when the checked value
                // actually changes, so clicking the already-selected choice
                // to clear it (this score is optional, unlike the sign-off
                // one) has to be handled on click instead.
                onClick={() => setScore((s) => (s === choice ? "" : choice))}
              />
              <b>{choice}</b>
            </label>
          ))}
      </div>
      <div className="annot-form__actions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>
          {t("analysis.annotate.cancel")}
        </button>
        <button
          type="submit"
          className="btn btn--primary btn--sm"
          disabled={saving || (!note.trim() && !score)}
          {...(saving ? { "data-busy": "" } : {})}
        >
          {t("analysis.annotate.save")}
        </button>
      </div>
    </form>
  );
}

function clamp01(n) {
  return Math.max(0, Math.min(1, n));
}

function rectFrom(d) {
  return {
    x: Math.min(d.x0, d.x1),
    y: Math.min(d.y0, d.y1),
    w: Math.abs(d.x1 - d.x0),
    h: Math.abs(d.y1 - d.y0),
  };
}

function boxStyle(r) {
  return {
    left: `${r.x * 100}%`,
    top: `${r.y * 100}%`,
    width: `${r.w * 100}%`,
    height: `${r.h * 100}%`,
  };
}

/* Floating cards anchor at the box's top-right corner, clamped so they do
   not run off the edge of the frame -- there is no viewport-aware
   repositioning here, just enough margin that the common case (a box drawn
   somewhere in the middle two-thirds of the image) never clips. */
function popoverStyle(r) {
  return {
    left: `${Math.min(r.x + r.w, 0.72) * 100}%`,
    top: `${Math.min(r.y, 0.8) * 100}%`,
  };
}
