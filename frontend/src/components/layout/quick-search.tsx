"use client";

import { Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { InlineSourceError } from "@/components/data-source-error";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { getCategory } from "@/lib/taxonomy";
import type { ArticleListOut } from "@/lib/types";

const DEBOUNCE_MS = 250;
const PREVIEW_LIMIT = 6;

/** One settled preview, tagged with the query it answers.
 *
 * The tag is the fix. State held as a bare `results` belongs to whichever
 * response landed last, and responses do not land in the order they were
 * sent: typing "ist" fires three requests and the reply to "is" can arrive
 * after the reply to "ist", so the dropdown headed by the box's current text
 * listed another query's articles. Tagging makes that unrepresentable --
 * render reads the record only while its `query` is still the query being
 * asked (`current` below), exactly the `sameSelection` gate `useDataSource`
 * applies to its `deps`. */
interface Answer {
  query: string;
  /** Null when the request for THIS query failed. */
  items: ArticleListOut | null;
  failed: boolean;
}

export function QuickSearch() {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [open, setOpen] = useState(false);

  /** The generation of the newest request. A reply whose id is not this one
   * has been superseded and applies nothing -- the belt to the AbortController's
   * braces, because an abort races the promise callback it is meant to stop and
   * a cached response can resolve before the signal is ever read. */
  const requestId = useRef(0);

  const trimmed = query.trim();

  // Debounced live search as the user types. An empty box asks nothing: the
  // effect returns before setting anything in motion, and because `loading`
  // and `current` below are both gated on `trimmed`, clearing the box empties
  // the dropdown and stops the spinner without a single state write. That
  // spinner used to run forever -- `setLoading(true)` fired on every keystroke
  // including the one that emptied the box, and the early return then skipped
  // the `finally` that was the only thing that ever turned it off.
  useEffect(() => {
    const asked = query.trim();
    if (!asked) return;

    const id = (requestId.current += 1);
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- debounced data fetch driven by `query`; the in-flight flag must flip with the dependency change
    setInFlight(true);
    const timer = setTimeout(() => {
      apiFetch<ArticleListOut>(
        `/search?q=${encodeURIComponent(asked)}&limit=${PREVIEW_LIMIT}`,
        { signal: controller.signal },
      )
        .then((data) => {
          if (id !== requestId.current) return;
          setAnswer({ query: asked, items: data, failed: false });
        })
        .catch((error: unknown) => {
          if (id !== requestId.current || (error as Error)?.name === "AbortError") return;
          // A failed search is NOT an empty search. This used to be
          // `setResults(null)`, which the dropdown then drew as
          // "…için henüz sonuç yok" -- an outage reported to the reader as a
          // fact about the archive.
          setAnswer({ query: asked, items: null, failed: true });
        })
        .finally(() => {
          if (id === requestId.current) setInFlight(false);
        });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, retryToken]);

  // Close the dropdown on outside click.
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function goToFullResults() {
    if (trimmed) {
      setOpen(false);
      router.push(`/search?q=${encodeURIComponent(trimmed)}`);
    }
  }

  /** The answer to the question currently in the box, or null when there is
   * none yet. Read at render time so the heading and the list can never
   * describe two different queries for even one frame. */
  const current = answer && answer.query === trimmed ? answer : null;
  /** A request for THIS query is running, or is one debounce away from it. */
  const loading = trimmed.length > 0 && (inFlight || current === null);
  const showDropdown = open && trimmed.length > 0;

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          goToFullResults();
        }}
      >
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          placeholder="Havayolu, havalimanı, rota, haber ara…"
          className="pl-9"
        />
        {loading && (
          <Loader2 className="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        )}
      </form>

      {showDropdown && (
        <div className="absolute left-0 right-0 top-full z-40 mt-2 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
          {/* The three branches, in the order they can occur. Nothing renders
              a list, a count or an "yok" until a request for THIS query has
              settled -- an old query's articles under a new query's heading is
              the failure this dropdown is being fixed for. */}
          {current === null ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">Aranıyor…</p>
          ) : current.failed ? (
            <InlineSourceError
              message="Arama sonuçları okunamadı."
              onRetry={() => setRetryToken((token) => token + 1)}
              pending={inFlight}
              className="px-3 py-4"
            />
          ) : current.items && current.items.items.length > 0 ? (
            <>
              <ul className="flex max-h-96 flex-col divide-y divide-border overflow-y-auto">
                {current.items.items.map((article) => {
                  const category = article.enrichment ? getCategory(article.enrichment.category) : null;
                  const headline =
                    (article.enrichment?.is_translated && article.enrichment.headline_tr) ||
                    article.enrichment?.headline ||
                    article.title;
                  return (
                    <li key={article.id}>
                      <a
                        href={article.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex flex-col gap-0.5 px-3 py-2 hover:bg-accent"
                      >
                        <span className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                          {article.source.name}
                          {category && <span className={category.textClass}> · {category.label}</span>}
                          <span className="ml-auto normal-case">{article.reading_time_minutes} dk okuma</span>
                        </span>
                        <span className="truncate text-sm font-medium text-popover-foreground">
                          {headline}
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
              <button
                onClick={goToFullResults}
                className="w-full border-t border-border px-3 py-2 text-left text-xs font-medium text-primary hover:bg-accent"
              >
                &ldquo;{trimmed}&rdquo; için tüm sonuçları gör
              </button>
            </>
          ) : (
            <p className="px-3 py-4 text-sm text-muted-foreground">
              &ldquo;{trimmed}&rdquo; için henüz sonuç yok.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
