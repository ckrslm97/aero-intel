"use client";

import { Search as SearchIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { DataSourceError } from "@/components/data-source-error";
import { CategoryChipRow } from "@/components/filters/category-chip-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  readEnum,
  readOptionalEnum,
  useUrlState,
  writeParam,
} from "@/hooks/use-url-state";
import { apiFetch } from "@/lib/api";
import { WINDOW_OPTIONS } from "@/lib/gazete";
import { NEWSPAPER_CATEGORY_SLUGS } from "@/lib/taxonomy";
import type { ArticleListOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Search's own window rungs.
 *
 * `hours` means nothing here -- /search filters on days only, because the
 * index is the archive rather than a live wire and "matches from the last six
 * hours" is a question nobody brings to a search box. The two hour rungs of
 * the Gazete's row are therefore dropped rather than translated into
 * fractional days, and "Tümü" is added, which the paper deliberately has no
 * equivalent of: the paper is a window onto current news, the archive is not.
 */
const SEARCH_WINDOWS = [
  { id: "all", label: "Tümü", days: null as number | null },
  ...WINDOW_OPTIONS.filter((option) => option.days).map((option) => ({
    id: option.id,
    label: option.label,
    days: option.days ?? null,
  })),
];

const SEARCH_WINDOW_IDS = SEARCH_WINDOWS.map((option) => option.id);
/** "Tümü" -- the archive's whole span, and the id an absent `?window=` means. */
const DEFAULT_SEARCH_WINDOW = "all";

/**
 * ARA -- full-text search over every verified article.
 *
 * THE QUERY AND BOTH FILTERS ARE URL-OWNED. `?q=` already arrived through the
 * URL, but only inbound: typing in the box and pressing Ara changed the
 * results and left the address bar saying whatever it had said before, so the
 * one thing on this page anyone would ever want to send -- "search for this,
 * in this beat, over this window" -- was the one thing that could not be sent.
 * `?category` and `?window` join it for the same reason: they change the
 * answer, so they belong in the address of the answer.
 *
 * The URL is also the trigger. There is no separate "run the search" path any
 * more: submitting the form or pressing a filter chip writes the URL, and the
 * effect below fetches whatever the URL now says. One writer, one reader, and
 * no way for the box, the chips and the result list to hold three different
 * opinions about what was searched for.
 */
export function SearchClient() {
  const { params, replaceParams } = useUrlState();

  const submitted = params.get("q")?.trim() ?? "";
  const category = readOptionalEnum(params, "category", NEWSPAPER_CATEGORY_SLUGS);
  const windowId = readEnum(
    params,
    "window",
    SEARCH_WINDOW_IDS,
    DEFAULT_SEARCH_WINDOW,
  );

  /** What is in the box. Free to diverge from the URL while the reader types --
   * the results below describe `submitted`, not this -- but not free to keep
   * describing a query the URL has left behind.
   *
   * Seeding at mount alone was not enough once the URL became the trigger. The
   * header QuickSearch (components/layout/quick-search.tsx) is in the Topbar on
   * every route, /search included, and pressing enter there does
   * router.push("/search?q=..."). On this route that is a re-render, not a
   * remount: the results and the "N sonuç" line moved to the new query while
   * the box still showed the old one, and pressing "Ara" without editing then
   * searched the old query again. So the box follows the URL whenever the URL
   * moves on its own, and only then -- `lastSubmitted` is what makes typing
   * still survive its own re-renders. */
  const [draft, setDraft] = useState(submitted);
  const [lastSubmitted, setLastSubmitted] = useState(submitted);
  if (submitted !== lastSubmitted) {
    setLastSubmitted(submitted);
    setDraft(submitted);
  }
  /** One settled search, tagged with the REQUEST it answers.
   *
   * Tagged rather than bare, because the answers do not arrive in the order
   * the questions were asked. Pressing three window chips in a second fires
   * three requests, and the reply to "son 7 gün" landing after the reply to
   * "tümü" left the lit chip labelling another query's list -- and the "N
   * sonuç" line counting it. The tag makes that unrepresentable: the render
   * reads this record only while its `path` is still the path the current URL
   * asks for, the same `sameSelection` gate `useDataSource` applies to `deps`.
   *
   * `failed` is carried instead of a separate error slot so an error can never
   * coexist with a list on screen: a failed request has `data: null`, so the
   * previous query's articles cannot sit under an error banner looking like a
   * narrower result set. */
  const [answer, setAnswer] = useState<{
    path: string;
    query: string;
    data: ArticleListOut | null;
    failed: boolean;
  } | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  /** The generation of the newest request; a reply from an older one applies
   * nothing. Belt to the AbortController's braces -- abort races the promise
   * callback it is meant to stop, and a cached response can resolve before the
   * signal is read at all. */
  const requestId = useRef(0);

  const setSearchState = useCallback(
    (next: { q?: string; category?: string | null; window?: string }) => {
      const updated = new URLSearchParams(params.toString());
      if (next.q !== undefined) writeParam(updated, "q", next.q.trim() || null);
      if (next.category !== undefined) writeParam(updated, "category", next.category);
      if (next.window !== undefined) {
        writeParam(
          updated,
          "window",
          next.window === DEFAULT_SEARCH_WINDOW ? null : next.window,
        );
      }
      replaceParams(updated);
    },
    [params, replaceParams],
  );

  const days = useMemo(
    () => SEARCH_WINDOWS.find((option) => option.id === windowId)?.days ?? null,
    [windowId],
  );

  /** The request the current URL asks for, or null when there is nothing to
   * search for yet. */
  const requestPath = useMemo(() => {
    if (!submitted) return null;
    const query = new URLSearchParams({ q: submitted });
    if (category) query.set("category", category);
    if (days) query.set("days", String(days));
    return `/search?${query.toString()}`;
  }, [submitted, category, days]);

  useEffect(() => {
    // An empty ?q= has nothing to ask for. The previous answer is left in
    // state untouched and simply not rendered -- `current` below drops it the
    // moment its `path` stops matching, so no state write is needed to stop
    // describing a query the URL has left behind.
    if (!requestPath) return;
    const id = (requestId.current += 1);
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the fetch is driven by the URL; the in-flight flag must flip with it
    setInFlight(true);
    apiFetch<ArticleListOut>(requestPath, { signal: controller.signal })
      .then((data) => {
        if (id !== requestId.current) return;
        setAnswer({ path: requestPath, query: submitted, data, failed: false });
      })
      .catch((err: unknown) => {
        if (id !== requestId.current || (err as Error)?.name === "AbortError") return;
        setAnswer({ path: requestPath, query: submitted, data: null, failed: true });
      })
      .finally(() => {
        if (id === requestId.current) setInFlight(false);
      });
    return () => {
      controller.abort();
    };
  }, [requestPath, submitted, retryToken]);

  /** The answer to the question the URL is asking, or null while none exists.
   * Everything below reads this and never `answer` directly. */
  const current = answer && answer.path === requestPath ? answer : null;
  /** A request for THIS question is running, or the URL just changed and the
   * effect has not fired yet. Without the second half, the frame between a
   * chip press and the effect would render "Sonuç bulunamadı". */
  const loading = requestPath !== null && (inFlight || current === null);
  const results = current?.data ?? null;
  /** The query the list on screen actually answers. */
  const searchedFor = current?.query ?? null;

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSearchState({ q: draft });
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Havayolu, havalimanı, rota, haber ara…"
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={loading}>
          {loading ? "Aranıyor…" : "Ara"}
        </Button>
      </form>

      <div className="flex flex-col gap-2">
        <CategoryChipRow
          value={category}
          onChange={(next) => setSearchState({ category: next })}
          slugs={NEWSPAPER_CATEGORY_SLUGS}
          layoutId="searchCategoryPill"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Zaman
          </span>
          {SEARCH_WINDOWS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setSearchState({ window: option.id })}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs font-medium tabular-nums transition-colors",
                windowId === option.id
                  ? "bg-primary text-primary-foreground"
                  : "border border-border text-muted-foreground hover:bg-accent",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {/* THE THREE BRANCHES, and nothing between them. The count line, the
          list and the "Sonuç bulunamadı" panel are all gated on a settled
          answer to the CURRENT question, so a search that failed can no longer
          leave the previous query's articles on screen looking like a
          narrower result set with a warning above them. */}
      {/* `!current`: a retry of a failed search keeps the error block on
          screen with its button reading "Deneniyor…", rather than stacking a
          skeleton underneath it. The skeleton means "nothing settled for this
          question yet", which is exactly `current === null`. */}
      {loading && !current && (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex flex-col gap-2 p-4">
              <Skeleton className="h-4 w-24 rounded-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-full" />
            </div>
          ))}
        </div>
      )}

      {current?.failed && (
        <DataSourceError
          onRetry={() => setRetryToken((token) => token + 1)}
          lastUpdated={null}
          pending={inFlight}
        />
      )}

      {searchedFor && results && (
        <p className="text-sm text-muted-foreground">
          {/* A real count now: this used to be the page size, so any search
              with more hits than the limit reported exactly the limit. */}
          &ldquo;{searchedFor}&rdquo; için{" "}
          <span className="tabular-nums">{results.total ?? 0}</span> sonuç
          {results.items.length < (results.total ?? 0) && (
            <span> — ilk {results.items.length} tanesi gösteriliyor</span>
          )}
        </p>
      )}

      {results && results.items.length > 0 && (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {results.items.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}

      {results?.items.length === 0 && (
        <div className="rounded-lg border border-dashed border-border p-10 text-center">
          <p className="text-sm font-medium text-foreground">Sonuç bulunamadı</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {/* Said plainly, because it is the single most likely reason a
                Turkish search comes back empty: the index stores Turkish words
                as written and does not stem them. */}
            Türkçe arama, kelimeleri ekleriyle değil yazıldığı gibi eşleştirir —
            &ldquo;yakıt&rdquo; yerine &ldquo;yakıtın&rdquo; aramak sonuç vermeyebilir.
            Filtreleri gevşetmeyi ya da kelimenin yalın hâlini denemeyi deneyin.
          </p>
        </div>
      )}
    </div>
  );
}
