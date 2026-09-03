"use client";

import { Search as SearchIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { CategoryChipRow } from "@/components/filters/category-chip-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  const [results, setResults] = useState<ArticleListOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** The query the results on screen actually answer. */
  const [searchedFor, setSearchedFor] = useState<string | null>(null);

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
    // state untouched and simply not rendered (every result block below is
    // gated on `submitted`) -- clearing it here would be a setState in an
    // effect body to produce something the render can already derive.
    if (!requestPath) return;
    let cancelled = false;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the fetch is driven by the URL; the loading flag must flip with it
    setLoading(true);
    setError(null);
    apiFetch<ArticleListOut>(requestPath, { signal: controller.signal })
      .then((data) => {
        if (cancelled) return;
        setResults(data);
        setSearchedFor(submitted);
      })
      .catch((err: unknown) => {
        if (cancelled || (err as Error)?.name === "AbortError") return;
        setError("Arama şu anda kullanılamıyor. Sunucu çalışıyor mu?");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [requestPath, submitted]);

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

      {error && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      )}

      {submitted && searchedFor && !error && (
        <p className="text-sm text-muted-foreground">
          {/* A real count now: this used to be the page size, so any search
              with more hits than the limit reported exactly the limit. */}
          &ldquo;{searchedFor}&rdquo; için{" "}
          <span className="tabular-nums">{results?.total ?? 0}</span> sonuç
          {results && results.items.length < (results.total ?? 0) && (
            <span> — ilk {results.items.length} tanesi gösteriliyor</span>
          )}
        </p>
      )}

      {submitted && results && results.items.length > 0 && (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {results.items.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}

      {submitted && searchedFor && !error && !loading && results?.items.length === 0 && (
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
