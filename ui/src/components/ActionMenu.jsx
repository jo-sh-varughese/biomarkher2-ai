/* The "⋯" button on a table row: a short menu of actions for that row.
   Items that do not apply are left out rather than shown disabled, so the
   menu only ever offers what can actually be done. */

import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

export default function ActionMenu({ label, items }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  // Hidden items go; so do dividers left leading, trailing or doubled.
  const visible = items
    .filter((item) => item && !item.hidden)
    .filter((item, i, list) => !item.divider || (i > 0 && i < list.length - 1 && !list[i - 1].divider));

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!visible.length) return null;

  return (
    <div className="action-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="btn btn--ghost btn--icon btn--sm"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <Icon name="more" size={17} />
      </button>
      {open ? (
        <div className="menu action-menu__list" role="menu">
          {visible.map((item, index) =>
            item.divider ? (
              <hr key={`d${index}`} className="menu__rule" />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className={`menu__item${item.tone === "danger" ? " menu__item--danger" : ""}`}
                onClick={(event) => {
                  event.stopPropagation();
                  setOpen(false);
                  item.onClick();
                }}
              >
                {item.icon ? <Icon name={item.icon} size={16} /> : null}
                {item.label}
              </button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}
