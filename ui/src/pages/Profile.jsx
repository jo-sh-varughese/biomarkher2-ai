/* ============================================================================
   Profile.

   This page edits the two fields that end up inside a signed clinical
   record -- the reviewer's name and registration number -- so it leads with
   that fact rather than treating them as ordinary account settings.

   It is also honest about which parts of the account it can actually change.
   The demo account has no user record behind it, so its edits live in the
   session and end at sign-out, and its password is fixed in the bundle. Both
   are stated on the page instead of being discovered by a save that silently
   does nothing.
   ==========================================================================*/

import { useEffect, useMemo, useRef, useState } from "react";
import Icon from "../components/Icon.jsx";
import {
  AVATAR_COLORS,
  ROLE_KEYS,
  avatarStyle,
  passwordStrength,
  useAuth,
} from "../state/AuthContext.jsx";
import { useTheme } from "../state/ThemeContext.jsx";
import { useI18n } from "../i18n/I18nContext.jsx";
import { useToast } from "../state/ToastContext.jsx";
import { LANGS } from "../i18n/I18nContext.jsx";
import { dateTime, initials } from "../lib/format.js";

const STRENGTH_COLORS = [
  "var(--line-strong)",
  "var(--danger)",
  "var(--warn)",
  "var(--accent)",
  "var(--ok)",
];

