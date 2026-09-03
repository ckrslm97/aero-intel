import { useCallback, useEffect, useRef, useState } from "react";

interface DataSourceState<T> {
  /** The result of the CURRENT selection, or null when this selection has no
   * result yet. A dependency change blanks it in the same render the caller
   * changed the dependency in -- see `sameSelection` below for why. */
  data: T | null;
  /** The last attempt's failure message for the CURRENT selection, or null.
   *
   * IT CAN BE SET WHILE `data` IS ALSO SET, and callers get this wrong in the
   * one direction that hurts. A failed refresh that still has a previous
   * successful result FOR THE SAME SELECTION keeps showing that result rather
   * than clearing it -- a source going down should thin the page's
   * information, never blank it -- and that combination is exactly what
   * `stale` reports. So `if (error) return <DataSourceError/>` would erase
   * good data on screen because a refresh failed. The full-error branch is
   * `error && !data`; the stale branch is `stale`. */
  error: string | null;
  /** Nothing to draw yet for this selection, and a request is on its way:
   * the skeleton branch. Distinct from `pending`, which stays true through a
   * refresh that still has data on screen. */
  loading: boolean;
  /** True once a request FOR THIS SELECTION has completed (success or
   * failure) -- distinct from `data !== null`, since a first load has no
   * prior data to be stale relative to, and distinct from "some request has
   * completed", since the last one may have answered a different question. */
  loaded: boolean;
  /** A request for this selection is in flight, or is about to be because the
   * dependencies just changed. True through an in-place refresh, when data is
   * still on screen -- the caller dims it (the `opacity-60` pattern in
   * recommendations-client.tsx) or disables its retry button rather than
   * letting a pending request look like a finished one. */
  pending: boolean;
  /** What the card prints as "son güncelleme".
   *
   * The SERVER's `generated_at` when the payload carries one -- the instant it
   * cut the window it answered with. Only when a payload has no stamp does
   * this fall back to the moment this fetch resolved, which is a fact about
   * the browser and not about the data: it reads "now" on a response served
   * from cache, moves on every reload, and keeps climbing over numbers whose
   * cron stopped days ago. Null before this selection's first request ever
   * completes -- the previous selection's success is not this one's.
   * Faz 12: "her kartta son güncelleme". */
  lastUpdated: Date | null;
  /** True when the last fetch attempt failed but an earlier result FOR THE
   * SAME SELECTION is still being shown. Never true across a dependency
   * change: data fetched for another question is not stale, it is wrong. */
  stale: boolean;
  retry: () => void;
}

/** One settled request, tagged with the selection that asked for it.
 *
 * The tag is the whole point. Without it the hook kept `data` across a
 * dependency change, so a reader switching 5 days to 90 days saw the 5-day
 * counters under a lit "90g" chip, and a failed 90-day request handed those
 * 5-day numbers a "son başarılı güncelleme" stamp -- a StaleDataBanner
 * vouching for the answer to a question nobody asked. */
interface Settled<T> {
  deps: React.DependencyList;
  data: T | null;
  error: string | null;
  lastUpdated: Date | null;
}

/** React's own dependency comparison, applied at render time.
 *
 * `Object.is` per element, exactly like the effect's dependency check, so the
 * data a caller sees and the request the effect fires can never disagree about
 * what counts as a new selection. Render-time rather than in an effect because
 * an effect runs a frame too late: for that one frame the caller would print
 * the old selection's numbers under the new selection's heading, which is the
 * failure this comparison exists to prevent. */
function sameSelection(a: React.DependencyList, b: React.DependencyList): boolean {
  return a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
}

/** The response's own stamp, when it has one.
 *
 * Aggregate endpoints return `generated_at` (backend/app/api/window.py); older
 * ones return bare lists. An unparseable or absent stamp falls back to the
 * fetch time rather than to nothing, because a card with no timestamp at all
 * is worse than one whose timestamp is honestly the client's -- but the
 * server's answer wins wherever there is one. */
function stampOf(result: unknown): Date {
  if (result && typeof result === "object" && "generated_at" in result) {
    const raw = (result as { generated_at?: unknown }).generated_at;
    if (typeof raw === "string") {
      const at = new Date(raw);
      if (!Number.isNaN(at.getTime())) return at;
    }
  }
  return new Date();
}

/** Faz 12's per-source graceful-degradation contract in one hook: loading /
 * error / stale-but-showing-old-data / fresh, plus a retry that re-runs the
 * same fetcher. `fetcher` is called once on mount and again whenever `deps`
 * changes or `retry()` is called; a run superseded by a newer one (deps
 * changed again, or unmount) never applies its result -- the classic
 * fetch-race guard, just centralised instead of hand-rolled per component.
 *
 * EVERY FIELD BELONGS TO THE CURRENT `deps`, and to nothing else. `deps` is
 * not only a re-fetch trigger, it is the identity of the question being
 * asked: the moment it changes, the previous answer stops being an answer.
 * The reader is shown a loading state rather than another selection's
 * numbers, and `retry` re-asks the current question, never the old one. */
export function useDataSource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList,
): DataSourceState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [inFlight, setInFlight] = useState(true);
  const [retryToken, setRetryToken] = useState(0);
  // Refs may not be written during render -- kept current via its own effect
  // instead, which (same commit, declared first) always runs before the
  // fetch effect below reads it, without making fetcher identity itself a
  // re-fetch trigger.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const retry = useCallback(() => setRetryToken((t) => t + 1), []);

  useEffect(() => {
    // The selection this run answers, captured from the render that scheduled
    // it, so its result can be tagged with the question it was asked.
    const selection = deps;
    let cancelled = false;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by deps/retry change; must flip synchronously with the dependency change
    setInFlight(true);

    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (cancelled) return;
        setSettled({
          deps: selection,
          data: result,
          error: null,
          lastUpdated: stampOf(result),
        });
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        const message = err instanceof Error ? err.message : "Bilinmeyen hata";
        // A failed REFRESH keeps what it was refreshing; a failed first load
        // for this selection has nothing to keep. Reaching back into another
        // selection's data here is what produced the wrong-window banner.
        setSettled((prev) =>
          prev && sameSelection(prev.deps, selection)
            ? { ...prev, error: message }
            : { deps: selection, data: null, error: message, lastUpdated: null },
        );
      })
      .finally(() => {
        if (cancelled) return;
        setInFlight(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps is the caller's own dependency list, forwarded as-is
  }, [...deps, retryToken]);

  // The gate: a settled result is only readable while it still answers the
  // question being asked. Between a dependency change and the effect that
  // follows it, `inFlight` is still false -- so `pending` reads the selection
  // itself, and a caller never sees "nothing here, and nothing coming" for a
  // request that is one tick from being fired.
  const current = settled && sameSelection(settled.deps, deps) ? settled : null;
  const data = current?.data ?? null;
  const pending = inFlight || current === null;

  return {
    data,
    error: current?.error ?? null,
    loading: pending && data === null,
    loaded: current !== null,
    pending,
    lastUpdated: current?.lastUpdated ?? null,
    stale: current !== null && current.error !== null && current.data !== null,
    retry,
  };
}
