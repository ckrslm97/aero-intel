"use client";

import { Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { getCategory } from "@/lib/taxonomy";
import type { ArticleListOut } from "@/lib/types";

const DEBOUNCE_MS = 250;
const PREVIEW_LIMIT = 6;

export function QuickSearch() {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ArticleListOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  // Debounced live search as the user types. When the query is empty there's
  // nothing to fetch -- the dropdown is already hidden in that case (see
  // showDropdown below), so stale results/loading state simply never renders.
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect -- debounced data fetch driven by `query`; loading must flip synchronously with the dependency change
    setLoading(true);
    const timer = setTimeout(() => {
      apiFetch<ArticleListOut>(`/search?q=${encodeURIComponent(trimmed)}&limit=${PREVIEW_LIMIT}`)
        .then((data) => setResults(data))
        .catch(() => setResults(null))
        .finally(() => setLoading(false));
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [query]);

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
    if (query.trim()) {
      setOpen(false);
      router.push(`/search?q=${encodeURIComponent(query.trim())}`);
    }
  }

  const showDropdown = open && query.trim().length > 0;

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
          {results && results.items.length > 0 ? (
            <>
              <ul className="flex max-h-96 flex-col divide-y divide-border overflow-y-auto">
                {results.items.map((article) => {
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
                &ldquo;{query.trim()}&rdquo; için tüm sonuçları gör
              </button>
            </>
          ) : (
            !loading && (
              <p className="px-3 py-4 text-sm text-muted-foreground">
                &ldquo;{query.trim()}&rdquo; için henüz sonuç yok.
              </p>
            )
          )}
        </div>
      )}
    </div>
  );
}
