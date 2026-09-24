import Icon from "./Icon.jsx";
import { classForLabel, isCannotAssess } from "../lib/format.js";

/** A recorded HER2 assessment: its class-colour mark beside the score, or the
    translated "Cannot assess" whatever wording the log stored it in. */
export function ScoreBadge({ score, classes, t }) {
  if (isCannotAssess(score)) return <span className="badge badge--outline">{t("analysis.cannotAssess")}</span>;
  const color = classForLabel(classes, score)?.color;
  return (
    <span className="badge badge--score">
      <i style={{ background: color ?? "var(--accent)" }} />
      {score}
    </span>
  );
}

export function ConcordBadge({ agrees, t }) {
  return agrees ? (
    <span className="badge badge--ok">
      <Icon name="check" size={11} /> {t("common.yes")}
    </span>
  ) : (
    <span className="badge badge--warn">
      <Icon name="alert" size={11} /> {t("table.flagged")}
    </span>
  );
}
