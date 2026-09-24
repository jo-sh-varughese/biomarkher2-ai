/* Shared application state: the server context (classes, samples, caveats,
   provenance), the analysis currently on screen, and the review history.

   Analysis lives here rather than inside the Analysis page so that navigating
   to Cases and back does not throw away a field the pathologist is part-way
   through reviewing. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchContext, loadReviews, rememberReview } from "../lib/api.js";

const PortalContext = createContext(null);

export function PortalProvider({ children }) {
  const [context, setContext] = useState(null);
  const [contextError, setContextError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [analysis, setAnalysis] = useState(null);
  const [lastRequest, setLastRequest] = useState(null);
  const [reviews, setReviews] = useState(() => loadReviews());

  const reload = useCallback(async () => {
    setLoading(true);
    setContextError(null);
    try {
      setContext(await fetchContext());
    } catch (err) {
      setContextError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const recordReview = useCallback((entry) => {
    const stored = { id: `r-${Date.now()}`, at: new Date().toISOString(), ...entry };
    rememberReview(stored);
    setReviews((list) => [stored, ...list]);
    return stored;
  }, []);

  const value = useMemo(
    () => ({
      context,
      contextError,
      loading,
      reload,
      analysis,
      setAnalysis,
      lastRequest,
      setLastRequest,
      reviews,
      recordReview,
      // A single flag for "nothing real is behind this screen", true when the
      // context or the analysis on screen came from the demo module.
      isDemo: Boolean(context?.demo || analysis?.demo),
    }),
    [context, contextError, loading, reload, analysis, lastRequest, reviews, recordReview],
  );

  return <PortalContext.Provider value={value}>{children}</PortalContext.Provider>;
}

export function usePortal() {
  const ctx = useContext(PortalContext);
  if (!ctx) throw new Error("usePortal must be used inside <PortalProvider>");
  return ctx;
}
