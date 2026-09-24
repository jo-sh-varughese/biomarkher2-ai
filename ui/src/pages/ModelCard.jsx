/* The model card. Specification rows describe THIS project's model. The
   comparison block at the foot describes PathAI's AIM-HER2 and is labelled as
   somebody else's product with a link to their page -- a student project's
   model card that quietly borrows a commercial system's validation numbers
   would be worse than having no model card at all. */

import Icon from "../components/Icon.jsx";
import { HeatLegend } from "../components/charts/Charts.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { runName } from "../lib/format.js";
import { useT } from "../i18n/I18nContext.jsx";

const SPEC_KEYS = ["intendedUse", "task", "indication", "inputs", "outputs", "targets", "site"];
const REF_KEYS = ["intendedUse", "outputs", "clones", "scanners", "inputs"];
const LIMIT_KEYS = ["area", "two", "label", "field"];

export default function ModelCard() {
  const { context } = usePortal();
  const t = useT();
  const p = context?.provenance;

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("model.eyebrow")}</div>
          <h1>{t("model.title")}</h1>
          <p className="lede">{t("model.lede")}</p>
        </div>
        <div className="page__actions">
          <span className="badge badge--warn">
            <Icon name="shield" size={12} /> {t("common.researchUseOnly")}
          </span>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("model.spec")}</h2>
                <p className="sub">{t("model.specSub")}</p>
              </div>
            </div>
            <dl className="spec-list">
              {SPEC_KEYS.map((key) => (
                <div key={key}>
                  <dt>{t(`model.specs.${key}`)}</dt>
                  <dd>{t(`model.specs.${key}Body`)}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("model.limitations")}</h2>
                <p className="sub">{t("model.limitationsSub")}</p>
              </div>
            </div>
            <dl className="caveats">
              {LIMIT_KEYS.map((key) => (
                <div key={key}>
                  <dt>{t(`model.limits.${key}Title`)}</dt>
                  <dd>{t(`model.limits.${key}Body`)}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("model.comparison")}</h2>
                <p className="sub">{t("model.comparisonSub")}</p>
              </div>
            </div>
            <dl className="spec-list">
              {REF_KEYS.map((key) => (
                <div key={key}>
                  <dt>{t(`model.ref.${key}`)}</dt>
                  <dd>{t(`model.ref.${key}Body`)}</dd>
                </div>
              ))}
              <div>
                <dt>{t("model.ref.reference")}</dt>
                <dd>
                  <a href="https://www.pathai.com/aim-her2-breast-cancer" target="_blank" rel="noreferrer noopener">
                    pathai.com/aim-her2-breast-cancer
                  </a>
                </dd>
              </div>
            </dl>
            <div className="note note--info" style={{ marginTop: 16 }}>
              <span className="note__icon">
                <Icon name="info" size={16} />
              </span>
              <span>
                {t("model.comparisonNote")}
              </span>
            </div>
          </section>
        </div>

        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("model.checkpoint")}</h2>
                <p className="sub">{t("model.checkpointSub")}</p>
              </div>
              <span className="pulse-dot" data-tone={context?.demo ? "warn" : "ok"} />
            </div>
            <dl className="spec-list" style={{ fontSize: "0.8125rem" }}>
              <div>
                <dt>{t("common.run")}</dt>
                <dd className="mono" title={p?.run}>{p?.run ? runName(p.run) : "—"}</dd>
              </div>
              <div>
                <dt>{t("common.epoch")}</dt>
                <dd className="mono">{p?.epoch ?? "—"}</dd>
              </div>
              <div>
                <dt>{t("common.architecture")}</dt>
                <dd className="mono">{p?.architecture?.toUpperCase() ?? "—"}</dd>
              </div>
              {p?.checkpoint_sha ? (
                <div>
                  <dt>{t("model.checkpointLabel")}</dt>
                  <dd className="mono">{p.checkpoint_sha}</dd>
                </div>
              ) : null}
              {p?.trained_at ? (
                <div>
                  <dt>{t("model.trained")}</dt>
                  <dd className="mono">{p.trained_at}</dd>
                </div>
              ) : null}
            </dl>
            {context?.demo ? (
              <div className="note note--warn" style={{ marginTop: 14 }}>
                <span className="note__icon">
                  <Icon name="alert" size={16} />
                </span>
                <span>
                  {t("model.demoWarning")}
                </span>
              </div>
            ) : null}
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("model.classes")}</h2>
                <p className="sub">{t("model.classesSub")}</p>
              </div>
            </div>
            <div style={{ display: "grid", gap: 10 }}>
              {(context?.classes ?? []).map((c) => (
                <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <span
                    style={{
                      width: 26, height: 26, borderRadius: 8, flex: "none",
                      background: c.color,
                      boxShadow: "inset 0 0 0 1px rgba(0,0,0,.08)",
                    }}
                  />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: "0.8125rem", fontWeight: 600 }}>{c.name}</div>
                    <div className="tiny muted mono">
                      {t("model.classIndex", { i: c.index, color: c.color })}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <p className="hint" style={{ marginTop: 14 }}>
              {t("model.classesNote")}
            </p>
            {context?.heatmap_legend ? (
              <div style={{ marginTop: 18 }}>
                <HeatLegend
                  legend={context.heatmap_legend}
                  title={t("analysis.heatLegend")}
                  lowLabel={t("analysis.heatLow")}
                />
              </div>
            ) : null}
          </section>
        </div>
      </div>

      <p className="footer-note">
        {t("common.notMedicalDevice")}
      </p>
    </>
  );
}
