import { useCallback, useEffect, useRef, useState } from "react";

interface DataSourceState<T> {
  data: T | null;
  /** Set only when there is no usable data at all -- a failed refresh that
   * still has a previous successful result keeps showing that result with
   * `stale: true` rather than clearing it. A source going down should thin
   * the page's information, never blank it. */
  error: string | null;
  loading: boolean;
  /** True once a request has completed (success or failure) -- distinct from
   * `data !== null`, since the very first load has no prior data to be
   * stale relative to. */
  loaded: boolean;
  /** When `data` was last replaced by a successful fetch, or null before the
   * first one ever completes. Faz 12: "her kartta son güncelleme". */
  lastUpdated: Date | null;
  /** True when the last fetch attempt failed but an earlier result is still
   * being shown. */
  stale: boolean;
  retry: () => void;
}

/** Faz 12's per-source graceful-degradation contract in one hook: loading /
 * error / stale-but-showing-old-data / fresh, plus a retry that re-runs the
 * same fetcher. `fetcher` is called once on mount and again whenever `deps`
 * changes or `retry()` is called; a run superseded by a newer one (deps
 * changed again, or unmount) never applies its result -- the classic
 * fetch-race guard, just centralised instead of hand-rolled per component. */
export function useDataSource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList,
): DataSourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
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
    let cancelled = false;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch driven by deps/retry change; must flip synchronously with the dependency change
    setLoading(true);

    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
        setLastUpdated(new Date());
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Bilinmeyen hata");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        setLoaded(true);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps is the caller's own dependency list, forwarded as-is
  }, [...deps, retryToken]);

  return {
    data,
    error,
    loading,
    loaded,
    lastUpdated,
    stale: error !== null && data !== null,
    retry,
  };
}
