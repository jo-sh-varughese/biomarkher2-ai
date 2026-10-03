/* A password input with show/hide, an optional strength meter, and -- for
   an administrator setting someone else's password -- a generator that
   fills in a strong random password and shows it so it can be copied. */

import { useState } from "react";
import Icon from "./Icon.jsx";
import CopyButton from "./CopyButton.jsx";
import { generatePassword, passwordStrength } from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";

const STRENGTH_COLORS = ["var(--line-strong)", "var(--danger)", "var(--warn)", "var(--accent)", "var(--ok)"];

export default function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete = "new-password",
  meter = true,
  generator = false,
  minLength,
  error,
  hint,
  autoFocus,
  placeholder,
}) {
  const t = useT();
  const [shown, setShown] = useState(false);
  const strength = passwordStrength(value);
  const levels = t("signup.strengthLevels");

  return (
    <div className="field">
      <div className="field__top">
        <label htmlFor={id}>{label}</label>
        {generator ? (
          <span className="field__tools">
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                onChange(generatePassword());
                setShown(true);
              }}
            >
              <Icon name="sparkles" size={13} /> {t("password.generate")}
            </button>
            {value ? <CopyButton text={value} compact /> : null}
          </span>
        ) : null}
      </div>
      <div className="auth__pw-wrap">
        <input
          id={id}
          className="input mono-when-shown"
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={hint || minLength ? `${id}-hint` : undefined}
          autoFocus={autoFocus}
          data-shown={shown ? "" : undefined}
          spellCheck={false}
        />
        <button
          type="button"
          className="auth__pw-toggle"
          onClick={() => setShown((v) => !v)}
          aria-label={t(shown ? "login.hidePassword" : "login.showPassword")}
        >
          <Icon name={shown ? "eyeOff" : "eye"} size={17} />
        </button>
      </div>
      {meter && value ? (
        <div className="strength" aria-live="polite">
          <div className="strength__bars">
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className="strength__bar"
                style={{ background: i < strength ? STRENGTH_COLORS[strength] : "var(--line)" }}
              />
            ))}
          </div>
          <span className="strength__label" style={{ color: STRENGTH_COLORS[strength] }}>
            {t("signup.strength")}: {levels[strength]}
          </span>
        </div>
      ) : null}
      {error ? (
        <span className="field__error" role="alert">
          <Icon name="alert" size={13} />
          {error}
        </span>
      ) : hint || minLength ? (
        <p className="hint" id={`${id}-hint`}>
          {hint ?? t("password.minHint", { min: minLength })}
        </p>
      ) : null}
    </div>
  );
}
