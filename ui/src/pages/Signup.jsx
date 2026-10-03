/* ============================================================================
   Sign-up.

   Mirrors the login screen's split layout so the two read as one flow. Two
   things it does deliberately:

   - The notice about what this account actually is sits ABOVE the submit
     button, not in small print underneath it. Someone is about to type a
     password; the fact that there is no server behind this is information
     they need before they type, not after they have committed.

   - Field errors appear on blur and on submit, never on every keystroke.
     Telling someone their email is invalid while they are still on the third
     character is noise, and it trains people to ignore the message that
     matters.
   ==========================================================================*/

import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import LangToggle from "../components/LangToggle.jsx";
import AuthLayout, { FormNote } from "../components/AuthLayout.jsx";
import PasswordField from "../components/PasswordField.jsx";
import {
  ROLE_KEYS,
  passwordStrength,
  useAuth,
  validateSignup,
} from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { errorText } from "../lib/auth.js";

const STRENGTH_COLORS = [
  "var(--line-strong)",
  "var(--danger)",
  "var(--warn)",
  "var(--accent)",
  "var(--ok)",
];

/* With a server behind the portal, this page asks for an account rather
   than creating one: the request waits, as a pending account, until an
   administrator approves it and chooses what the person may do. With no
   server (the static demo) it keeps the original browser-only sign-up. */
export default function Signup() {
  const { isServer } = useAuth();
  return isServer ? <RequestAccess /> : <DemoSignup />;
}

