import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { DEMO_ACCOUNT, useAuth } from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import LangToggle from "../components/LangToggle.jsx";

export default function Login() {
  const { user, signIn } = useAuth();
  const location = useLocation();
  const t = useT();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (user) return <Navigate to={location.state?.from ?? "/overview"} replace />;

  const fillDemo = () => {
    setEmail(DEMO_ACCOUNT.email);
    setPassword(DEMO_ACCOUNT.password);
    setError(null);
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn({ email, password, remember });
    } catch (err) {
      setError(err.i18nKey ? t(err.i18nKey) : err.message);
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth__form-side">
        <div className="auth__inner">
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
            {/* Language has to be switchable before sign-in, not only after:
                someone who reads Malayalam needs it on the first screen. */}
            <span style={{ marginLeft: "auto" }}>
              <LangToggle />
            </span>
          </div>

          <h1>{t("login.title")}</h1>
          <p className="auth__lede">
            {t("login.lede")}
          </p>

          <form onSubmit={onSubmit} noValidate>
            <div className="field">
              <label htmlFor="email">{t("login.email")}</label>
              <div style={{ position: "relative" }}>
                <input
                  id="email"
                  className="input"
                  type="email"
                  autoComplete="username"
                  placeholder={t("login.emailPlaceholder")}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                />
              </div>
            </div>

            <div className="field">
              <label htmlFor="password">{t("login.password")}</label>
              <div className="auth__pw-wrap">
                <input
                  id="password"
                  className="input"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
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
            </div>

            {error ? (
              <div className="note note--danger" role="alert">
                <span className="note__icon">
                  <Icon name="alert" size={16} />
                </span>
                <span>{error}</span>
              </div>
            ) : null}

            <div className="auth__row">
              <label className="check">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                {t("login.remember")}
              </label>
              <Link to="/signup">{t("login.needAccess")}</Link>
            </div>

            <button
              type="submit"
              className="btn btn--primary btn--lg btn--block"
              disabled={busy}
              {...(busy ? { "data-busy": "" } : {})}
            >
              {t("login.submit")}
              <Icon name="arrowRight" size={16} />
            </button>
          </form>

          {/* The demo account is printed here on purpose: it is a project
              build with no user table, and hiding a credential that ships in
              the bundle would only make it look more real than it is. */}
          <div className="demo-card">
            <dl>
              <div>
                <dt>{t("login.demoAccount")}</dt>
                <dd>{DEMO_ACCOUNT.email}</dd>
                <dd>{DEMO_ACCOUNT.password}</dd>
              </div>
            </dl>
            <button type="button" className="btn btn--soft btn--sm" onClick={fillDemo}>
              {t("login.fill")}
            </button>
          </div>

          <p className="auth__switch">
            {t("login.noAccount")} <Link to="/signup">{t("login.createAccount")}</Link>
          </p>

          <p className="hint" style={{ marginTop: 16 }}>
            {t("login.disclaimer")}
          </p>
        </div>
      </section>

      <section className="auth__poster" aria-hidden="true">
        <span className="auth__orb auth__orb--a" />
        <span className="auth__orb auth__orb--b" />
        <span className="auth__orb auth__orb--c" />

        <span className="auth__chip">
          <Icon name="sparkles" size={13} /> {t("login.posterChip")}
        </span>
        <h2>{t("login.posterTitle")}</h2>
        <p>
          {t("login.posterBody")}
        </p>

        <div className="auth__stats">
          <div>
            <strong>4</strong>
            <span>{t("login.statClasses")}</span>
          </div>
          <div>
            <strong>&lt;2s</strong>
            <span>{t("login.statSpeed")}</span>
          </div>
          <div>
            <strong>100%</strong>
            <span>{t("login.statReviewed")}</span>
          </div>
        </div>
      </section>
    </div>
  );
}
