import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import AuthLayout, { FormNote } from "../components/AuthLayout.jsx";
import { DEMO_ACCOUNT, useAuth } from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { errorText } from "../lib/auth.js";

export default function Login() {
  const { user, signIn, isServer, config, expired, clearExpired } = useAuth();
  const location = useLocation();
  const t = useT();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (user) {
    const target = user.must_change_password ? "/change-password" : location.state?.from ?? "/overview";
    return <Navigate to={target} replace />;
  }

  const setupRequired = isServer && config?.setup_required;
  const allowRemember = !isServer || config?.allow_remember_me;

  const fillDemo = () => {
    setEmail(DEMO_ACCOUNT.email);
    setPassword(DEMO_ACCOUNT.password);
    setError(null);
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    clearExpired();
    try {
      await signIn({ email, password, remember: remember && allowRemember });
    } catch (err) {
      setError(errorText(err, t));
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      siteName={config?.site_name}
      poster={{
        chip: t("login.posterChip"),
        title: t("login.posterTitle"),
        body: t("login.posterBody"),
        extra: (
          <div className="auth__stats">
            <div>
              <strong>4</strong>
              <span>{t("login.statClasses")}</span>
            </div>
            <div>
              {/* Measured, not aspirational: median of 48 full analyses of
                  1024x1024 fields on the development laptop's CPU (2026-09-24). */}
              <strong>≈7s</strong>
              <span>{t("login.statSpeed")}</span>
            </div>
            <div>
              <strong>100%</strong>
              <span>{t("login.statReviewed")}</span>
            </div>
          </div>
        ),
      }}
    >
      <h1>{t("login.title")}</h1>
      <p className="auth__lede">{t("login.lede")}</p>

      {expired ? (
        <FormNote tone="info" icon="clock">
          <strong>{t("auth.sessionEnded")}.</strong> {t("auth.sessionEndedBody")}
        </FormNote>
      ) : null}

      {setupRequired ? (
        <FormNote tone="warn" icon="key">
          <strong>{t("auth.setupNeededTitle")}.</strong> {t("auth.setupNeededBody")}
        </FormNote>
      ) : null}

      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="email">{t("login.email")}</label>
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

        {error ? <FormNote>{error}</FormNote> : null}

        <div className="auth__row">
          {allowRemember ? (
            <label className="check">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              {t("login.remember")}
            </label>
          ) : (
            <span />
          )}
          {isServer ? (
            config?.allow_access_requests ? <Link to="/signup">{t("auth.requestAccess")}</Link> : null
          ) : (
            <Link to="/signup">{t("login.needAccess")}</Link>
          )}
        </div>

        <button
          type="submit"
          className="btn btn--primary btn--lg btn--block"
          disabled={busy || setupRequired}
          {...(busy ? { "data-busy": "" } : {})}
        >
          {t("login.submit")}
          <Icon name="arrowRight" size={16} />
        </button>
      </form>

      {isServer ? (
        <>
          <p className="auth__switch">
            {t("auth.needAccessServer")}{" "}
            {config?.allow_access_requests ? (
              <Link to="/signup">{t("auth.requestAccess")}</Link>
            ) : (
              t("auth.askAdmin")
            )}
          </p>
          <p className="hint" style={{ marginTop: 8 }}>{t("auth.forgot")}</p>
          <p className="hint" style={{ marginTop: 16 }}>{t("auth.serverDisclaimer")}</p>
        </>
      ) : (
        <>
          {/* The demo account is printed here on purpose: with no server there
              is no user table, and hiding a credential that ships in the
              bundle would only make it look more real than it is. */}
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
        </>
      )}
    </AuthLayout>
  );
}