function DemoSignup() {
  const { user, signUp } = useAuth();
  const t = useT();

  const [form, setForm] = useState({
    name: "",
    email: "",
    registration: "",
    roleKey: ROLE_KEYS[0],
    password: "",
    confirm: "",
    accepted: false,
  });
  const [touched, setTouched] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);

  if (user) return <Navigate to="/overview" replace />;

  const errors = validateSignup(form);
  const set = (key) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((f) => ({ ...f, [key]: value }));
    setFormError(null);
  };
  const blur = (key) => () => setTouched((s) => ({ ...s, [key]: true }));
  const errorFor = (key) => ((touched[key] || submitted) && errors[key] ? t(errors[key]) : null);

  const strength = passwordStrength(form.password);
  const strengthLabels = t("signup.strengthLevels");

  const onSubmit = async (event) => {
    event.preventDefault();
    setSubmitted(true);
    setFormError(null);
    if (Object.keys(errors).length) {
      // Move focus to the first problem rather than leaving the reader to
      // hunt for it -- especially on a phone, where the error may be off
      // screen entirely.
      const first = ["name", "email", "registration", "password", "confirm", "accepted"].find(
        (key) => errors[key],
      );
      document.getElementById(`su-${first}`)?.focus();
      return;
    }

    setBusy(true);
    try {
      await signUp(form);
    } catch (err) {
      setFormError(err.i18nKey ? t(err.i18nKey) : err.message);
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth__form-side">
        <div className="auth__inner auth__inner--wide">
          <div className="auth__brand">
            <span className="brand__mark">
              <Icon name="logo" size={21} strokeWidth={1.7} />
            </span>
            <div>
              <div className="brand__name" style={{ fontSize: "1rem" }}>
                BioMark<em>HER2</em>
              </div>
              <div className="brand__sub">{t("common.tagline")}</div>
            </div>
            <span style={{ marginLeft: "auto" }}>
              <LangToggle />
            </span>
          </div>

          <h1>{t("signup.title")}</h1>
          <p className="auth__lede">{t("signup.lede")}</p>

          <form onSubmit={onSubmit} noValidate>
            <Field id="su-name" label={t("signup.name")} error={errorFor("name")}>
              <input
                id="su-name"
                className="input"
                type="text"
                autoComplete="name"
                placeholder={t("signup.namePlaceholder")}
                value={form.name}
                onChange={set("name")}
                onBlur={blur("name")}
                aria-invalid={Boolean(errorFor("name"))}
              />
            </Field>

            <Field id="su-email" label={t("signup.email")} error={errorFor("email")}>
              <input
                id="su-email"
                className="input"
                type="email"
                autoComplete="username"
                placeholder={t("login.emailPlaceholder")}
                value={form.email}
                onChange={set("email")}
                onBlur={blur("email")}
                aria-invalid={Boolean(errorFor("email"))}
              />
            </Field>

            <div className="auth__pair">
              <Field
                id="su-registration"
                label={t("signup.registration")}
                error={errorFor("registration")}
              >
                <input
                  id="su-registration"
                  className="input"
                  type="text"
                  autoComplete="off"
                  placeholder={t("signup.registrationPlaceholder")}
                  value={form.registration}
                  onChange={set("registration")}
                  onBlur={blur("registration")}
                  aria-invalid={Boolean(errorFor("registration"))}
                />
              </Field>

              <Field id="su-role" label={t("signup.role")}>
                <select
                  id="su-role"
                  className="select"
                  value={form.roleKey}
                  onChange={set("roleKey")}
                >
                  {ROLE_KEYS.map((key) => (
                    <option key={key} value={key}>
                      {t(key)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <Field id="su-password" label={t("signup.password")} error={errorFor("password")}>
              <div className="auth__pw-wrap">
                <input
                  id="su-password"
                  className="input"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  placeholder={t("signup.passwordPlaceholder")}
                  value={form.password}
                  onChange={set("password")}
                  onBlur={blur("password")}
                  aria-invalid={Boolean(errorFor("password"))}
                />
                <button
                  type="button"
                  className="auth__pw-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={t(showPassword ? "login.hidePassword" : "login.showPassword")}
                >
                  <Icon name={showPassword ? "eyeOff" : "eye"} size={17} />
                </button>
              </div>
              {form.password ? (
                <div className="strength" aria-live="polite">
                  <div className="strength__bars">
                    {[0, 1, 2, 3].map((i) => (
                      <span
                        key={i}
                        className="strength__bar"
                        style={{
                          background: i < strength ? STRENGTH_COLORS[strength] : "var(--line)",
                        }}
                      />
                    ))}
                  </div>
                  <span className="strength__label" style={{ color: STRENGTH_COLORS[strength] }}>
                    {t("signup.strength")}: {strengthLabels[strength]}
                  </span>
                </div>
              ) : null}
            </Field>

            <Field id="su-confirm" label={t("signup.confirm")} error={errorFor("confirm")}>
              <input
                id="su-confirm"
                className="input"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                placeholder="••••••••"
                value={form.confirm}
                onChange={set("confirm")}
                onBlur={blur("confirm")}
                aria-invalid={Boolean(errorFor("confirm"))}
              />
            </Field>

            <label className="check" style={{ alignItems: "flex-start" }}>
              <input
                id="su-accepted"
                type="checkbox"
                checked={form.accepted}
                onChange={set("accepted")}
                onBlur={blur("accepted")}
                style={{ marginTop: 2 }}
              />
              <span>
                {t("signup.terms")}
                {errorFor("accepted") ? (
                  <span className="field__error" style={{ display: "block", marginTop: 4 }}>
                    {errorFor("accepted")}
                  </span>
                ) : null}
              </span>
            </label>

            {/* Placed before the button on purpose -- see the note at the top
                of this file. */}
            <div className="note note--warn">
              <span className="note__icon">
                <Icon name="info" size={16} />
              </span>
              <span>
                <strong>{t("signup.noticeLead")}</strong> {t("signup.noticeBody")}
              </span>
            </div>

            {formError ? (
              <div className="note note--danger" role="alert">
                <span className="note__icon">
                  <Icon name="alert" size={16} />
                </span>
                <span>{formError}</span>
              </div>
            ) : null}

            <button
              type="submit"
              className="btn btn--primary btn--lg btn--block"
              disabled={busy}
              {...(busy ? { "data-busy": "" } : {})}
            >
              {t("signup.submit")}
              <Icon name="arrowRight" size={16} />
            </button>
          </form>

          <p className="auth__switch">
            {t("signup.haveAccount")} <Link to="/login">{t("signup.signIn")}</Link>
          </p>
        </div>
      </section>

      <section className="auth__poster" aria-hidden="true">
        <span className="auth__orb auth__orb--a" />
        <span className="auth__orb auth__orb--b" />
        <span className="auth__orb auth__orb--c" />

        <span className="auth__chip">
          <Icon name="shield" size={13} /> {t("signup.posterChip")}
        </span>
        <h2>{t("signup.posterTitle")}</h2>
        <p>{t("signup.posterBody")}</p>
      </section>
    </div>
  );
}

function Field({ id, label, error, children }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? (
        <span className="field__error" role="alert">
          <Icon name="alert" size={13} />
          {error}
        </span>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------ request access --- */

function RequestAccess() {
  const { user, config, requestAccess } = useAuth();
  const t = useT();
  const min = config?.password_min_length ?? 10;
  const [form, setForm] = useState({
    name: "", email: "", registration: "", title: "", password: "", confirm: "", note: "", accepted: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);

  if (user) return <Navigate to="/overview" replace />;

  const set = (key) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((f) => ({ ...f, [key]: value }));
    setError(null);
  };
  const mismatch = form.confirm && form.confirm !== form.password;
  const ready =
    form.name.trim().length >= 2 && form.email.includes("@") && form.password.length >= min &&
    form.password === form.confirm && form.accepted;

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await requestAccess({
        name: form.name, email: form.email, password: form.password,
        registration: form.registration, title: form.title, note: form.note,
      });
      setSent(true);
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  const poster = { chip: t("signup.posterChip"), chipIcon: "shield", title: t("signup.posterTitle"), body: t("signup.posterBody") };

  if (!config?.allow_access_requests) {
    return (
      <AuthLayout poster={poster} siteName={config?.site_name}>
        <h1>{t("request.closedTitle")}</h1>
        <p className="auth__lede">{t("request.closedBody")}</p>
        <Link className="btn btn--primary btn--lg btn--block" to="/login">
          {t("signup.backToSignIn")} <Icon name="arrowRight" size={16} />
        </Link>
      </AuthLayout>
    );
  }

  if (sent) {
    return (
      <AuthLayout poster={poster} siteName={config?.site_name}>
        <span className="auth__done" aria-hidden="true">
          <Icon name="checkCircle" size={30} />
        </span>
        <h1>{t("request.sentTitle")}</h1>
        <p className="auth__lede">{t("request.sentBody")}</p>
        <Link className="btn btn--primary btn--lg btn--block" to="/login">
          {t("signup.backToSignIn")} <Icon name="arrowRight" size={16} />
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout wide poster={poster} siteName={config?.site_name}>
      <h1>{t("request.title")}</h1>
      <p className="auth__lede">{t("request.lede")}</p>

      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="ra-name">{t("signup.name")}</label>
          <input id="ra-name" className="input" autoComplete="name" placeholder={t("signup.namePlaceholder")}
            value={form.name} onChange={set("name")} autoFocus />
        </div>
        <div className="field">
          <label htmlFor="ra-email">{t("signup.email")}</label>
          <input id="ra-email" className="input" type="email" autoComplete="username"
            placeholder={t("login.emailPlaceholder")} value={form.email} onChange={set("email")} />
        </div>
        <div className="auth__pair">
          <div className="field">
            <label htmlFor="ra-reg">{t("signup.registration")}</label>
            <input id="ra-reg" className="input" autoComplete="off" placeholder={t("signup.registrationPlaceholder")}
              value={form.registration} onChange={set("registration")} />
          </div>
          <div className="field">
            <label htmlFor="ra-title">{t("request.jobTitle")}</label>
            <input id="ra-title" className="input" placeholder={t("request.jobTitlePlaceholder")}
              value={form.title} onChange={set("title")} />
          </div>
        </div>
        <PasswordField id="ra-password" label={t("signup.password")} value={form.password}
          onChange={(v) => { setForm((f) => ({ ...f, password: v })); setError(null); }} minLength={min} />
        <div className="field">
          <label htmlFor="ra-confirm">{t("password.confirm")}</label>
          <input id="ra-confirm" className="input" type="password" autoComplete="new-password"
            value={form.confirm} onChange={set("confirm")} aria-invalid={Boolean(mismatch)} />
          {mismatch ? (
            <span className="field__error"><Icon name="alert" size={13} />{t("password.mismatch")}</span>
          ) : null}
        </div>
        <div className="field">
          <label htmlFor="ra-note">{t("request.note")}</label>
          <textarea id="ra-note" className="input textarea" rows={2} maxLength={500}
            placeholder={t("request.notePlaceholder")} value={form.note} onChange={set("note")} />
        </div>
        <label className="check" style={{ alignItems: "flex-start" }}>
          <input type="checkbox" checked={form.accepted} onChange={set("accepted")} style={{ marginTop: 2 }} />
          <span>{t("signup.terms")}</span>
        </label>

        {error ? <FormNote>{error}</FormNote> : null}

        <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={busy || !ready}
          {...(busy ? { "data-busy": "" } : {})}>
          {t("request.submit")} <Icon name="arrowRight" size={16} />
        </button>
      </form>

      <p className="auth__switch">
        {t("signup.haveAccount")} <Link to="/login">{t("signup.signIn")}</Link>
      </p>
    </AuthLayout>
  );
}
