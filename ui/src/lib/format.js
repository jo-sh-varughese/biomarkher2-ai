export const pct = (value, digits = 1) =>
  `${Number(value ?? 0).toFixed(digits)}%`;

export const signed = (value, digits = 2) => {
  const n = Number(value ?? 0);
  // A true minus sign, not a hyphen -- it aligns with tabular figures.
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(digits)}`;
};

export const initials = (name = "") =>
  name
    .replace(/^(Dr|Prof|Mr|Ms|Mrs)\.?\s+/i, "")
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("") || "?";

/* Dates take the active locale. Passing undefined falls back to the browser's
   own, which is what English callers want. */
export const shortDate = (value, locale) =>
  new Date(value).toLocaleDateString(locale, { day: "numeric", month: "short" });

export const dateTime = (value, locale) =>
  new Date(value).toLocaleString(locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

/* Takes the lookup function rather than formatting English and translating
   after: Malayalam does not mark the plural on a counted noun, so the
   one/other split has to live in the string table, not here. */
export function relativeTime(value, t, locale) {
  const then = new Date(value).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  const table = [
    [60, "second", 1],
    [3600, "minute", 60],
    [86400, "hour", 3600],
    [604800, "day", 86400],
  ];
  for (const [limit, unit, divisor] of table) {
    if (seconds < limit) {
      const n = Math.max(1, Math.floor(seconds / divisor));
      const key = n === 1 ? `common.unit.${unit}` : `common.unitPlural.${unit}`;
      return t("common.ago", { n, unit: t(key) });
    }
  }
  return shortDate(value, locale);
}

export const greetingKey = (date = new Date()) => {
  const h = date.getHours();
  if (h < 12) return "common.greeting.morning";
  if (h < 17) return "common.greeting.afternoon";
  return "common.greeting.evening";
};

/** The class with the largest share, ignoring background. */
export function dominantClass(percentages = {}) {
  const entries = Object.entries(percentages).filter(([name]) => name.toLowerCase() !== "background");
  if (!entries.length) return null;
  return entries.reduce((best, entry) => (entry[1] > best[1] ? entry : best));
}

/* The server offers "cannot assess from this field"; older demo data says
   "Cannot assess". Every comparison goes through this so neither wording can
   silently fall out of a count, a filter, or a score picker again. */
export const isCannotAssess = (score = "") => /^cannot assess/i.test(String(score).trim());

/** A sample id like "test/class_2+/her2-2+-score_train_87.png", shortened to
    what fits a table cell. The full id stays available as a tooltip. */
export const shortId = (id = "") => {
  const base = String(id).split(/[\\/]/).pop() || String(id);
  return base.replace(/\.(png|jpe?g|tiff?)$/i, "");
};

/** "artifacts\\phase2_unet" -> "phase2_unet": a run is named by its folder. */
export const runName = (run = "") => String(run).split(/[\\/]/).filter(Boolean).pop() || String(run);

const DAY = 86400000;
const dayKey = (value) => {
  const d = new Date(value);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
};

/** Reviews per calendar day for the last `days` days, oldest first, zero-filled. */
export function dailyCounts(reviews = [], days = 14, now = new Date()) {
  const counts = new Map();
  for (const r of reviews) {
    if (!r.at) continue;
    const key = dayKey(r.at);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Array.from({ length: days }, (_, i) => {
    const day = new Date(today.getTime() - (days - 1 - i) * DAY);
    return { day, count: counts.get(dayKey(day)) || 0 };
  });
}

/** How many reviews fall in the last `days` days, and in the `days` before. */
export function periodCounts(reviews = [], days = 7, now = Date.now()) {
  let current = 0;
  let previous = 0;
  for (const r of reviews) {
    const age = now - new Date(r.at).getTime();
    if (Number.isNaN(age) || age < 0) continue;
    if (age < days * DAY) current += 1;
    else if (age < 2 * days * DAY) previous += 1;
  }
  return { current, previous, delta: current - previous };
}

/** Colour for a class name, preferring the server's own palette. */
export function classColor(classes, name, fallback = "var(--text-3)") {
  return classes?.find((c) => c.name === name)?.color ?? fallback;
}

/* Dataset folder labels ("0", "1+", "2+", "3+") and the server's own class
   names ("negative", "weak (1+)", ...) are two different vocabularies for
   the same four tissue classes -- a folder label's class index is always
   its position here plus 1, since index 0 is background and has no label
   of its own. Kept here, derived from context.classes rather than a
   hardcoded name list, so a wording change server-side cannot silently
   desync the two. */
export const LABEL_ORDER = ["0", "1+", "2+", "3+"];

/** The server's class entry ({index, name, color}) for a dataset folder
    label, or null if `classes` hasn't loaded yet or the label is unknown. */
export function classForLabel(classes, label) {
  const i = LABEL_ORDER.indexOf(label);
  if (i === -1) return null;
  return classes?.find((c) => c.index === i + 1) ?? null;
}

/** The inverse: the short dataset-style label ("2+") for a class name
    ("moderate (2+)"), for display next to a percentage measured by name. */
export function labelForClassName(classes, name) {
  const found = classes?.find((c) => c.name === name);
  return found ? (LABEL_ORDER[found.index - 1] ?? null) : null;
}
