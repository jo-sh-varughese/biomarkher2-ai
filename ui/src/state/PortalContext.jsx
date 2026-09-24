/* Shared application state: the server context (classes, samples, caveats,
   provenance), the analysis currently on screen, and the review history.

   Analysis lives here rather than inside the Analysis page so that navigating
   to Cases and back does not throw away a field the pathologist is part-way
   through reviewing. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchContext, fetchReviews, rememberReview } from "../lib/api.js";

const PortalContext = createContext(null);

export function PortalProvider({ children }) {
  const [context, setContext] = useState(null);
  const [contextError, setContextError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [analysis, setAnalysis] = useState(null);
  const [lastRequest, setLastRequest] = useState(null);
  // Starts empty, not seeded: until the log has been read there is nothing
  // true to show, and a flash of demo rows on a live portal is the exact
  // confusion this state exists to prevent.
  const [reviews, setReviews] = useState([]);
  const [reviewsDemo, setReviewsDemo] = useState(false);
  const [reviewsLoaded, setReviewsLoaded] = useState(false);

  const loadReviews = useCallback(async () => {
    try {
      const result = await fetchReviews();
      setReviews(result.reviews);
      setReviewsDemo(result.demo);
    } catch {
      /* A malformed log is surfaced by the server's own error; the pages
         render their empty states rather than a partial history. */
    } finally {
      setReviewsLoaded(true);
    }
  }, []);

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
    loadReviews();
  }, [loadReviews]);

  useEffect(() => {
    reload();
  }, [reload]);

  const recordReview = useCallback(
    (entry) => {
      const stored = { id: `r-${Date.now()}`, at: new Date().toISOString(), ...entry };
      // Live, the server log already holds it (submitReview wrote it); only a
      // demo session needs a local copy to survive a reload.
      if (reviewsDemo) rememberReview(stored);
      setReviews((list) => [stored, ...list]);
      return stored;
    },
    [reviewsDemo],
  );

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
      reviewsDemo,
      reviewsLoaded,
      recordReview,
      // A single flag for "nothing real is behind this screen", true when the
      // context or the analysis on screen came from the demo module.
      isDemo: Boolean(context?.demo || analysis?.demo),
    }),
    [context, contextError, loading, reload, analysis, lastRequest, reviews, reviewsDemo, reviewsLoaded, recordReview],
  );

  return <PortalContext.Provider value={value}>{children}</PortalContext.Provider>;
}

export function usePortal() {
  const ctx = useContext(PortalContext);
  if (!ctx) throw new Error("usePortal must be used inside <PortalProvider>");
  return ctx;
}
