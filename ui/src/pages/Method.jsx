/* Method and caveats. The four caveat texts come from the server
   (context.caveats) so they cannot drift away from what the backend and the
   PDF report say; the demo module carries the same four strings. */

import Icon from "../components/Icon.jsx";
import { usePortal } from "../state/PortalContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { CAVEAT_KEYS, resolveCaveats } from "../i18n/caveats.js";

const STEP_KEYS = ["detect", "classify", "baseline", "quantify", "hand"];
const DATA_KEYS = ["local", "log", "report"];

export default function Method() {
  const { context } = usePortal();
  const t = useT();
  const caveats = resolveCaveats(context?.caveats, context?.demo, t);

  return (
    <>
      <div className="page__head">
        <div>
          <div className="eyebrow">{t("method.eyebrow")}</div>
          <h1>{t("method.title")}</h1>
          <p className="lede">{t("method.lede")}</p>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("method.caveatsTitle")}</h2>
                <p className="sub">{t("method.caveatsSub")}</p>
              </div>
            </div>
            <dl className="caveats">
              {CAVEAT_KEYS.map((key) =>
                caveats[key] ? (
                  <div key={key}>
                    <dt>{t(`method.caveatTitles.${key}`)}</dt>
                    <dd>{caveats[key]}</dd>
                  </div>
                ) : null,
              )}
            </dl>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("method.pipeline")}</h2>
                <p className="sub">{t("method.pipelineSub")}</p>
              </div>
            </div>
            <div className="timeline">
              {STEP_KEYS.map((key, i) => (
                <div className="timeline__item" key={key}>
                  <div className="timeline__when">{t("method.step", { n: i + 1 })}</div>
                  <div className="timeline__what">
                    <b>{t(`method.steps.${key}Title`)}</b> —{" "}
                    <span className="muted">{t(`method.steps.${key}Body`)}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="dash-col">
          <section className="card card--pad rise">
            <div className="note note--warn">
              <span className="note__icon">
                <Icon name="shield" size={16} />
              </span>
              <span>
                <strong>{t("method.notDeviceLead")}</strong> {t("method.notDeviceBody")}
              </span>
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("method.dataTitle")}</h2>
                <p className="sub">{t("method.dataSub")}</p>
              </div>
            </div>
            <div className="list">
              {DATA_KEYS.map((key) => (
                <div className="list__row" key={key}>
                  <span className="kpi__icon" style={{ width: 30, height: 30 }}>
                    <Icon name="lock" size={15} />
                  </span>
                  <div className="list__body">
                    <div className="list__title">{t(`method.data.${key}Title`)}</div>
                    <div className="list__meta" style={{ whiteSpace: "normal", lineHeight: 1.5 }}>
                      {t(`method.data.${key}Body`)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card card--pad rise">
            <div className="card-head">
              <div>
                <h2>{t("method.refTitle")}</h2>
                <p className="sub">{t("method.refSub")}</p>
              </div>
            </div>
            <div className="list">
              <a
                className="list__row"
                href="https://arxiv.org/abs/2206.01794"
                target="_blank"
                rel="noreferrer noopener"
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <span className="kpi__icon" style={{ width: 30, height: 30 }}>
                  <Icon name="file" size={15} />
                </span>
                <div className="list__body">
                  <div className="list__title">{t("method.refs.amilTitle")}</div>
                  <div className="list__meta">{t("method.refs.amilMeta")}</div>
                </div>
                <Icon name="arrowRight" size={15} />
              </a>
              <a
                className="list__row"
                href="https://www.pathai.com/aim-her2-breast-cancer"
                target="_blank"
                rel="noreferrer noopener"
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <span className="kpi__icon" style={{ width: 30, height: 30 }}>
                  <Icon name="book" size={15} />
                </span>
                <div className="list__body">
                  <div className="list__title">{t("method.refs.pathaiTitle")}</div>
                  <div className="list__meta">{t("method.refs.pathaiMeta")}</div>
                </div>
                <Icon name="arrowRight" size={15} />
              </a>
            </div>
          </section>
        </div>
      </div>

      <p className="footer-note">
        {t("common.notMedicalDevice")}
      </p>
    </>
  );
}
