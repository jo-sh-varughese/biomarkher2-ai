/* Everything about one account, in a drawer over the users table: edit
   their details and role, see how and where they sign in, end their
   sessions, reset their password, and -- at the bottom, set apart -- take
   their access away. Opened from /admin/users/:userId, so a link to a
   particular account can be shared between administrators. */

import { useEffect, useMemo, useState } from "react";
import Dialog from "../../components/Dialog.jsx";
import Icon from "../../components/Icon.jsx";
import { FormNote } from "../../components/AuthLayout.jsx";
import { avatarStyle, useAuth } from "../../state/AuthContext.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { initials, relativeTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import UserActions, { quickAction } from "./UserActions.jsx";
import {
  EventRow,
  LoadError,
  RoleBadge,
  SkeletonRows,
  StatusPill,
  device,
  deviceLabel,
  stamp,
  useAdmin,
  useLoad,
  userState,
  when,
} from "./shared.jsx";

export default function UserDrawer({ userId, onClose, onChanged }) {
  const { api, refreshBadge } = useAdmin();
  const { user: me } = useAuth();
  const { t, locale } = useI18n();
  const toast = useToast();
  const { data, error, reload } = useLoad(() => api.user(userId), [api, userId]);
  const [action, setAction] = useState(null);
  const [busy, setBusy] = useState(null);

  const user = data?.user;
  const isSelf = user && me && (user.id === me.id || user.email === me.email);

  const changed = async () => {
    await reload().catch(() => {});
    onChanged?.();
  };

  const quick = async (kind) => {
    setBusy(kind);
    try {
      await quickAction(api, kind, user);
      toast.ok(t(kind === "enable" ? "admin.drawer.enabled" : "admin.drawer.unlocked"));
      refreshBadge?.();
      await changed();
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    } finally {
      setBusy(null);
    }
  };

  const revokeSession = async (session) => {
    setBusy(session.id);
    try {
      await api.revokeSession(session.id);
      toast.ok(t("admin.sessions.revoked"));
      await changed();
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog
      open
      variant="drawer"
      size="lg"
      onClose={onClose}
      title={user ? user.name : "…"}
      subtitle={user?.email}
    >
      {error && !data ? (
        <LoadError error={error} onRetry={reload} t={t} />
      ) : !user ? (
        <SkeletonRows rows={6} />
      ) : (
        <div className="drawer-body">
          <div className="drawer-id">
            <span className="avatar avatar--xl" style={avatarStyle(user.accent)} aria-hidden="true">
              {initials(user.name)}
            </span>
            <div className="drawer-id__text">
              <div className="drawer-id__badges">
                <RoleBadge role={user.role} t={t} />
                <StatusPill user={user} t={t} />
                {isSelf ? <span className="you-tag">{t("admin.you")}</span> : null}
              </div>
              <p className="tiny muted">
                {user.title || t(`roles.${user.role}`)}
                {user.registration ? ` · ${user.registration}` : ""}
              </p>
            </div>
          </div>

          <StateNote user={user} isSelf={isSelf} t={t} locale={locale} />

          {user.status === "pending" ? (
            <section className="drawer-section">
              {user.request_note ? (
                <blockquote className="attention__note">
                  <span className="tiny muted">{t("admin.drawer.requestNote")}</span>
                  <br />
                  {user.request_note}
                </blockquote>
              ) : null}
              <div className="btn-row">
                <button type="button" className="btn btn--primary" onClick={() => setAction({ kind: "approve", user })}>
                  <Icon name="userCheck" size={15} /> {t("admin.users.approve")}
                </button>
                <button type="button" className="btn" onClick={() => setAction({ kind: "reject", user })}>
                  <Icon name="ban" size={15} /> {t("admin.users.reject")}
                </button>
              </div>
            </section>
          ) : null}

          <DetailsForm user={user} isSelf={isSelf} onSaved={changed} />

          {user.status !== "pending" ? (
            <section className="drawer-section">
              <h3>{t("admin.drawer.security")}</h3>
              <dl className="facts">
                <div>
                  <dt>{t("admin.drawer.lastSignIn")}</dt>
                  <dd title={stamp(user.last_login_at, locale)}>{when(user.last_login_at, t, locale)}</dd>
                </div>
                <div>
                  <dt>{t("admin.drawer.lastIp")}</dt>
                  <dd className="mono">{user.last_login_ip || "—"}</dd>
                </div>
                <div>
                  <dt>{t("admin.drawer.passwordChanged")}</dt>
                  <dd title={stamp(user.password_changed_at, locale)}>{when(user.password_changed_at, t, locale)}</dd>
                </div>
                <div>
                  <dt>{t("admin.drawer.created")}</dt>
                  <dd title={stamp(user.created_at, locale)}>{relativeTime(user.created_at, t, locale)}</dd>
                </div>
                <div>
                  <dt>{t("admin.drawer.failed")}</dt>
                  <dd className={user.failed_attempts ? "tone-warn" : undefined}>{user.failed_attempts}</dd>
                </div>
                <div>
                  <dt>{t("admin.drawer.reviews")}</dt>
                  <dd>{data.reviews ?? 0}</dd>
                </div>
              </dl>
              {!isSelf ? (
                <div className="btn-row">
                  {user.status !== "disabled" ? (
                    <>
                      <button type="button" className="btn btn--sm" onClick={() => setAction({ kind: "password", user })}>
                        <Icon name="key" size={14} /> {t("admin.users.resetPassword")}
                      </button>
                      <button type="button" className="btn btn--sm" onClick={() => setAction({ kind: "link", user })}>
                        <Icon name="mail" size={14} /> {t("admin.users.resetLink")}
                      </button>
                    </>
                  ) : null}
                  {user.locked ? (
                    <button type="button" className="btn btn--sm" onClick={() => quick("unlock")} disabled={busy === "unlock"}>
                      <Icon name="unlock" size={14} /> {t("admin.users.unlock")}
                    </button>
                  ) : null}
                  {data.sessions.length ? (
                    <button type="button" className="btn btn--sm" onClick={() => setAction({ kind: "signout", user })}>
                      <Icon name="logout" size={14} /> {t("admin.users.signOutAll")}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </section>
          ) : null}

          {user.status !== "pending" ? (
            <section className="drawer-section">
              <h3>
                {t("admin.drawer.sessions")} <span className="count">{data.sessions.length}</span>
              </h3>
              {data.sessions.length ? (
                <ul className="session-list">
                  {data.sessions.map((s) => (
                    <li key={s.id} className="session-item">
                      <span className="session-item__icon" aria-hidden="true">
                        <Icon name={device(s.user_agent).icon} size={17} />
                      </span>
                      <div className="session-item__text">
                        <b>{deviceLabel(s.user_agent, t)}</b>
                        {s.current ? <span className="you-tag">{t("admin.sessions.thisDevice")}</span> : null}
                        <span className="tiny muted">
                          <span className="mono">{s.ip || "—"}</span> ·{" "}
                          {t("account.lastActive", { when: relativeTime(s.last_seen_at, t, locale) })}
                          {s.remember ? ` · ${t("admin.sessions.remembered")}` : ""}
                        </span>
                      </div>
                      {!s.current ? (
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => revokeSession(s)}
                          disabled={busy === s.id}>
                          {t("admin.sessions.revoke")}
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="hint">{t("admin.drawer.noSessions")}</p>
              )}
            </section>
          ) : null}

          <section className="drawer-section">
            <h3>{t("admin.drawer.activity")}</h3>
            {data.activity.length ? (
              <ul className="event-list event-list--tight">
                {data.activity.map((event) => (
                  <EventRow key={event.id} event={event} t={t} locale={locale} />
                ))}
              </ul>
            ) : (
              <p className="hint">{t("admin.drawer.noActivity")}</p>
            )}
          </section>

          {!isSelf && user.status !== "pending" ? (
            <section className="drawer-section drawer-section--danger">
              <h3>{t("admin.drawer.danger")}</h3>
              <div className="btn-row">
                {user.status === "disabled" ? (
                  <button type="button" className="btn" onClick={() => quick("enable")} disabled={busy === "enable"}>
                    <Icon name="checkCircle" size={15} /> {t("admin.users.enable")}
                  </button>
                ) : (
                  <button type="button" className="btn" onClick={() => setAction({ kind: "disable", user })}>
                    <Icon name="ban" size={15} /> {t("admin.users.disable")}
                  </button>
                )}
                <button type="button" className="btn btn--danger" onClick={() => setAction({ kind: "delete", user })}>
                  <Icon name="trash" size={15} /> {t("admin.users.delete")}
                </button>
              </div>
            </section>
          ) : null}
        </div>
      )}

      <UserActions
        action={action}
        onClose={() => setAction(null)}
        onDone={async () => {
          const deleted = action?.kind === "delete" || action?.kind === "reject";
          if (deleted) {
            onChanged?.();
            onClose();
          } else {
            await changed();
          }
        }}
      />
    </Dialog>
  );
}

function StateNote({ user, isSelf, t, locale }) {
  const state = userState(user);
  if (isSelf) return <FormNote tone="info" icon="info">{t("admin.drawer.selfNote")}</FormNote>;
  if (state === "locked") {
    return (
      <FormNote tone="danger" icon="lock">
        {t("admin.drawer.lockedNote", { time: stamp(user.locked_until, locale) })}
      </FormNote>
    );
  }
  if (state === "pending") {
    return (
      <FormNote tone="warn" icon="userPlus">
        {t("admin.drawer.pendingNote", { when: relativeTime(user.created_at, t, locale) })}
      </FormNote>
    );
  }
  if (state === "invited") return <FormNote tone="info" icon="mail">{t("admin.drawer.invitedNote")}</FormNote>;
  if (state === "disabled") return <FormNote tone="warn" icon="ban">{t("admin.drawer.disabledNote")}</FormNote>;
  if (state === "mustChange") return <FormNote tone="info" icon="key">{t("admin.drawer.mustChangeNote")}</FormNote>;
  return null;
}

function DetailsForm({ user, isSelf, onSaved }) {
  const { api } = useAdmin();
  const { t } = useI18n();
  const toast = useToast();
  const initial = useMemo(
    () => ({ name: user.name, email: user.email, role: user.role, registration: user.registration, title: user.title }),
    [user],
  );
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setForm(initial);
    setError(null);
  }, [initial]);

  const diff = Object.fromEntries(Object.entries(form).filter(([k, v]) => (initial[k] ?? "") !== v));
  const dirty = Object.keys(diff).length > 0;

  const save = async (event) => {
    event.preventDefault();
    if (!dirty) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateUser(user.id, diff);
      toast.ok(t("admin.drawer.saved"));
      await onSaved();
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  const set = (key) => (event) => {
    setForm((f) => ({ ...f, [key]: event.target.value }));
    setError(null);
  };

  return (
    <section className="drawer-section">
      <h3>{t("admin.drawer.details")}</h3>
      <form className="form-grid" onSubmit={save} noValidate>
        <div className="field">
          <label htmlFor="ud-name">{t("admin.form.name")}</label>
          <input id="ud-name" className="input" value={form.name} onChange={set("name")} />
        </div>
        <div className="field">
          <label htmlFor="ud-email">{t("admin.form.email")}</label>
          <input id="ud-email" className="input" type="email" value={form.email} onChange={set("email")} />
        </div>
        <div className="field">
          <label htmlFor="ud-role">{t("admin.form.role")}</label>
          <select id="ud-role" className="select" value={form.role} onChange={set("role")}
            disabled={isSelf || user.status === "pending"}>
            {["admin", "pathologist", "viewer"].map((role) => (
              <option key={role} value={role}>{t(`roles.${role}`)}</option>
            ))}
          </select>
          <p className="hint">{t(`roleHelp.${form.role}`)}</p>
        </div>
        <div className="field">
          <label htmlFor="ud-reg">{t("admin.form.registration")}</label>
          <input id="ud-reg" className="input" value={form.registration}
            onChange={(e) => setForm((f) => ({ ...f, registration: e.target.value.toUpperCase() }))} />
        </div>
        <div className="field field--span">
          <label htmlFor="ud-title">{t("admin.form.title")}</label>
          <input id="ud-title" className="input" value={form.title} onChange={set("title")}
            placeholder={t("account.jobTitlePlaceholder")} />
        </div>
        {error ? <div className="field--span"><FormNote>{error}</FormNote></div> : null}
        <div className="field--span btn-row">
          <button type="submit" className="btn btn--primary" disabled={!dirty || busy} {...(busy ? { "data-busy": "" } : {})}>
            <Icon name="check" size={15} /> {t("admin.drawer.save")}
          </button>
          {dirty ? (
            <button type="button" className="btn btn--ghost" onClick={() => setForm(initial)}>
              {t("admin.settings.discard")}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}
