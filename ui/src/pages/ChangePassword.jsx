/* Shown instead of the portal to someone signed in with a temporary
   password an administrator set. The server refuses every other route until
   the password is changed, so this is the only screen that can work -- and
   it says why, rather than letting each page fail. */

import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import AuthLayout, { FormNote } from "../components/AuthLayout.jsx";
import PasswordField from "../components/PasswordField.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useToast } from "../state/ToastContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { errorText } from "../lib/auth.js";

export default function ChangePassword() {
  const { ready, user, config, changePassword, signOut } = useAuth();
  const t = useT();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const min = config?.password_min_length ?? 10;

  if (!ready) return <div style={{ minHeight: "100dvh", background: "var(--bg)" }} />;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.must_change_password) return <Navigate to={location.state?.from ?? "/overview"} replace />;

  const mismatch = confirm && confirm !== next;
  const valid = current && next.length >= min && confirm && !mismatch;

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await changePassword({ current, next });
      toast.ok(t("changePw.done"), t("account.passwordRules"));
      navigate(location.state?.from ?? "/overview", { replace: true });
    } catch (err) {
      setError(errorText(err, t));
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      siteName={config?.site_name}
      poster={{ chip: t("setup.posterChip"), chipIcon: "lock", title: t("setup.posterTitle"), body: t("setup.posterBody") }}
    >
      <div className="eyebrow">{t("changePw.eyebrow")}</div>
      <h1>{t("changePw.title")}</h1>
      <p className="auth__lede">{t("changePw.lede")}</p>

      <form onSubmit={onSubmit} noValidate>
        <input type="email" autoComplete="username" value={user.email} readOnly hidden />
        <PasswordField id="cp-current" label={t("changePw.current")} value={current} onChange={setCurrent}
          autoComplete="current-password" meter={false} autoFocus />
        <PasswordField id="cp-next" label={t("changePw.next")} value={next}
          onChange={(v) => { setNext(v); setError(null); }} minLength={min} />
        <div className="field">
          <label htmlFor="cp-confirm">{t("password.confirm")}</label>
          <input id="cp-confirm" className="input" type="password" autoComplete="new-password"
            value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={Boolean(mismatch)} />
          {mismatch ? (
            <span className="field__error"><Icon name="alert" size={13} />{t("password.mismatch")}</span>
          ) : null}
        </div>

        {error ? <FormNote>{error}</FormNote> : null}

        <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={busy || !valid}
          {...(busy ? { "data-busy": "" } : {})}>
          {t("changePw.submit")} <Icon name="arrowRight" size={16} />
        </button>
        <button type="button" className="btn btn--ghost btn--block" onClick={signOut}>
          <Icon name="logout" size={16} /> {t("changePw.signOut")}
        </button>
      </form>
    </AuthLayout>
  );
}
