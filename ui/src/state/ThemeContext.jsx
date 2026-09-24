import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const KEY = "bmh2.theme.v1";
const ThemeContext = createContext(null);

function readStored() {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}

export const DEFAULT_THEME = "light";

export function ThemeProvider({ children }) {
  // The portal is light by default and does not follow the operating system:
  // these screens are read next to a microscope and against printed slides,
  // and a pathologist who wants dark can say so once with the toggle. The
  // inline script in index.html applies the same rule before the first paint,
  // so the two must agree -- change them together.
  const [theme, setTheme] = useState(() => readStored() ?? DEFAULT_THEME);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);

    // Mobile browsers tint their own chrome from this, and it cannot be done
    // in CSS -- so the meta tag is kept in step with the toggle here.
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0c0e18" : "#f5f6fb");

    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* Blocked site data just means the choice does not survive a reload. */
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  // `resolved` is now always the same as `theme`; it is kept so callers that
  // ask "which theme is actually showing" keep reading the right thing.
  const value = useMemo(
    () => ({ theme, resolved: theme, setTheme, toggle }),
    [theme, toggle],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
