/* First-run setup: creating the first administrator.

   Reachable only through the one-time link the server prints in its console
   when it starts with no administrator, so creating the account that
   controls everything else needs access to that console -- not merely a
   network path to the server. The token is taken out of the address bar as
   soon as the page has read it, so it does not sit in the browser history. */

import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import AuthLayout, { FormNote } from "../components/AuthLayout.jsx";
import PasswordField from "../components/PasswordField.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { errorText } from "../lib/auth.js";

export default function Setup() {
  const { ready, isServer, config, user, completeSetup } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [token] = useState(() => params.get("token") || "");
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const min = config?.password_min_length ?? 10;

  useEffect(() => {
    if (params.get("token")) setParams({}, { replace: true });
  }, [params, setParams]);

  if (!ready) return <div style={{ minHeight: "100dvh", background: "var(--bg)" }} />;
  if (!isServer) return <Navigate to="/login" replace />;
  if (user) return <Navigate to="/overview" replace />;

  const poster = {
    chip: t("setup.posterChip"),
    chipIcon: "shield",
    title: t("setup.posterTitle"),
    body: t("setup.posterBody"),
  };

  if (!config?.setup_required) {
    return (
      <AuthLayout poster={poster} siteName={config?.site_name}>
        <h1>{t("setup.doneTitle")}</h1>
        <p className="auth__lede">{t("setup.doneBody")}</p>
        <Link className="btn btn--primary btn--lg btn--block" to="/login">
          {t("setup.goSignIn")} <Icon name="arrowRight" size={16} />
        </Link>
      </AuthLayout>
    );
  }

  if (!token) {
    return (
      <AuthLayout poster={poster} siteName={config?.site_name}>
        <div className="eyebrow">{t("setup.eyebrow")}</div>
        <h1>{t("setup.noTokenTitle")}</h1>
        <p className="auth__lede">{t("setup.noToken")}</p>
        <p className="hint">{t("setup.cli")}</p>
        <pre className="code-line">biomark-admin create-admin --email you@hospital.org --name "Your Name"</pre>
      </AuthLayout>
    );
  }

  const set = (key) => (value) => {
    setForm((f) => ({ ...f, [key]: value }));
    setError(null);
  };
  const mismatch = form.confirm && form.confirm !== form.password;
  const valid =
    form.name.trim().length >= 2 && form.email.includes("@") && form.password.length >= min && !mismatch && form.confirm;

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await completeSetup({ token, name: form.name, email: form.email, password: form.password });
      navigate("/admin/users", { replace: true });
    } catch (err) {
      setError(errorText(err, t));
      setBusy(false);
    }
  };

  return (
    <AuthLayout poster={poster} siteName={config?.site_name}>
      <div className="eyebrow">{t("setup.eyebrow")}</div>
      <h1>{t("setup.title")}</h1>
      <p className="auth__lede">{t("setup.lede")}</p>

      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="su-name">{t("setup.name")}</label>
          <input id="su-name" className="input" autoComplete="name" value={form.name}
            onChange={(e) => set("name")(e.target.value)} placeholder={t("signup.namePlaceholder")} autoFocus />
        </div>
        <div className="field">
          <label htmlFor="su-email">{t("setup.email")}</label>
          <input id="su-email" className="input" type="email" autoComplete="username" value={form.email}
            onChange={(e) => set("email")(e.target.value)} placeholder={t("login.emailPlaceholder")} />
        </div>
        <PasswordField id="su-password" label={t("setup.password")} value={form.password}
          onChange={set("password")} minLength={min} />
        <div className="field">
          <label htmlFor="su-confirm">{t("password.confirm")}</label>
          <input id="su-confirm" className="input" type="password" autoComplete="new-password"
            value={form.confirm} onChange={(e) => set("confirm")(e.target.value)} aria-invalid={Boolean(mismatch)} />
          {mismatch ? (
            <span className="field__error"><Icon name="alert" size={13} />{t("password.mismatch")}</span>
          ) : null}
        </div>

        {error ? <FormNote>{error}</FormNote> : null}

        <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={busy || !valid}
          {...(busy ? { "data-busy": "" } : {})}>
          {t("setup.submit")} <Icon name="arrowRight" size={16} />
        </button>
      </form>
    </AuthLayout>
  );
}
