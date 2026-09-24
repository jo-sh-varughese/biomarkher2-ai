import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import Icon from "../components/Icon.jsx";
import { useT } from "../i18n/I18nContext.jsx";

const ToastContext = createContext(null);

const ICONS = { ok: "checkCircle", error: "alert", info: "info" };

export function ToastProvider({ children }) {
  const t = useT();
  const [items, setItems] = useState([]);
  const seq = useRef(0);

  const dismiss = useCallback((id) => {
    setItems((list) => list.filter((entry) => entry.id !== id));
  }, []);

  const push = useCallback(
    (toast) => {
      seq.current += 1;
      const id = seq.current;
      const entry = { tone: "info", ttl: 5200, ...toast, id };
      setItems((list) => [...list, entry]);
      if (entry.ttl) setTimeout(() => dismiss(id), entry.ttl);
      return id;
    },
    [dismiss],
  );

  const value = useMemo(
    () => ({
      push,
      dismiss,
      ok: (title, body) => push({ tone: "ok", title, body }),
      error: (title, body) => push({ tone: "error", title, body, ttl: 8000 }),
      info: (title, body) => push({ tone: "info", title, body }),
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.tone}`}>
            <span className="toast__icon">
              <Icon name={ICONS[toast.tone]} size={17} />
            </span>
            <div style={{ minWidth: 0 }}>
              <b>{toast.title}</b>
              {toast.body ? <p>{toast.body}</p> : null}
            </div>
            <button
              type="button"
              className="toast__close"
              onClick={() => dismiss(toast.id)}
              aria-label={t("toast.dismiss")}
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
