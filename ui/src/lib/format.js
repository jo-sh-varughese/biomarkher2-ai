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
  const entries = Object.entries(percentages).filter(([name]) => name !== "Background");
  if (!entries.length) return null;
  return entries.reduce((best, entry) => (entry[1] > best[1] ? entry : best));
}

/** Colour for a class name, preferring the server's own palette. */
export function classColor(classes, name, fallback = "var(--text-3)") {
  return classes?.find((c) => c.name === name)?.color ?? fallback;
}
