/* Setting a password from a one-time link: an invitation to a new account,
   or a reset an administrator made. The link's token is read once and taken
   out of the address bar, checked with the server before the form is shown
   (so an expired link says so up front, not after the person has typed a
   new password twice), and spent on submit, which also signs them in. */

import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import AuthLayout, { FormNote } from "../components/AuthLayout.jsx";
import PasswordField from "../components/PasswordField.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { errorText, inspectLink } from "../lib/auth.js";

export default function ResetPassword() {
  const { ready, isServer, config, acceptLink } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [token] = useState(() => params.get("token") || "");
  const [link, setLink] = useState(null);
  const [linkError, setLinkError] = useState(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const min = config?.password_min_length ?? 10;

  useEffect(() => {
    if (params.get("token")) setParams({}, { replace: true });
  }, [params, setParams]);

  useEffect(() => {
    if (!ready || !isServer || !token) return;
    inspectLink(token)
      .then(setLink)
      .catch((err) => setLinkError(errorText(err, t)));
  }, [ready, isServer, token, t]);

  if (!ready) return <div style={{ minHeight: "100dvh", background: "var(--bg)" }} />;
  if (!isServer) return <Navigate to="/login" replace />;

  const poster = {
    chip: t("setup.posterChip"),
    chipIcon: "lock",
    title: t("login.posterTitle"),
    body: t("setup.posterBody"),
  };

  if (!token || linkError) {
    return (
      <AuthLayout poster={poster} siteName={config?.site_name}>
        <h1>{t("reset.invalidTitle")}</h1>
        <p className="auth__lede">{linkError ?? t("reset.missing")}</p>
        <Link className="btn btn--primary btn--lg btn--block" to="/login">
          {t("setup.goSignIn")} <Icon name="arrowRight" size={16} />
        </Link>
      </AuthLayout>
    );
  }

  if (!link) {
    return (
      <AuthLayout poster={poster} siteName={config?.site_name}>
        <p className="auth__lede" aria-live="polite">{t("reset.checking")}</p>
      </AuthLayout>
    );
  }

  const mismatch = confirm && confirm !== password;
  const valid = password.length >= min && confirm && !mismatch;

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await acceptLink(token, password);
      navigate("/overview", { replace: true });
    } catch (err) {
      setError(errorText(err, t));
      setBusy(false);
    }
  };

  return (
    <AuthLayout poster={poster} siteName={config?.site_name}>
      <h1>{t(link.kind === "invite" ? "reset.inviteTitle" : "reset.resetTitle")}</h1>
      <p className="auth__lede">{t("reset.lede", { email: link.email })}</p>

      <form onSubmit={onSubmit} noValidate>
        {/* Lets a password manager file the new password under the right account. */}
        <input type="email" autoComplete="username" value={link.email} readOnly hidden />
        <PasswordField id="rp-password" label={t("changePw.next")} value={password}
          onChange={(v) => { setPassword(v); setError(null); }} minLength={min} autoFocus />
        <div className="field">
          <label htmlFor="rp-confirm">{t("password.confirm")}</label>
          <input id="rp-confirm" className="input" type="password" autoComplete="new-password"
            value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={Boolean(mismatch)} />
          {mismatch ? (
            <span className="field__error"><Icon name="alert" size={13} />{t("password.mismatch")}</span>
          ) : null}
        </div>

        {error ? <FormNote>{error}</FormNote> : null}

        <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={busy || !valid}
          {...(busy ? { "data-busy": "" } : {})}>
          {t("reset.submit")} <Icon name="arrowRight" size={16} />
        </button>
      </form>
    </AuthLayout>
  );
}
