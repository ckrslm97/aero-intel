"use client";

import { Search as SearchIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { CategoryChipRow } from "@/components/filters/category-chip-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

export function SearchClient({ initialQuery }: { initialQuery: string }) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<ArticleListOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchedFor, setSearchedFor] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [windowId, setWindowId] = useState<string>("all");

  async function runSearch(q: string, filters?: { category?: string | null; windowId?: string }) {
    const trimmed = q.trim();
    if (!trimmed) return;

    const activeCategory = filters?.category !== undefined ? filters.category : category;
    const activeWindowId = filters?.windowId ?? windowId;
    const days = SEARCH_WINDOWS.find((w) => w.id === activeWindowId)?.days ?? null;

    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ q: trimmed });
      if (activeCategory) params.set("category", activeCategory);
      if (days) params.set("days", String(days));
      const data = await apiFetch<ArticleListOut>(`/search?${params.toString()}`);
      setResults(data);
      setSearchedFor(trimmed);
    } catch {
      setError("Arama şu anda kullanılamıyor. Sunucu çalışıyor mu?");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (initialQuery.trim()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount from the initial ?q= prop
      void runSearch(initialQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** A filter press re-runs the search immediately rather than waiting for the
   * reader to press "Ara" again -- the query has not changed, only the shape
   * of the answer, and a filter row that needs a second click to apply reads
   * as broken. The new value is passed explicitly because the state setter
   * has not landed yet at call time. */
  function applyCategory(next: string | null) {
    setCategory(next);
    if (searchedFor) void runSearch(searchedFor, { category: next });
  }

  function applyWindow(next: string) {
    setWindowId(next);
    if (searchedFor) void runSearch(searchedFor, { windowId: next });
  }

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch(query);
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
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
          onChange={applyCategory}
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
              onClick={() => applyWindow(option.id)}
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

      {searchedFor && !error && (
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

      {results && results.items.length > 0 && (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {results.items.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}

      {searchedFor && !error && !loading && results?.items.length === 0 && (
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
