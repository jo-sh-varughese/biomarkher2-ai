import { LANGS, useI18n } from "../i18n/I18nContext.jsx";

/* A two-state segmented control rather than a dropdown. With exactly two
   languages a select would hide the alternative behind a click, and each
   option is short enough to show both at once -- so the reader can see that
   Malayalam exists without going looking for it. Each label is rendered in
   its own language, and carries its own lang attribute so the browser picks
   the right font and a screen reader the right voice. */
export default function LangToggle({ size = "sm" }) {
  const { lang, setLang, t } = useI18n();

  return (
    <div
      className={`lang-toggle${size === "lg" ? " lang-toggle--lg" : ""}`}
      role="group"
      aria-label={t("common.language")}
    >
      {LANGS.map((entry) => (
        <button
          key={entry.id}
          type="button"
          lang={entry.id}
          className={`lang-toggle__btn${lang === entry.id ? " is-active" : ""}`}
          aria-pressed={lang === entry.id}
          title={entry.label}
          onClick={() => setLang(entry.id)}
        >
          {entry.short}
        </button>
      ))}
    </div>
  );
}
