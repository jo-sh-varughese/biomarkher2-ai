import { NavLink } from "react-router-dom";
import Icon from "./Icon.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { runName } from "../lib/format.js";
import { useT } from "../i18n/I18nContext.jsx";

const NAV = [
  { to: "/overview", icon: "grid", key: "nav.overview" },
  { to: "/analysis", icon: "scan", key: "nav.analysis" },
  { to: "/slides", icon: "layers", key: "nav.slides" },
  { to: "/review", icon: "stethoscope", key: "review.nav" },
  { to: "/cases", icon: "clipboard", key: "nav.cases", badge: "reviews" },
  { to: "/model", icon: "layers", key: "nav.model" },
];

const SECONDARY = [{ to: "/method", icon: "book", key: "nav.method" }];

const ADMIN = [{ to: "/admin", icon: "shield", key: "admin.navConsole", badge: "pending" }];

export default function Sidebar({ open, collapsed, onClose }) {
  const { context, reviews } = usePortal();
  const { can, pendingRequests } = useAuth();
  const t = useT();
  const provenance = context?.provenance;
  const counts = { reviews: reviews.length, pending: pendingRequests };

  const item = (entry, secondary = false) => {
    const count = entry.badge ? counts[entry.badge] : 0;
    return (
      <NavLink
        key={entry.to}
        to={entry.to}
        end={entry.end}
        onClick={onClose}
        className={({ isActive }) => `nav__item${isActive ? " is-active" : ""}`}
        // Collapsed to a rail, the label is gone and the icon is the only
        // affordance left, so it has to carry the name itself.
        title={collapsed ? t(entry.key) : undefined}
        aria-label={collapsed ? t(entry.key) : undefined}
        data-secondary={secondary ? "" : undefined}
      >
        <span className="nav__icon">
          <Icon name={entry.icon} size={17} />
          {collapsed && count ? <span className="nav__pip" /> : null}
        </span>
        <span className="nav__text">{t(entry.key)}</span>
        {!collapsed && count ? (
          <span className={`count${entry.badge === "pending" ? " count--warn" : ""}`}>{count}</span>
        ) : null}
      </NavLink>
    );
  };

  return (
    <>
      {open ? <div className="sidebar__scrim" onClick={onClose} /> : null}
      <aside className={`sidebar${open ? " is-open" : ""}${collapsed ? " is-rail" : ""}`}>
        <div className="sidebar__panel">
          <div className="brand">
            <span className="brand__mark">
              <Icon name="logo" size={21} strokeWidth={1.7} />
            </span>
            <div className="brand__text">
              <div className="brand__name">
                BioMark<em>HER2</em>
              </div>
              <div className="brand__sub">{t("common.tagline")}</div>
            </div>
          </div>

          <nav className="nav" aria-label={t("nav.primary")}>
            {NAV.map((entry) => item(entry))}

            {collapsed ? (
              <hr className="nav__rule" />
            ) : (
              <div className="nav__label">{t("nav.reference")}</div>
            )}
            {SECONDARY.map((entry) => item(entry, true))}

            {/* Administrators only. The server refuses /api/admin to anyone
                else; leaving the link out keeps it from being a dead end. */}
            {can("admin") ? (
              <>
                {collapsed ? (
                  <hr className="nav__rule" />
                ) : (
                  <div className="nav__label">{t("admin.navLabel")}</div>
                )}
                {ADMIN.map((entry) => item(entry, true))}
              </>
            ) : null}
          </nav>

          <div className="sidebar__spacer" />

          {/* Which checkpoint is answering is a run-time fact and belongs on
              screen at all times, not buried in an About page. Collapsed, it
              shrinks to the status light alone -- still visible, still
              carrying the demo-vs-live distinction in its tooltip. */}
          {collapsed ? (
            <div
              className="rail-status rail-status--dot"
              title={
                provenance
                  ? `${t(context?.demo ? "common.demoData" : "common.modelOnline")} — ${provenance.run}, ${t("common.epochShort", { n: provenance.epoch })}`
                  : t("nav.modelStatusUnknown")
              }
            >
              <span className="pulse-dot" data-tone={context?.demo ? "warn" : "ok"} />
            </div>
          ) : (
            <dl className="rail-status">
              <div className="rail-status__row">
                <dt style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span className="pulse-dot" data-tone={context?.demo ? "warn" : "ok"} />
                  {t(context?.demo ? "common.demoData" : "common.modelOnline")}
                </dt>
              </div>
              {/* Two models answer on the Field analysis page: the pre-score
                  (multi-task U-Net) and the stain map. Name both, or the
                  panel reads as if the stain map produced the pre-score. */}
              <div className="rail-status__row">
                <dt>{t("common.prescoreModel")}</dt>
                <dd title={context?.prescore_model?.checkpoint}>
                  {context?.prescore_model
                    ? `${context.prescore_model.encoder ?? ""} · ${t("common.epochShort", { n: context.prescore_model.epoch })}`
                    : "—"}
                </dd>
              </div>
              <div className="rail-status__row">
                <dt>{t("common.stainModel")}</dt>
                <dd title={provenance?.run}>
                  {provenance?.run ? `${runName(provenance.run)} · ${t("common.epochShort", { n: provenance.epoch })}` : "—"}
                </dd>
              </div>
            </dl>
          )}
        </div>
      </aside>
    </>
  );
}
