/* ============================================================================
   Language.

   English and Malayalam, chosen by the user and remembered. The choice is
   stamped on <html lang> as well as stored, because that attribute is what
   tells the browser which font to reach for, how to hyphenate, and what to
   announce to a screen reader -- getting the strings right and leaving the
   attribute saying "en" would leave a screen reader reading Malayalam with
   English phonetics.
   ==========================================================================*/

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { STRINGS } from "./strings.js";

const KEY = "bmh2.lang.v1";
export const LANGS = [
  { id: "en", label: "English", short: "EN" },
  { id: "ml", label: "മലയാളം", short: "മല" },
];

const I18nContext = createContext(null);

function readStored() {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "en" || stored === "ml" ? stored : null;
  } catch {
    return null;
  }
}

/** Walks "a.b.c" through a nested object. */
function lookup(tree, path) {
  return path.split(".").reduce((node, key) => (node == null ? undefined : node[key]), tree);
}

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => readStored() ?? "en");

  useEffect(() => {
    document.documentElement.setAttribute("lang", lang);
    try {
      localStorage.setItem(KEY, lang);
    } catch {
      /* Blocked site data just means the choice does not survive a reload. */
    }
  }, [lang]);

  const t = useCallback(
    (path, vars) => {
      // Fall back to English rather than rendering a raw key: a missing
      // Malayalam string should degrade to a readable word, not to
      // "analysis.rail.heading" in the middle of a clinical screen.
      const value = lookup(STRINGS[lang], path) ?? lookup(STRINGS.en, path);
      if (value == null) {
        if (import.meta.env.DEV) console.warn(`[i18n] missing string: ${path}`);
        return path;
      }
      if (!vars) return value;
      return String(value).replace(/\{(\w+)\}/g, (whole, name) =>
        name in vars ? String(vars[name]) : whole,
      );
    },
    [lang],
  );

  /* Dates and numbers follow the language too. ml-IN formats with Latin
     digits, which is what Kerala clinical practice actually uses -- Malayalam
     numerals would look archaic on a lab report. */
  const locale = lang === "ml" ? "ml-IN" : undefined;

  const value = useMemo(
    () => ({ lang, setLang, t, locale, isMalayalam: lang === "ml" }),
    [lang, t, locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}

/** Shorthand for components that only need the lookup function. */
export function useT() {
  return useI18n().t;
}
