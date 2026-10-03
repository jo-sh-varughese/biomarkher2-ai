/* "Are you sure?" -- for actions that are hard to undo. A destructive one
   can also ask the person to type a phrase (an email address) before the
   button unlocks, so a slipped click cannot delete an account. */

import { useEffect, useState } from "react";
import Dialog from "./Dialog.jsx";
import Icon from "./Icon.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { errorText } from "../lib/auth.js";

export default function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  tone = "danger",
  icon = "alert",
  typeToConfirm,
  typeLabel,
  onConfirm,
  onClose,
  children,
}) {
  const t = useT();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setTyped("");
      setBusy(false);
      setError(null);
    }
  }, [open]);

  const unlocked = !typeToConfirm || typed.trim().toLowerCase() === typeToConfirm.toLowerCase();

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={busy ? () => {} : onClose}
      title={title}
      icon={icon}
      tone={tone}
      size="sm"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className={`btn ${tone === "danger" ? "btn--danger" : "btn--primary"}`}
            onClick={confirm}
            disabled={!unlocked || busy}
            {...(busy ? { "data-busy": "" } : {})}
            data-autofocus={typeToConfirm ? undefined : ""}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <p className="dialog__text">{body}</p>
      {children}
      {typeToConfirm ? (
        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="confirm-type">{typeLabel}</label>
          <input
            id="confirm-type"
            className="input mono"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            data-autofocus=""
          />
        </div>
      ) : null}
      {error ? (
        <div className="note note--danger" role="alert" style={{ marginTop: 14 }}>
          <span className="note__icon">
            <Icon name="alert" size={16} />
          </span>
          <span>{errorText(error, t)}</span>
        </div>
      ) : null}
    </Dialog>
  );
}
