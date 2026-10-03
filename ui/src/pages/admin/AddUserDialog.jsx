/* Adding a person: who they are, what they may do, and how they get in the
   first time -- a password the administrator sets (and hands over), or a
   one-time link that lets them choose their own. The result screen shows
   exactly what to pass on, ready to copy, once; the server never shows a
   password again after this. */

import { useEffect, useState } from "react";
import Dialog from "../../components/Dialog.jsx";
import Icon from "../../components/Icon.jsx";
import PasswordField from "../../components/PasswordField.jsx";
import CopyButton from "../../components/CopyButton.jsx";
import { FormNote } from "../../components/AuthLayout.jsx";
import { useAuth } from "../../state/AuthContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { dateTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import { useAdmin } from "./shared.jsx";

const EMPTY = {
  name: "",
  email: "",
  role: "pathologist",
  registration: "",
  title: "",
  access: "password",
  password: "",
  must_change_password: true,
};

export default function AddUserDialog({ open, onClose, onCreated }) {
  const { api } = useAdmin();
  const { config } = useAuth();
  const { t, locale } = useI18n();
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const min = config?.password_min_length ?? 10;

  useEffect(() => {
    if (open) {
      setForm(EMPTY);
      setError(null);
      setResult(null);
      setBusy(false);
    }
  }, [open]);

  const set = (key) => (value) => {
    setForm((f) => ({ ...f, [key]: value }));
    setError(null);
  };

  const valid =
    form.name.trim().length >= 2 &&
    /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(form.email.trim()) &&
    (form.access === "invite" || form.password.length >= min);

  const submit = async (event) => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const body = { ...form };
      if (body.access === "invite") delete body.password;
      const created = await api.createUser(body);
      setResult({ ...created, password: form.access === "password" ? form.password : null });
      onCreated?.(created.user);
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  const origin = window.location.origin;

  if (result) {
    const { user, link, password } = result;
    const url = link ? `${origin}${link.path}` : null;
    const details = link
      ? url
      : `${t("admin.form.portal")}: ${origin}/login\n${t("admin.form.email")}: ${user.email}\n${t("admin.form.password")}: ${password}`;
    return (
      <Dialog
        open={open}
        onClose={onClose}
        icon="userCheck"
        tone="ok"
        title={t("admin.form.createdTitle", { name: user.name })}
        subtitle={link ? t("admin.form.createdInvite", { when: dateTime(link.expires_at, locale) }) : t("admin.form.createdPassword")}
        footer={
          <>
            <button type="button" className="btn" onClick={() => { setForm(EMPTY); setResult(null); }}>
              <Icon name="userPlus" size={15} /> {t("admin.form.addAnother")}
            </button>
            <button type="button" className="btn btn--primary" onClick={onClose} data-autofocus="">
              {t("admin.form.done")}
            </button>
          </>
        }
      >
        <div className="handoff">
          {link ? (
            <div className="handoff__row handoff__row--link">
              <span className="handoff__label">{t("admin.drawer.linkTitle")}</span>
              <code className="handoff__value">{url}</code>
            </div>
          ) : (
            <>
              <div className="handoff__row">
                <span className="handoff__label">{t("admin.form.portal")}</span>
                <code className="handoff__value">{origin}/login</code>
              </div>
              <div className="handoff__row">
                <span className="handoff__label">{t("admin.form.email")}</span>
                <code className="handoff__value">{user.email}</code>
              </div>
              <div className="handoff__row">
                <span className="handoff__label">{t("admin.form.password")}</span>
                <code className="handoff__value">{password}</code>
              </div>
            </>
          )}
          <div className="handoff__copy">
            <CopyButton text={details} label={t("admin.form.copyDetails")} />
          </div>
        </div>
        {!link && user.must_change_password ? (
          <p className="hint hint-row" style={{ marginTop: 12 }}>
            <Icon name="key" size={13} /> {t("admin.drawer.mustChangeNote")}
          </p>
        ) : null}
      </Dialog>
    );
  }

  return (
    <Dialog
      open={open}
      onClose={busy ? () => {} : onClose}
      icon="userPlus"
      title={t("admin.form.addTitle")}
      subtitle={t("admin.form.addSub")}
      size="lg"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
          <button type="submit" form="add-user-form" className="btn btn--primary" disabled={busy || !valid}
            {...(busy ? { "data-busy": "" } : {})}>
            <Icon name="userPlus" size={15} /> {t("admin.form.create")}
          </button>
        </>
      }
    >
      <form id="add-user-form" className="form-grid" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="au-name">{t("admin.form.name")}</label>
          <input id="au-name" className="input" value={form.name} onChange={(e) => set("name")(e.target.value)}
            placeholder={t("signup.namePlaceholder")} autoComplete="off" data-autofocus="" />
        </div>
        <div className="field">
          <label htmlFor="au-email">{t("admin.form.email")}</label>
          <input id="au-email" className="input" type="email" value={form.email}
            onChange={(e) => set("email")(e.target.value)} placeholder={t("login.emailPlaceholder")} autoComplete="off" />
        </div>

        <fieldset className="field field--span">
          <legend className="field-label">{t("admin.form.role")}</legend>
          <div className="choice-grid">
            {["pathologist", "viewer", "admin"].map((role) => (
              <label key={role} className={`choice${form.role === role ? " is-on" : ""}`}>
                <input type="radio" name="au-role" value={role} checked={form.role === role}
                  onChange={() => set("role")(role)} />
                <span className="choice__title">{t(`roles.${role}`)}</span>
                <span className="choice__sub">{t(`roleHelp.${role}`)}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="au-reg">
            {t("admin.form.registration")} <span className="muted">· {t("admin.form.optional")}</span>
          </label>
          <input id="au-reg" className="input" value={form.registration}
            onChange={(e) => set("registration")(e.target.value.toUpperCase())} placeholder={t("signup.registrationPlaceholder")} />
        </div>
        <div className="field">
          <label htmlFor="au-title">
            {t("admin.form.title")} <span className="muted">· {t("admin.form.optional")}</span>
          </label>
          <input id="au-title" className="input" value={form.title} onChange={(e) => set("title")(e.target.value)}
            placeholder={t("account.jobTitlePlaceholder")} />
        </div>

        <fieldset className="field field--span">
          <legend className="field-label">{t("admin.form.access")}</legend>
          <div className="choice-grid choice-grid--two">
            {[
              ["password", "key", "admin.form.accessPassword", "admin.form.accessPasswordSub"],
              ["invite", "mail", "admin.form.accessInvite", "admin.form.accessInviteSub"],
            ].map(([value, icon, title, sub]) => (
              <label key={value} className={`choice${form.access === value ? " is-on" : ""}`}>
                <input type="radio" name="au-access" value={value} checked={form.access === value}
                  onChange={() => set("access")(value)} />
                <span className="choice__title"><Icon name={icon} size={14} /> {t(title)}</span>
                <span className="choice__sub">{t(sub)}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {form.access === "password" ? (
          <div className="field--span">
            <PasswordField id="au-password" label={t("admin.form.password")} value={form.password}
              onChange={set("password")} generator minLength={min} autoComplete="new-password" />
            <label className="check" style={{ marginTop: 10 }}>
              <input type="checkbox" checked={form.must_change_password}
                onChange={(e) => set("must_change_password")(e.target.checked)} />
              {t("admin.form.mustChange")}
            </label>
          </div>
        ) : null}

        {error ? (
          <div className="field--span">
            <FormNote>{error}</FormNote>
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}
