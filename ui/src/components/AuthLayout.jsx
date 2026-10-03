/* The split layout every signed-out screen shares: the form on one side,
   the poster on the other, the brand and language switch above the form.
   Language has to be switchable before sign-in, not only after: someone
   who reads Malayalam needs it on the first screen they see. */

import Icon from "./Icon.jsx";
import LangToggle from "./LangToggle.jsx";
import { useT } from "../i18n/I18nContext.jsx";

export default function AuthLayout({ children, wide = false, poster, siteName }) {
  const t = useT();
  return (
    <div className="auth">
      <section className="auth__form-side">
        <div className={`auth__inner${wide ? " auth__inner--wide" : ""}`}>
          <div className="auth__brand">
            <span className="brand__mark">
              <Icon name="logo" size={21} strokeWidth={1.7} />
            </span>
            <div>
              <div className="brand__name" style={{ fontSize: "1rem" }}>
                {siteName && siteName !== "BioMarkHER2" ? (
                  siteName
                ) : (
                  <>
                    BioMark<em>HER2</em>
                  </>
                )}
              </div>
              <div className="brand__sub">{t("common.tagline")}</div>
            </div>
            <span style={{ marginLeft: "auto" }}>
              <LangToggle />
            </span>
          </div>
          {children}
        </div>
      </section>

      <section className="auth__poster" aria-hidden="true">
        <span className="auth__orb auth__orb--a" />
        <span className="auth__orb auth__orb--b" />
        <span className="auth__orb auth__orb--c" />
        {poster?.chip ? (
          <span className="auth__chip">
            <Icon name={poster.chipIcon ?? "sparkles"} size={13} /> {poster.chip}
          </span>
        ) : null}
        {poster?.title ? <h2>{poster.title}</h2> : null}
        {poster?.body ? <p>{poster.body}</p> : null}
        {poster?.extra ?? null}
      </section>
    </div>
  );
}

export function FormNote({ tone = "danger", icon = "alert", children }) {
  return (
    <div className={`note note--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <span className="note__icon">
        <Icon name={icon} size={16} />
      </span>
      <span>{children}</span>
    </div>
  );
}
