"use client";

import { Search as SearchIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { ArticleCard } from "@/components/article-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import type { ArticleListOut } from "@/lib/types";

export function SearchClient({ initialQuery }: { initialQuery: string }) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<ArticleListOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchedFor, setSearchedFor] = useState<string | null>(null);

  async function runSearch(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<ArticleListOut>(`/search?q=${encodeURIComponent(trimmed)}`);
      setResults(data);
      setSearchedFor(trimmed);
    } catch {
      setError("Search is unavailable right now. Is the backend running?");
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
            placeholder="Search airlines, airports, routes, news…"
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={loading}>
          {loading ? "Searching…" : "Search"}
        </Button>
      </form>

      {error && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      )}

      {searchedFor && !error && (
        <p className="text-sm text-muted-foreground">
          {results?.total ?? 0} result{results?.total === 1 ? "" : "s"} for &ldquo;{searchedFor}
          &rdquo;
        </p>
      )}

      {results && results.items.length > 0 && (
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {results.items.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}
    </div>
  );
}
