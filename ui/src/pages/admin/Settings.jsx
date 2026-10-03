/* Portal-wide settings. Edits collect in a draft and nothing is sent until
   "Save changes" -- a bar that appears only while there is something to
   save, and says so. The server validates every value (ranges, types) and
   records each change, with its old and new value, in the audit log. */

import { useEffect, useMemo, useState } from "react";
import Icon from "../../components/Icon.jsx";
import { FormNote } from "../../components/AuthLayout.jsx";
import { useAuth } from "../../state/AuthContext.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useT } from "../../i18n/I18nContext.jsx";
import { errorText } from "../../lib/auth.js";
import { LoadError, PageHead, SkeletonRows, useAdmin, useLoad } from "./shared.jsx";

export default function Settings() {
  const { api } = useAdmin();
  const { refresh, refreshConfig } = useAuth();
  const t = useT();
  const toast = useToast();
  const { data, error, reload, setData } = useLoad(() => api.settings(), [api]);
  const saved = data?.settings;
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    if (saved) setDraft(saved);
  }, [saved]);

  const changes = useMemo(() => {
    if (!saved || !draft) return {};
    return Object.fromEntries(Object.entries(draft).filter(([k, v]) => saved[k] !== v));
  }, [saved, draft]);
  const dirty = Object.keys(changes).length > 0;
  // A number box cleared or typed into garbage holds NaN; saving it would
  // only earn a round trip to be told so.
  const incomplete = draft
    ? Object.values(draft).some((v) => typeof v === "number" && !Number.isFinite(v)) || !draft.site_name?.trim()
    : false;

  const set = (key, value) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaveError(null);
  };

  const save = async () => {
    setBusy(true);
    setSaveError(null);
    try {
      const result = await api.updateSettings(changes);
      setData(result);
      toast.ok(t("admin.settings.saved"));
      // The announcement and the sign-in rules are read elsewhere too.
      refresh?.();
      refreshConfig?.().catch(() => {});
    } catch (err) {
      setSaveError(err);
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <PageHead eyebrow={t("admin.eyebrow")} title={t("admin.settings.title")} lede={t("admin.settings.lede")} />
  );

  if (error && !data) {
    return (
      <>
        {head}
        <section className="card card--pad"><LoadError error={error} onRetry={reload} t={t} /></section>
      </>
    );
  }
  if (!draft) {
    return (
      <>
        {head}
        <section className="card card--pad"><SkeletonRows rows={6} /></section>
      </>
    );
  }

  const units = (key) => t(`admin.settings.units.${key}`);
  const fieldError = saveError?.extra?.field;

  return (
    <>
      {head}

      <div className="settings-grid">
        <SettingsCard icon="megaphone" title={t("admin.settings.general")} sub={t("admin.settings.generalSub")}>
          <TextSetting id="st-site" label={t("admin.settings.siteName")} help={t("admin.settings.siteNameHelp")}
            value={draft.site_name} max={60} onChange={(v) => set("site_name", v)} invalid={fieldError === "site_name"} />
          <div className="field">
            <label htmlFor="st-announce">{t("admin.settings.announcement")}</label>
            <textarea id="st-announce" className="input textarea" rows={2} maxLength={280}
              placeholder={t("admin.settings.announcementPlaceholder")} value={draft.announcement}
              onChange={(e) => set("announcement", e.target.value)} aria-invalid={fieldError === "announcement"} />
            <p className="hint">
              {t("admin.settings.announcementHelp")} <span className="num">{draft.announcement.length}/280</span>
            </p>
            {draft.announcement.trim() ? (
              <div className="announce announce--preview" aria-label={t("admin.settings.preview")}>
                <Icon name="megaphone" size={15} />
                <span>{draft.announcement}</span>
              </div>
            ) : null}
          </div>
        </SettingsCard>

        <SettingsCard icon="clock" title={t("admin.settings.sessions")} sub={t("admin.settings.sessionsSub")}>
          <NumberSetting id="st-idle" label={t("admin.settings.idle")} help={t("admin.settings.idleHelp")}
            value={draft.session_idle_minutes} min={5} max={1440} unit={units("minutes")}
            onChange={(v) => set("session_idle_minutes", v)} invalid={fieldError === "session_idle_minutes"} />
          <NumberSetting id="st-max" label={t("admin.settings.maxAge")} help={t("admin.settings.maxAgeHelp")}
            value={draft.session_max_hours} min={1} max={720} unit={units("hours")}
            onChange={(v) => set("session_max_hours", v)} invalid={fieldError === "session_max_hours"} />
          <ToggleSetting id="st-remember" label={t("admin.settings.remember")} help={t("admin.settings.rememberHelp")}
            checked={draft.allow_remember_me} onChange={(v) => set("allow_remember_me", v)} />
          {draft.allow_remember_me ? (
            <NumberSetting id="st-remember-days" label={t("admin.settings.rememberDays")}
              value={draft.remember_me_days} min={1} max={90} unit={units("days")}
              onChange={(v) => set("remember_me_days", v)} invalid={fieldError === "remember_me_days"} />
          ) : null}
        </SettingsCard>

        <SettingsCard icon="lock" title={t("admin.settings.passwords")} sub={t("admin.settings.passwordsSub")}>
          <NumberSetting id="st-min" label={t("admin.settings.minLength")} help={t("admin.settings.minLengthHelp")}
            value={draft.password_min_length} min={8} max={64} unit={units("chars")}
            onChange={(v) => set("password_min_length", v)} invalid={fieldError === "password_min_length"} />
          <NumberSetting id="st-lock" label={t("admin.settings.lockout")} help={t("admin.settings.lockoutHelp")}
            value={draft.lockout_threshold} min={3} max={20} unit={units("attempts")}
            onChange={(v) => set("lockout_threshold", v)} invalid={fieldError === "lockout_threshold"} />
          <NumberSetting id="st-lock-min" label={t("admin.settings.lockoutMinutes")}
            value={draft.lockout_minutes} min={1} max={1440} unit={units("minutes")}
            onChange={(v) => set("lockout_minutes", v)} invalid={fieldError === "lockout_minutes"} />
        </SettingsCard>

        <SettingsCard icon="userPlus" title={t("admin.settings.access")} sub={t("admin.settings.accessSub")}>
          <ToggleSetting id="st-requests" label={t("admin.settings.allowRequests")}
            help={t("admin.settings.allowRequestsHelp")} checked={draft.allow_access_requests}
            onChange={(v) => set("allow_access_requests", v)} />
        </SettingsCard>
      </div>

      {dirty || saveError ? (
        <div className="savebar" role="region" aria-label={t("admin.settings.unsaved")}>
          <span className="savebar__text">
            <Icon name="info" size={16} />
            {saveError ? errorText(saveError, t) : t("admin.settings.unsaved")}
          </span>
          <button type="button" className="btn btn--ghost" onClick={() => { setDraft(saved); setSaveError(null); }}
            disabled={busy}>
            {t("admin.settings.discard")}
          </button>
          <button type="button" className="btn btn--primary" onClick={save} disabled={busy || !dirty || incomplete}
            {...(busy ? { "data-busy": "" } : {})}>
            <Icon name="check" size={15} /> {t("admin.settings.save")}
          </button>
        </div>
      ) : null}
      {saveError && !dirty ? <FormNote>{errorText(saveError, t)}</FormNote> : null}
    </>
  );
}

