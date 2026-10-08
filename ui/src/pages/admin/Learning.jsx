/* Continual learning, under the administrator's control (app/learning).

   What has been collected (cases analysed, signed reviews by grade, annotated
   tiles), whether there is enough to train, a button to train a candidate
   version, and every version with the evidence its gates were judged on.
   A candidate goes live only when an administrator activates it, and only if
   its gates passed; any earlier version can be re-activated (rollback). */

import { useEffect } from "react";
import Icon from "../../components/Icon.jsx";
import { useToast } from "../../state/ToastContext.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { errorText } from "../../lib/auth.js";
import { LoadError, PageHead, SkeletonRows, stamp, useAdmin, useLoad } from "./shared.jsx";

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const CHECK_KEYS = ["enough_cases", "reference_accuracy_kept", "reference_qwk_kept", "local_accuracy_gain", "local_big_errors_not_worse"];

export default function Learning() {
  const { api } = useAdmin();
  const { t, locale } = useI18n();
  const toast = useToast();
  const { data, error, loading, reload } = useLoad(() => api.learning(), [api]);
  const running = data?.job?.status === "running";

  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(reload, 3000);
    return () => clearInterval(id);
  }, [running, reload]);

  const train = async () => {
    try {
      await api.learningTrain();
      toast.ok(t("learning.trainStarted"));
      reload();
    } catch (err) {
      toast.error(t("learning.failed"), errorText(err, t));
    }
  };
  const act = async (version, action) => {
    if (action === "activate" && !window.confirm(t("learning.confirmActivate", { v: version }))) return;
    try {
      const res = await api.learningVersion(version, action);
      toast.ok(t(action === "activate" ? "learning.activated" : "learning.rejected", { v: version }));
      if (action === "activate" && res?.version?.prediction_sets_stale) toast.error(t("learning.sets.staleAfterActivate", { v: version }));
      reload();
    } catch (err) {
      toast.error(t("learning.failed"), errorText(err, t));
    }
  };

  const recalibrate = async () => {
    try {
      const res = await api.learningRecalibrate();
      toast.ok(t("learning.sets.done", { v: res.calibration.head_version, cases: res.calibration.n_cases }));
      reload();
    } catch (err) {
      toast.error(t("learning.failed"), errorText(err, t));
    }
  };

  if (error) return <LoadError error={error} onRetry={reload} t={t} />;
  if (loading && !data) return <SkeletonRows rows={6} />;
  const d = data.data ?? {};
  const ps = data.prediction_sets ?? {};
  const g = data.gates ?? {};
  const versions = [...(data.registry?.versions ?? [])].reverse();

  return (
    <>
      <PageHead eyebrow={t("learning.eyebrow")} title={t("learning.title")} lede={t("learning.lede")} />

      <section className="card card--pad learn__stats">
        <div><span className="learn__k">{t("learning.active")}</span><b className="learn__v">{data.active_version}</b></div>
        <div><span className="learn__k">{t("learning.stored")}</span><b className="learn__v">{d.stored ?? 0}</b></div>
        <div><span className="learn__k">{t("learning.labelled")}</span><b className="learn__v">{d.labelled ?? 0}</b>
          <span className="tiny muted">{Object.entries(d.by_grade ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</span></div>
        <div><span className="learn__k">{t("learning.tiles")}</span><b className="learn__v">{d.annotated_tiles ?? 0}</b></div>
      </section>

      <section className="card card--pad">
        <div className="card-head">
          <div>
            <h2>{t("learning.trainTitle")}</h2>
            <p className="sub">{t("learning.trainSub", { n: g.min_labelled_cases ?? 40, k: g.min_per_grade ?? 3 })}</p>
          </div>
          <button type="button" className="btn btn--primary" onClick={train}
            disabled={!data.ready_to_train || running} {...(running ? { "data-busy": "" } : {})}>
            <Icon name="refresh" size={16} /> {t("learning.train")}
          </button>
        </div>
        {!data.reference_loaded ? <p className="note note--caveat">{t("learning.noReference")}</p> : null}
        {data.job?.status && data.job.status !== "idle" ? (
          <p className={`hint${data.job.status === "error" ? " review__bad" : ""}`}>
            {t(`learning.job.${data.job.status}`)}
            {data.job.candidate ? ` · ${data.job.candidate}` : ""}
            {data.job.seconds ? ` · ${data.job.seconds}s` : ""}
            {data.job.error ? ` · ${data.job.error}` : ""}
          </p>
        ) : null}
        <ul className="learn__gates">
          <li>{t("learning.gate.reference", { acc: ((g.reference_max_accuracy_drop ?? 0.01) * 100).toFixed(0) })}</li>
          <li>{t("learning.gate.local", { gain: ((g.local_min_accuracy_gain ?? 0.02) * 100).toFixed(0) })}</li>
          <li>{t("learning.gate.big")}</li>
          <li>{t("learning.gate.human")}</li>
        </ul>
      </section>

      <section className="card card--pad">
        <div className="card-head">
          <div>
            <h2>{t("learning.sets.title")}</h2>
            <p className="sub">{t("learning.sets.sub", { n: ps.min_cases ?? 25 })}</p>
          </div>
          <button type="button" className="btn btn--primary" onClick={recalibrate} disabled={(d.labelled ?? 0) < (ps.min_cases ?? 25)}>
            <Icon name="refresh" size={16} /> {t("learning.sets.recalibrate", { v: data.active_version })}
          </button>
        </div>
        <p className={`hint${ps.current ? "" : " review__bad"}`}>
          {ps.current
            ? t("learning.sets.current", { site: ps.calibrated_for_site, v: ps.calibrated_for_version, cases: ps.n_cases })
            : ps.available
              ? t("learning.sets.stale", { reason: ps.reason })
              : t("learning.sets.none", { reason: ps.reason })}
        </p>
      </section>

      <section className="card card--pad">
        <h2 className="learn__h">{t("learning.versions")}</h2>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("learning.col.version")}</th><th>{t("learning.col.status")}</th><th className="num">{t("learning.col.cases")}</th>
                <th className="num">{t("learning.col.local")}</th><th className="num">{t("learning.col.reference")}</th><th>{t("learning.col.gates")}</th><th />
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => {
                const cv = v.local_cv ?? {};
                const ref = v.reference ?? {};
                const checks = v.gates?.checks ?? {};
                return (
                  <tr key={v.version}>
                    <td><b>{v.version}</b><div className="tiny muted">{v.created ? stamp(v.created, locale) : t("learning.shipped")}</div></td>
                    <td><span className={`review__status review__status--${v.status === "active" ? "final" : v.status === "candidate" ? "preliminary" : "draft"}`}>{t(`learning.status.${v.status}`)}</span>
                      {v.activated_by ? <div className="tiny muted">{v.activated_by}</div> : null}</td>
                    <td className="num">{v.data?.labelled ?? "—"}</td>
                    <td className="num">{cv.enough ? `${pct(cv.current?.accuracy)} → ${pct(cv.candidate?.accuracy)}` : "—"}</td>
                    <td className="num">{ref.current ? `${pct(ref.current.accuracy)} → ${pct(ref.candidate.accuracy)}` : "—"}</td>
                    <td>
                      {v.gates ? (
                        <ul className="learn__checks">
                          {CHECK_KEYS.map((k) => (
                            <li key={k} className={checks[k] ? "is-ok" : "is-bad"}>{checks[k] ? "✓" : "✕"} {t(`learning.check.${k}`)}</li>
                          ))}
                        </ul>
                      ) : "—"}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {v.status === "candidate" && v.gates?.passed ? (
                        <button type="button" className="btn btn--primary btn--sm" onClick={() => act(v.version, "activate")}>{t("learning.activate")}</button>
                      ) : null}
                      {v.status === "candidate" ? (
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => act(v.version, "reject")}>{t("learning.reject")}</button>
                      ) : null}
                      {v.status === "retired" && (v.version === "v0" || v.gates?.passed) ? (
                        <button type="button" className="btn btn--sm" onClick={() => act(v.version, "activate")}>{t("learning.rollback")}</button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="hint">{t("learning.note")}</p>
      </section>
    </>
  );
}
