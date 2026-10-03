/* The dialogs behind every per-user action -- shared by the users table's
   row menu and the user drawer, so an action behaves the same whichever
   way it was reached. `action` is { kind, user }; `onDone` runs after any
   successful change so the caller can reload. */

import { useEffect, useState } from "react";
import Dialog from "../../components/Dialog.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import Icon from "../../components/Icon.jsx";
import PasswordField from "../../components/PasswordField.jsx";
import CopyButton from "../../components/CopyButton.jsx";
import { FormNote } from "../../components/AuthLayout.jsx";
import { useAuth } from "../../state/AuthContext.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { dateTime } from "../../lib/format.js";
import { errorText } from "../../lib/auth.js";
import { useAdmin } from "./shared.jsx";

export default function UserActions({ action, onClose, onDone }) {
  const { api, refreshBadge } = useAdmin();
  const { t } = useI18n();
  const toast = useToast();
  const kind = action?.kind;
  const user = action?.user;

  const finish = (message) => {
    if (message) toast.ok(message);
    refreshBadge?.();
    onDone?.();
  };

  return (
    <>
      <PasswordDialog open={kind === "password"} user={user} onClose={onClose} onDone={() => finish()} />
      <LinkDialog open={kind === "link"} user={user} onClose={onClose} onDone={() => finish()} />
      <ApproveDialog open={kind === "approve"} user={user} onClose={onClose}
        onDone={() => finish(t("admin.drawer.approved"))} />
      <ConfirmDialog
        open={kind === "disable"}
        title={t("admin.drawer.disableTitle")}
        body={t("admin.drawer.disableBody", { name: user?.name })}
        confirmLabel={t("admin.users.disable")}
        icon="ban"
        onConfirm={async () => {
          await api.updateUser(user.id, { status: "disabled" });
          finish(t("admin.drawer.disabled"));
        }}
        onClose={onClose}
      />
      <ConfirmDialog
        open={kind === "delete"}
        title={t("admin.drawer.deleteTitle")}
        body={t("admin.drawer.deleteBody", { name: user?.name })}
        confirmLabel={t("admin.users.delete")}
        icon="trash"
        typeToConfirm={user?.email}
        typeLabel={t("admin.drawer.deleteConfirm", { email: user?.email })}
        onConfirm={async () => {
          await api.deleteUser(user.id);
          finish(t("admin.drawer.deleted"));
        }}
        onClose={onClose}
      />
      <ConfirmDialog
        open={kind === "reject"}
        title={t("admin.drawer.rejectTitle")}
        body={t("admin.drawer.rejectBody", { email: user?.email })}
        confirmLabel={t("admin.users.reject")}
        icon="ban"
        onConfirm={async () => {
          await api.deleteUser(user.id);
          finish(t("admin.drawer.rejected"));
        }}
        onClose={onClose}
      />
      <ConfirmDialog
        open={kind === "signout"}
        title={t("admin.drawer.signOutTitle")}
        body={t("admin.drawer.signOutBody", { name: user?.name })}
        confirmLabel={t("admin.users.signOutAll")}
        icon="logout"
        tone="warn"
        onConfirm={async () => {
          const result = await api.signOut(user.id);
          finish(t("admin.drawer.signedOut", { n: result.revoked ?? 0 }));
        }}
        onClose={onClose}
      />
    </>
  );
}

/** Enable and unlock need no confirmation: they give access back. */
export async function quickAction(api, kind, user) {
  if (kind === "enable") return api.updateUser(user.id, { status: "active" });
  if (kind === "unlock") return api.unlock(user.id);
  throw new Error(`Unknown action ${kind}`);
}

function PasswordDialog({ open, user, onClose, onDone }) {
  const { api } = useAdmin();
  const { config } = useAuth();
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const min = config?.password_min_length ?? 10;

  useEffect(() => {
    if (open) {
      setPassword("");
      setMustChange(true);
      setError(null);
      setDone(false);
      setBusy(false);
    }
  }, [open]);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.setPassword(user.id, { password, must_change_password: mustChange });
      setDone(true);
      onDone();
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={busy ? () => {} : onClose}
      icon="key"
      tone={done ? "ok" : undefined}
      title={done ? t("admin.drawer.passwordSet") : t("admin.drawer.setPasswordTitle")}
      subtitle={user ? `${user.name} · ${user.email}` : ""}
      footer={
        done ? (
          <button type="button" className="btn btn--primary" onClick={onClose} data-autofocus="">
            {t("admin.form.done")}
          </button>
        ) : (
          <>
            <button type="button" className="btn" onClick={onClose} disabled={busy}>{t("common.cancel")}</button>
            <button type="submit" form="set-password-form" className="btn btn--primary"
              disabled={busy || password.length < min} {...(busy ? { "data-busy": "" } : {})}>
              <Icon name="key" size={15} /> {t("admin.drawer.setPassword")}
            </button>
          </>
        )
      }
    >
      {done ? (
        <div className="handoff">
          <div className="handoff__row">
            <span className="handoff__label">{t("admin.form.password")}</span>
            <code className="handoff__value">{password}</code>
          </div>
          <div className="handoff__copy">
            <CopyButton text={password} />
          </div>
        </div>
      ) : (
        <form id="set-password-form" onSubmit={submit} noValidate>
          <p className="dialog__text">{t("admin.drawer.setPasswordBody")}</p>
          <PasswordField id="sp-password" label={t("admin.form.password")} value={password}
            onChange={(v) => { setPassword(v); setError(null); }} generator minLength={min} autoFocus />
          <label className="check" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
            {t("admin.form.mustChange")}
          </label>
          {error ? <div style={{ marginTop: 12 }}><FormNote>{error}</FormNote></div> : null}
        </form>
      )}
    </Dialog>
  );
}