function SettingsCard({ icon, title, sub, children }) {
  return (
    <section className="card card--pad settings-card">
      <div className="card-head">
        <div>
          <h2>{title}</h2>
          <p className="sub">{sub}</p>
        </div>
        <span className="settings-card__icon" aria-hidden="true">
          <Icon name={icon} size={17} />
        </span>
      </div>
      <div className="settings-card__body">{children}</div>
    </section>
  );
}

function TextSetting({ id, label, help, value, onChange, max, invalid }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="input" value={value} maxLength={max} onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid || !value.trim()} />
      {help ? <p className="hint">{help}</p> : null}
    </div>
  );
}

function NumberSetting({ id, label, help, value, onChange, min, max, unit, invalid }) {
  const out = value < min || value > max;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="input-unit">
        <input id={id} className="input num" type="number" inputMode="numeric" min={min} max={max} step={1}
          value={Number.isFinite(value) ? value : ""}
          onChange={(e) => onChange(e.target.value === "" ? NaN : Math.round(Number(e.target.value)))}
          aria-invalid={invalid || out || !Number.isFinite(value)} />
        <span className="input-unit__unit">{unit}</span>
      </div>
      <p className="hint">
        {help ? `${help} ` : ""}
        <span className="num">({min}–{max})</span>
      </p>
    </div>
  );
}

function ToggleSetting({ id, label, help, checked, onChange }) {
  return (
    <div className="toggle-row">
      <div>
        <label htmlFor={id} className="toggle-row__label">{label}</label>
        {help ? <p className="hint">{help}</p> : null}
      </div>
      <button id={id} type="button" role="switch" aria-checked={checked}
        className={`switch${checked ? " is-on" : ""}`} onClick={() => onChange(!checked)}>
        <span className="switch__knob" />
      </button>
    </div>
  );
}
