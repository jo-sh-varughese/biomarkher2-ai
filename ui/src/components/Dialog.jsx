/* A modal dialog, or a drawer that slides in from the right (`variant`).

   Rendered into <body> so no card's overflow or stacking context can clip
   it. While open: the page behind cannot scroll, Escape and the scrim close
   it, focus moves inside and Tab cycles within it, and focus returns to
   whatever opened it on close -- the keyboard behaviour a dialog owes
   people who don't use a mouse. */

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon.jsx";
import { useT } from "../i18n/I18nContext.jsx";

/* Dialogs can open over dialogs (a confirmation over the user drawer). Only
   the topmost one answers Escape and keeps Tab inside itself. */
const openStack = [];

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function Dialog({
  open,
  onClose,
  title,
  subtitle,
  icon,
  tone,
  children,
  footer,
  variant = "modal",
  size = "md",
  dismissible = true,
}) {
  const t = useT();
  const panelRef = useRef(null);
  const titleId = useId();
  const stackId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    const opener = document.activeElement;
    openStack.push(stackId);
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";

    const focusFirst = () => {
      const panel = panelRef.current;
      if (!panel) return;
      const preferred = panel.querySelector("[data-autofocus]") || panel.querySelector(FOCUSABLE);
      (preferred || panel).focus();
    };
    const frame = requestAnimationFrame(focusFirst);

    const onKey = (event) => {
      if (openStack[openStack.length - 1] !== stackId) return;
      if (event.key === "Escape" && dismissible) {
        event.stopPropagation();
        closeRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const items = [...panelRef.current.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      cancelAnimationFrame(frame);
      const at = openStack.lastIndexOf(stackId);
      if (at !== -1) openStack.splice(at, 1);
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = overflow;
      if (opener && typeof opener.focus === "function") opener.focus();
    };
  }, [open, dismissible, stackId]);

  if (!open) return null;

  return createPortal(
    <div className={`dialog-root dialog-root--${variant}`}>
      <div className="dialog-scrim" onMouseDown={dismissible ? onClose : undefined} aria-hidden="true" />
      <section
        ref={panelRef}
        className={`dialog dialog--${variant} dialog--${size}${tone ? ` dialog--${tone}` : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="dialog__head">
          {icon ? (
            <span className="dialog__icon" aria-hidden="true">
              <Icon name={icon} size={18} />
            </span>
          ) : null}
          <div className="dialog__titles">
            <h2 id={titleId}>{title}</h2>
            {subtitle ? <p className="sub">{subtitle}</p> : null}
          </div>
          {dismissible ? (
            <button type="button" className="btn btn--ghost btn--icon dialog__close" onClick={onClose} aria-label={t("common.close")}>
              <Icon name="x" size={18} />
            </button>
          ) : null}
        </header>
        <div className="dialog__body">{children}</div>
        {footer ? <footer className="dialog__foot">{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}
