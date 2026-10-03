/* What is running and whether it is ready to be used by other people: a
   short list of deployment checks worth passing before the portal leaves
   the machine it was built on, the server and model facts an administrator
   is asked about, where the data lives, and the exports. */

import Icon from "../../components/Icon.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { errorText } from "../../lib/auth.js";
import { runName } from "../../lib/format.js";
import { LoadError, PageHead, SkeletonRows, stamp, useAdmin, useLoad } from "./shared.jsx";

const bytes = (n) => {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
};

const duration = (seconds) => {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return [d && `${d}d`, (d || h) && `${h}h`, `${m}m`].filter(Boolean).join(" ");
};

export default function System() {
  const { api } = useAdmin();
  const { t, locale } = useI18n();
  const toast = useToast();
  const { data, error, loading, reload } = useLoad(() => api.system(), [api]);

  const download = async (name) => {
    try {
      await api.exportFile(name);
      toast.ok(t("admin.system.exported"));
    } catch (err) {
      toast.error(t("admin.loadFailed"), errorText(err, t));
    }
  };

  const head = (
    <PageHead
      eyebrow={t("admin.eyebrow")}
      title={t("admin.system.title")}
      lede={t("admin.system.lede")}
      actions={
        <button type="button" className="btn" onClick={reload} disabled={loading}>
          <Icon name="refresh" size={16} /> {t("admin.refresh")}
        </button>
      }
    />
  );

  if (error && !data) {
    return (
      <>
        {head}
        <section className="card card--pad"><LoadError error={error} onRetry={reload} t={t} /></section>
      </>
    );
  }
  if (!data) {
    return (
      <>
        {head}
        <section className="card card--pad"><SkeletonRows rows={6} /></section>
      </>
    );
  }

  const passing = data.checks.filter((c) => c.level === "ok").length;
  const onOff = (v) => t(v ? "admin.system.on" : "admin.system.off");
  const storage = [
    ["database", "database", data.storage.database],
    ["reviews", "clipboard", data.storage.reviews],
    ["annotations", "pen", data.storage.annotations],
  ];

  return (
    <>
      {head}

      <section className="card card--pad rise">
        <div className="card-head">
          <div>
            <h2>{t("admin.system.readiness")}</h2>
            <p className="sub">{t("admin.system.readinessSub")}</p>
          </div>
          <span className={`badge ${passing === data.checks.length ? "badge--ok" : "badge--warn"}`}>
            {passing}/{data.checks.length}
          </span>
        </div>
        <ul className="checks">
          {data.checks.map((check) => (
            <li key={check.id} className={`check-item check-item--${check.level}`}>
              <span className="check-item__icon" aria-hidden="true">
                <Icon name={check.level === "ok" ? "checkCircle" : "alert"} size={17} />
              </span>
              <span>
                {t(`admin.system.checks.${check.id}.${check.level}`, {
                  value: typeof check.value === "object" ? "" : check.value,
                })}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className="system-grid">
        <section className="card card--pad rise">
          <div className="card-head">
            <h2>{t("admin.system.server")}</h2>
            <Icon name="server" size={17} />
          </div>
          <dl className="spec-list">
            <div><dt>{t("admin.system.version")}</dt><dd className="mono">{data.version}</dd></div>
            <div><dt>{t("admin.system.address")}</dt><dd className="mono">{data.host}:{data.port}</dd></div>
            <div><dt>{t("admin.system.uptime")}</dt><dd>{duration(data.uptime_seconds)}</dd></div>
            <div><dt>{t("admin.system.started")}</dt><dd>{stamp(data.started_at, locale)}</dd></div>
            <div><dt>{t("admin.system.secureCookies")}</dt><dd>{onOff(data.secure_cookies)}</dd></div>
            <div><dt>{t("admin.system.trustProxy")}</dt><dd>{onOff(data.trust_proxy)}</dd></div>
            <div><dt>{t("admin.system.python")}</dt><dd className="mono">{data.python}</dd></div>
            <div><dt>{t("admin.system.platform")}</dt><dd className="tiny">{data.platform}</dd></div>
          </dl>
        </section>

        <section className="card card--pad rise">
          <div className="card-head">
            <h2>{t("admin.system.model")}</h2>
            <Icon name="layers" size={17} />
          </div>
          <dl className="spec-list">
            <div><dt>{t("admin.system.run")}</dt><dd className="mono" title={data.model.run}>{data.model.run ? runName(data.model.run) : "—"}</dd></div>
            <div><dt>{t("admin.system.epoch")}</dt><dd>{data.model.epoch ?? "—"}</dd></div>
            <div><dt>{t("admin.system.architecture")}</dt><dd className="mono">{data.model.architecture ?? "—"}</dd></div>
            <div>
              <dt>{t("admin.system.conformal")}</dt>
              <dd>
                <span className={`badge ${data.model.conformal === "loaded" ? "badge--ok" : "badge--warn"}`}>
                  {t(`admin.system.conformalState.${data.model.conformal}`)}
                </span>
              </dd>
            </div>
            <div><dt>{t("admin.system.alpha")}</dt><dd className="num">{data.model.alpha ?? "—"}</dd></div>
          </dl>
        </section>

        <section className="card card--pad rise">
          <div className="card-head">
            <h2>{t("admin.system.storage")}</h2>
            <Icon name="database" size={17} />
          </div>
          <ul className="storage">
            {storage.map(([key, icon, info]) => (
              <li key={key}>
                <span className="storage__icon" aria-hidden="true"><Icon name={icon} size={16} /></span>
                <div className="storage__text">
                  <b>{t(`admin.system.${key}`)}</b>
                  <span className="mono tiny muted" title={info.path}>{info.path}</span>
                </div>
                <span className="storage__size">
                  {info.exists ? bytes(info.bytes) : t("admin.system.notCreated")}
                  {typeof info.entries === "number" && info.exists ? (
                    <span className="tiny muted">{t("admin.system.entries", { n: info.entries })}</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card card--pad rise">
          <div className="card-head">
            <div>
              <h2>{t("admin.system.exports")}</h2>
              <p className="sub">{t("admin.system.exportsSub")}</p>
            </div>
            <Icon name="download" size={17} />
          </div>
          <div className="export-grid">
            {[
              ["users", "users", "CSV"],
              ["audit", "activity", "CSV"],
              ["reviews", "clipboard", "JSONL"],
              ["annotations", "pen", "JSONL"],
            ].map(([name, icon, format]) => (
              <button key={name} type="button" className="export-tile" onClick={() => download(name)}>
                <Icon name={icon} size={18} />
                <span>{t(`admin.system.export${name[0].toUpperCase()}${name.slice(1)}`)}</span>
                <span className="export-tile__fmt">{format}</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
