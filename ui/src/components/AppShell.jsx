import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar.jsx";
import Topbar from "./Topbar.jsx";
import Icon from "./Icon.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";

const RAIL_KEY = "bmh2.rail.v1";

export default function AppShell() {
  const [navOpen, setNavOpen] = useState(false);
  const { pathname } = useLocation();
  const { context } = usePortal();
  const t = useT();

  // Collapsed-to-a-rail is a desktop preference and is remembered, because a
  // pathologist who wants the width back for the slide wants it back on every
  // case, not once per session.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(RAIL_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(RAIL_KEY, collapsed ? "1" : "0");
    } catch {
      /* Blocked site data just means the choice does not survive a reload. */
    }
  }, [collapsed]);

  const toggleRail = useCallback(() => setCollapsed((v) => !v), []);

  useEffect(() => {
    const onKey = (event) => {
      // The bracket shortcut most editors use for the same gesture. Ignored
      // while typing, so it never eats a keystroke in the notes field.
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target?.tagName ?? "");
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "[") {
        event.preventDefault();
        toggleRail();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [toggleRail]);

  return (
    <div className={`shell${collapsed ? " is-rail" : ""}`}>
      <Sidebar open={navOpen} collapsed={collapsed} onClose={() => setNavOpen(false)} />

      <div className="shell__main">
        <Topbar
          onOpenNav={() => setNavOpen(true)}
          onToggleRail={toggleRail}
          railCollapsed={collapsed}
        />

        <div className="safety-strip" role="note">
          <Icon name="shield" size={16} />
          <span>
            <strong>{t("safety.lead")}</strong> {t("safety.body")}
          </span>
          <span className="spacer" />
          {context?.demo ? (
            <span className="badge badge--warn" style={{ flex: "none" }}>
              <span className="dot" /> {t("common.demoData")}
            </span>
          ) : null}
        </div>

        {/* Keying on the path replays the entrance animation on every route
            change, which reads as a page transition without a transition
            library and without blocking the first paint. */}
        <main className="page" key={pathname}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
