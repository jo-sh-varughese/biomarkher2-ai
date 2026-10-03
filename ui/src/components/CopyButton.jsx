import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import { useT } from "../i18n/I18nContext.jsx";

/* Copies `text` and says so. Falls back to a hidden textarea where the
   Clipboard API is refused (plain-HTTP origins other than localhost). */
export default function CopyButton({ text, compact = false, label }) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
  };

  return (
    <button
      type="button"
      className={compact ? "link-btn" : "btn btn--sm"}
      onClick={copy}
      aria-live="polite"
    >
      <Icon name={copied ? "check" : "copy"} size={compact ? 13 : 15} />
      {copied ? t("password.copied") : (label ?? t("password.copy"))}
    </button>
  );
}
