import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import Icon from "./Icon.jsx";
import { ScoreBadge } from "./Badges.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useTheme } from "../state/ThemeContext.jsx";
import { avatarStyle } from "../state/AuthContext.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { initials, relativeTime, shortId } from "../lib/format.js";
import { LANGS, useI18n } from "../i18n/I18nContext.jsx";
import LangToggle from "./LangToggle.jsx";

const SEEN_KEY = "bmh2.activitySeen.v1";

const readSeen = () => {
  try {
    return Number(localStorage.getItem(SEEN_KEY)) || 0;
  } catch {
    return 0;
  }
};

const TITLE_KEYS = {
  "/overview": "nav.overview",
  "/analysis": "nav.analysis",
  "/cases": "nav.cases",
  "/model": "nav.model",
  "/method": "nav.method",
  "/profile": "profile.title",
};

export default function Topbar({ onOpenNav, onToggleRail, railCollapsed }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const { resolved, toggle } = useTheme();
  const { t, lang, setLang, locale } = useI18n();
  const { reviews, context } = usePortal();

  const [menuOpen, setMenuOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [seen, setSeen] = useState(readSeen);
  const menuRef = useRef(null);
  const activityRef = useRef(null);
  const searchRef = useRef(null);

  // "Unread" is sign-offs recorded since this browser last opened the panel.
  const unread = reviews.filter((r) => new Date(r.at).getTime() > seen).length;
  const openActivity = () => {
    if (!activityOpen) {
      const now = Date.now();
      setSeen(now);
      try {
        localStorage.setItem(SEEN_KEY, String(now));
      } catch {
        /* Not remembering is fine; the dot just returns next session. */
      }
    }
    setActivityOpen(!activityOpen);
  };

  useEffect(() => {
    const onDocClick = (event) => {
      if (activityRef.current && !activityRef.current.contains(event.target)) setActivityOpen(false);
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
        // Collapse the submenu too, so reopening the menu starts clean rather
        // than in whatever state it was abandoned in.
        setLangOpen(false);
      }
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        setActivityOpen(false);
        // Escape backs out one level at a time, as a nested menu should.
        setLangOpen((open) => {
          if (open) return false;
          setMenuOpen(false);
          return false;
        });
      }
      // Cmd/Ctrl-K focuses search, the shortcut the kbd hint advertises.
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <header className="topbar">
      <button
        type="button"
        className="btn btn--ghost btn--icon nav-toggle"
        onClick={onOpenNav}
        aria-label={t("nav.openNav")}
      >
        <Icon name="menu" size={19} />
      </button>

      {/* Desktop only: the drawer button above takes over below 1120px, where
          there is no rail to collapse in the first place. */}
      <button
        type="button"
        className="btn btn--ghost btn--icon rail-toggle"
        onClick={onToggleRail}
        aria-label={t(railCollapsed ? "nav.expand" : "nav.collapse")}
        aria-pressed={railCollapsed}
        title={`${t(railCollapsed ? "nav.expand" : "nav.collapse")}  ([)`}
      >
        <Icon name={railCollapsed ? "chevronsRight" : "chevronsLeft"} size={18} />
      </button>

      <div className="topbar__crumbs">
        <span>{t("nav.portal")}</span>
        <span className="sep">
          <Icon name="chevronRight" size={13} />
        </span>
        <b>{t(TITLE_KEYS[pathname] ?? "nav.portal")}</b>
      </div>

      <div className="topbar__search">
        <Icon name="search" size={16} />
        <input
          ref={searchRef}
          className="input"
          type="search"
          placeholder={t("topbar.search")}
          aria-label={t("topbar.searchLabel")}
          onKeyDown={(event) => {
            if (event.key === "Enter") navigate(`/cases?q=${encodeURIComponent(event.target.value)}`);
          }}
        />
        <kbd>⌘K</kbd>
      </div>

      <div className="topbar__tools">
        <LangToggle />

        <button
          type="button"
          className="btn btn--ghost btn--icon"
          onClick={toggle}
          aria-label={t(resolved === "dark" ? "topbar.toLight" : "topbar.toDark")}
          title={t(resolved === "dark" ? "topbar.toLight" : "topbar.toDark")}
        >
          <Icon name={resolved === "dark" ? "sun" : "moon"} size={18} />
        </button>

        <div style={{ position: "relative" }} ref={activityRef}>
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            aria-label={t("topbar.activity")}
            title={t("topbar.activity")}
            aria-haspopup="dialog"
            aria-expanded={activityOpen}
            onClick={openActivity}
          >
            <Icon name="bell" size={18} />
            {unread ? <span className="bell-dot" aria-hidden="true" /> : null}
          </button>

          {activityOpen ? (
            <div className="menu activity" role="dialog" aria-label={t("topbar.activity")}>
              <div className="activity__head">
                <b>{t("topbar.activity")}</b>
                <span className="tiny muted">{t("topbar.activitySub")}</span>
              </div>
              {reviews.length ? (
                <ul className="activity__list">
                  {reviews.slice(0, 5).map((r) => (
                    <li key={r.id}>
                      <ScoreBadge score={r.score} classes={context?.classes} t={t} />
                      <div className="activity__text">
                        <span className="mono" title={r.patch_id}>{shortId(r.patch_id)}</span>
                        <span className="tiny muted">
                          {r.reviewer} · {relativeTime(r.at, t, locale)}
                        </span>
                      </div>
                      {r.agrees ? null : (
                        <span className="activity__flag" title={t("table.flagged")}>
                          <Icon name="alert" size={13} />
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="hint" style={{ padding: "10px 14px" }}>{t("topbar.activityEmpty")}</p>
              )}
              <Link to="/cases" className="menu__item activity__all" onClick={() => setActivityOpen(false)}>
                {t("topbar.activityAll")} <Icon name="arrowRight" size={14} />
              </Link>
            </div>
          ) : null}
        </div>

        <div style={{ position: "relative" }} ref={menuRef}>
          <button
            type="button"
            className="user-chip"
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <span className="avatar" style={avatarStyle(user?.accent)}>{initials(user?.name)}</span>
            <span style={{ textAlign: "left" }}>
              <span className="user-chip__name">{user?.name}</span>
              <br />
              <span className="user-chip__role">{t(user?.roleKey ?? "demo.role")}</span>
            </span>
          </button>

          {menuOpen ? (
            <div className="menu" role="menu">
              <div className="menu__head">
                <div style={{ fontWeight: 700, fontSize: "0.8125rem" }}>{user?.name}</div>
                <div className="tiny muted">{user?.email}</div>
                <div className="tiny muted" style={{ marginTop: 4 }}>
                  {t("topbar.registration", { id: user?.registration })}
                </div>
              </div>
              <Link to="/profile" className="menu__item" role="menuitem" onClick={() => setMenuOpen(false)}>
                <Icon name="user" size={16} /> {t("topbar.profile")}
              </Link>
              <Link
                to="/profile#security"
                className="menu__item"
                role="menuitem"
                onClick={() => setMenuOpen(false)}
              >
                <Icon name="settings" size={16} /> {t("topbar.preferences")}
              </Link>

              {/* Language sits in the menu as well as in the top bar. The bar
                  toggle is the fast path for someone who already knows it is
                  there; this is where people look for a setting. It shows the
                  current value collapsed, so the menu stays short. */}
              <button
                type="button"
                className="menu__item menu__item--expand"
                role="menuitem"
                aria-expanded={langOpen}
                onClick={() => setLangOpen((v) => !v)}
              >
                <Icon name="globe" size={16} />
                {t("common.language")}
                <span className="menu__value" lang={lang}>
                  {LANGS.find((l) => l.id === lang)?.label}
                </span>
                <span className={`menu__chev${langOpen ? " is-open" : ""}`}>
                  <Icon name="chevronRight" size={13} />
                </span>
              </button>

              {langOpen ? (
                <div className="menu__options" role="group" aria-label={t("common.language")}>
                  {LANGS.map((entry) => (
                    <button
                      key={entry.id}
                      type="button"
                      lang={entry.id}
                      className="menu__item menu__item--option"
                      role="menuitemradio"
                      aria-checked={lang === entry.id}
                      onClick={() => {
                        setLang(entry.id);
                        setLangOpen(false);
                        setMenuOpen(false);
                      }}
                    >
                      <span className="menu__tick">
                        {lang === entry.id ? <Icon name="check" size={14} /> : null}
                      </span>
                      {entry.label}
                    </button>
                  ))}
                </div>
              ) : null}
              <button
                type="button"
                className="menu__item menu__item--danger"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  signOut();
                }}
              >
                <Icon name="logout" size={16} /> {t("topbar.signOut")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