function LinkDialog({ open, user, onClose, onDone }) {
  const { api } = useAdmin();
  const { t, locale } = useI18n();
  const [link, setLink] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setLink(null);
      setError(null);
      setBusy(false);
    }
  }, [open]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.link(user.id);
      setLink(result.link);
      onDone();
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  const url = link ? `${window.location.origin}${link.path}` : "";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      icon="mail"
      tone={link ? "ok" : undefined}
      title={link ? t("admin.drawer.linkCreated") : t("admin.drawer.linkTitle")}
      subtitle={user ? `${user.name} · ${user.email}` : ""}
      footer={
        link ? (
          <button type="button" className="btn btn--primary" onClick={onClose} data-autofocus="">{t("admin.form.done")}</button>
        ) : (
          <>
            <button type="button" className="btn" onClick={onClose}>{t("common.cancel")}</button>
            <button type="button" className="btn btn--primary" onClick={create} disabled={busy}
              {...(busy ? { "data-busy": "" } : {})} data-autofocus="">
              <Icon name="mail" size={15} /> {t("admin.drawer.linkCreate")}
            </button>
          </>
        )
      }
    >
      {link ? (
        <>
          <p className="dialog__text">
            {t("admin.drawer.linkBody", { email: user?.email, when: dateTime(link.expires_at, locale) })}
          </p>
          <div className="handoff">
            <div className="handoff__row handoff__row--link">
              <span className="handoff__label">{t("admin.drawer.linkTitle")}</span>
              <code className="handoff__value">{url}</code>
            </div>
            <div className="handoff__copy">
              <CopyButton text={url} />
            </div>
          </div>
        </>
      ) : (
        <p className="dialog__text">
          {t(user?.status === "invited" ? "admin.form.accessInviteSub" : "admin.drawer.linkIntro")}
        </p>
      )}
      {error ? <div style={{ marginTop: 12 }}><FormNote>{error}</FormNote></div> : null}
    </Dialog>
  );
}

function ApproveDialog({ open, user, onClose, onDone }) {
  const { api } = useAdmin();
  const { t } = useI18n();
  const [role, setRole] = useState("pathologist");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setRole("pathologist");
      setError(null);
      setBusy(false);
    }
  }, [open]);

  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.approve(user.id, role);
      onDone();
      onClose();
    } catch (err) {
      setError(errorText(err, t));
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={busy ? () => {} : onClose}
      icon="userCheck"
      title={t("admin.drawer.approveTitle")}
      subtitle={user ? `${user.name} · ${user.email}` : ""}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>{t("common.cancel")}</button>
          <button type="button" className="btn btn--primary" onClick={approve} disabled={busy}
            {...(busy ? { "data-busy": "" } : {})}>
            <Icon name="check" size={15} /> {t("admin.users.approve")}
          </button>
        </>
      }
    >
      <p className="dialog__text">{t("admin.drawer.approveBody", { name: user?.name })}</p>
      {user?.request_note ? (
        <blockquote className="attention__note">
          <span className="tiny muted">{t("admin.drawer.requestNote")}</span>
          <br />
          {user.request_note}
        </blockquote>
      ) : null}
      <div className="choice-grid" style={{ marginTop: 12 }}>
        {["pathologist", "viewer", "admin"].map((value) => (
          <label key={value} className={`choice${role === value ? " is-on" : ""}`}>
            <input type="radio" name="approve-role" value={value} checked={role === value} onChange={() => setRole(value)} />
            <span className="choice__title">{t(`roles.${value}`)}</span>
            <span className="choice__sub">{t(`roleHelp.${value}`)}</span>
          </label>
        ))}
      </div>
      {error ? <div style={{ marginTop: 12 }}><FormNote>{error}</FormNote></div> : null}
    </Dialog>
  );
}