export default function Profile() {
  const { user, updateProfile, changePassword, signOut } = useAuth();
  const { theme, setTheme } = useTheme();
  const { t, lang, setLang, locale } = useI18n();
  const toast = useToast();

  const [form, setForm] = useState({
    name: user.name ?? "",
    registration: user.registration ?? "",
    roleKey: user.roleKey ?? ROLE_KEYS[0],
    accent: user.accent ?? AVATAR_COLORS[0].id,
  });
  const [saving, setSaving] = useState(false);

  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwBusy, setPwBusy] = useState(false);
  const [pwError, setPwError] = useState(null);
  const securityRef = useRef(null);

  // Deep-link from the account menu's "Preferences" item.
  useEffect(() => {
    if (window.location.hash === "#security") {
      securityRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  const dirty = useMemo(
    () =>
      form.name.trim() !== (user.name ?? "") ||
      form.registration.trim() !== (user.registration ?? "") ||
      form.roleKey !== (user.roleKey ?? ROLE_KEYS[0]) ||
      form.accent !== (user.accent ?? AVATAR_COLORS[0].id),
    [form, user],
  );

  const nameOk = form.name.trim().length >= 3;
  const regOk = form.registration.trim().length >= 4;

  const onSave = async (event) => {
    event.preventDefault();
    if (!dirty) {
      toast.info(t("profile.noChanges"), t("profile.noChangesBody"));
      return;
    }
    if (!nameOk || !regOk) return;
    setSaving(true);
    try {
      await updateProfile({
        name: form.name.trim(),
        registration: form.registration.trim().toUpperCase(),
        roleKey: form.roleKey,
        accent: form.accent,
      });
      toast.ok(t("profile.saved"), t("profile.savedBody"));
    } catch (err) {
      toast.error(t("toast.recordFailed"), err.i18nKey ? t(err.i18nKey) : err.message);
    } finally {
      setSaving(false);
    }
  };

  const pwStrength = passwordStrength(pw.next);
  const pwValid =
    pw.current.length > 0 &&
    pw.next.length >= 8 &&
    /[a-zA-Z]/.test(pw.next) &&
    /\d/.test(pw.next) &&
    pw.next === pw.confirm;

  const onChangePassword = async (event) => {
    event.preventDefault();
    setPwError(null);
    if (!pwValid) return;
    setPwBusy(true);
    try {
      await changePassword({ current: pw.current, next: pw.next });
      setPw({ current: "", next: "", confirm: "" });
      toast.ok(t("profile.passwordChanged"), t("profile.passwordChangedBody"));
    } catch (err) {
      setPwError(err.i18nKey ? t(err.i18nKey) : err.message);
    } finally {
      setPwBusy(false);
    }
  };

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("profile.eyebrow")}</div>
          <h1>{t("profile.title")}</h1>
          <p className="lede">{t("profile.lede")}</p>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          {/* --------------------------------------------------- identity --- */}
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("profile.identity")}</h2>
                <p className="sub">{t("profile.identitySub")}</p>
              </div>
            </div>

            <div className="note note--info" style={{ marginBottom: 20 }}>
              <span className="note__icon">
                <Icon name="info" size={16} />
              </span>
              <span>{t(user.demo ? "profile.demoNotice" : "profile.localNotice")}</span>
            </div>

            <form onSubmit={onSave} style={{ display: "grid", gap: 16 }}>
              <div className="profile-id">
                <span className="avatar avatar--xl" style={avatarStyle(form.accent)}>
                  {initials(form.name || user.name)}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="field-label">{t("profile.avatar")}</div>
                  <p className="hint" style={{ marginBottom: 9 }}>
                    {t("profile.avatarSub")}
                  </p>
                  <div className="swatches" role="radiogroup" aria-label={t("profile.avatar")}>
                    {AVATAR_COLORS.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        role="radio"
                        aria-checked={form.accent === c.id}
                        aria-label={c.id}
                        className={`swatch-dot${form.accent === c.id ? " is-on" : ""}`}
                        style={avatarStyle(c.id)}
                        onClick={() => setForm((f) => ({ ...f, accent: c.id }))}
                      />
                    ))}
                  </div>
                </div>
              </div>

              <hr className="divider" />

              <div className="field">
                <label htmlFor="pf-name">{t("profile.name")}</label>
                <input
                  id="pf-name"
                  className="input"
                  type="text"
                  autoComplete="name"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  aria-invalid={!nameOk}
                />
                {!nameOk ? (
                  <span className="field__error">
                    <Icon name="alert" size={13} />
                    {t("signup.errName")}
                  </span>
                ) : null}
              </div>

              <div className="field">
                <label htmlFor="pf-email">{t("profile.email")}</label>
                <input id="pf-email" className="input" type="email" value={user.email} disabled />
                <p className="hint">{t("profile.emailFixed")}</p>
              </div>

              <div className="auth__pair">
                <div className="field">
                  <label htmlFor="pf-reg">{t("profile.registration")}</label>
                  <input
                    id="pf-reg"
                    className="input"
                    type="text"
                    value={form.registration}
                    /* Upper-cased as it is typed, not on save: doing it only
                       on save meant the field kept showing what you typed
                       while the stored value differed, which left the form
                       looking unsaved immediately after saving. */
                    onChange={(e) =>
                      setForm((f) => ({ ...f, registration: e.target.value.toUpperCase() }))
                    }
                    aria-invalid={!regOk}
                  />
                  {!regOk ? (
                    <span className="field__error">
                      <Icon name="alert" size={13} />
                      {t("signup.errRegistration")}
                    </span>
                  ) : null}
                </div>

                <div className="field">
                  <label htmlFor="pf-role">{t("profile.role")}</label>
                  <select
                    id="pf-role"
                    className="select"
                    value={form.roleKey}
                    onChange={(e) => setForm((f) => ({ ...f, roleKey: e.target.value }))}
                  >
                    {ROLE_KEYS.map((key) => (
                      <option key={key} value={key}>
                        {t(key)}
                      </option>
                    ))}
                    {/* The demo account's role key is not in the sign-up list;
                        keep it selectable so opening this page cannot silently
                        change the reviewer's job title. */}
                    {ROLE_KEYS.includes(user.roleKey) ? null : (
                      <option value={user.roleKey}>{t(user.roleKey)}</option>
                    )}
                  </select>
                </div>
              </div>

              <div>
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={saving || !dirty || !nameOk || !regOk}
                  {...(saving ? { "data-busy": "" } : {})}
                >
                  <Icon name="check" size={16} /> {t("profile.save")}
                </button>
              </div>
            </form>
          </section>

          {/* --------------------------------------------------- security --- */}
          <section className="card card--pad rise" id="security" ref={securityRef}>
            <div className="card-head">
              <div>
                <h2>{t("profile.security")}</h2>
                <p className="sub">{t("profile.securitySub")}</p>
              </div>
              <Icon name="lock" size={17} />
            </div>

            {user.demo ? (
              <div className="note note--warn">
                <span className="note__icon">
                  <Icon name="alert" size={16} />
                </span>
                <span>{t("profile.demoNoPassword")}</span>
              </div>
            ) : (
              <form onSubmit={onChangePassword} style={{ display: "grid", gap: 16 }}>
                <div className="field">
                  <label htmlFor="pf-cur">{t("profile.current")}</label>
                  <input
                    id="pf-cur"
                    className="input"
                    type="password"
                    autoComplete="current-password"
                    value={pw.current}
                    onChange={(e) => setPw((s) => ({ ...s, current: e.target.value }))}
                  />
                </div>

                <div className="auth__pair">
                  <div className="field">
                    <label htmlFor="pf-new">{t("profile.next")}</label>
                    <input
                      id="pf-new"
                      className="input"
                      type="password"
                      autoComplete="new-password"
                      value={pw.next}
                      onChange={(e) => setPw((s) => ({ ...s, next: e.target.value }))}
                    />
                    {pw.next ? (
                      <div className="strength" aria-live="polite">
                        <div className="strength__bars">
                          {[0, 1, 2, 3].map((i) => (
                            <span
                              key={i}
                              className="strength__bar"
                              style={{
                                background:
                                  i < pwStrength ? STRENGTH_COLORS[pwStrength] : "var(--line)",
                              }}
                            />
                          ))}
                        </div>
                        <span
                          className="strength__label"
                          style={{ color: STRENGTH_COLORS[pwStrength] }}
                        >
                          {t("signup.strengthLevels")[pwStrength]}
                        </span>
                      </div>
                    ) : null}
                  </div>

                  <div className="field">
                    <label htmlFor="pf-conf">{t("profile.confirm")}</label>
                    <input
                      id="pf-conf"
                      className="input"
                      type="password"
                      autoComplete="new-password"
                      value={pw.confirm}
                      onChange={(e) => setPw((s) => ({ ...s, confirm: e.target.value }))}
                      aria-invalid={Boolean(pw.confirm) && pw.confirm !== pw.next}
                    />
                    {pw.confirm && pw.confirm !== pw.next ? (
                      <span className="field__error">
                        <Icon name="alert" size={13} />
                        {t("signup.errConfirm")}
                      </span>
                    ) : null}
                  </div>
                </div>

                {pwError ? (
                  <div className="note note--danger" role="alert">
                    <span className="note__icon">
                      <Icon name="alert" size={16} />
                    </span>
                    <span>{pwError}</span>
                  </div>
                ) : null}

                <div>
                  <button
                    type="submit"
                    className="btn btn--primary"
                    disabled={pwBusy || !pwValid}
                    {...(pwBusy ? { "data-busy": "" } : {})}
                  >
                    <Icon name="lock" size={16} /> {t("profile.changePassword")}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>

        {/* ------------------------------------------------------- rail --- */}
        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("profile.prefs")}</h2>
                <p className="sub">{t("profile.prefsSub")}</p>
              </div>
            </div>

            <div className="field" style={{ marginBottom: 18 }}>
              <span className="field-label">{t("profile.language")}</span>
              <p className="hint" style={{ marginBottom: 8 }}>
                {t("profile.languageSub")}
              </p>
              <div className="seg" role="radiogroup" aria-label={t("profile.language")}>
                {LANGS.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    role="radio"
                    lang={entry.id}
                    aria-checked={lang === entry.id}
                    className={`seg__btn${lang === entry.id ? " is-on" : ""}`}
                    onClick={() => setLang(entry.id)}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="field">
              <span className="field-label">{t("profile.theme")}</span>
              <p className="hint" style={{ marginBottom: 8 }}>
                {t("profile.themeSub")}
              </p>
              <div className="seg" role="radiogroup" aria-label={t("profile.theme")}>
                {[
                  ["light", "sun", "profile.themeLight"],
                  ["dark", "moon", "profile.themeDark"],
                ].map(([id, icon, key]) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={theme === id}
                    className={`seg__btn${theme === id ? " is-on" : ""}`}
                    onClick={() => setTheme(id)}
                  >
                    <Icon name={icon} size={15} />
                    {t(key)}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("profile.account")}</h2>
                <p className="sub">{t("profile.accountSub")}</p>
              </div>
            </div>

            <dl className="spec-list" style={{ fontSize: "0.8125rem" }}>
              <div>
                <dt>{t("profile.type")}</dt>
                <dd>
                  <span className={`badge ${user.demo ? "badge--warn" : "badge--accent"}`}>
                    {t(user.demo ? "profile.typeDemo" : "profile.typeLocal")}
                  </span>
                </dd>
              </div>
              <div>
                <dt>{t("profile.email")}</dt>
                <dd className="mono">{user.email}</dd>
              </div>
              <div>
                <dt>{t("profile.created")}</dt>
                <dd>{user.signedInAt ? dateTime(user.signedInAt, locale) : "—"}</dd>
              </div>
            </dl>

            <button
              type="button"
              className="btn btn--danger btn--block"
              style={{ marginTop: 18 }}
              onClick={signOut}
            >
              <Icon name="logout" size={16} /> {t("profile.signOut")}
            </button>
          </section>
        </div>
      </div>

      <p className="footer-note">{t("common.notMedicalDevice")}</p>
    </>
  );
}
