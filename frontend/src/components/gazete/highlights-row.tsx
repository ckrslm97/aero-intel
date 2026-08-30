"use client";

import { Star } from "lucide-react";
import { useEffect, useState } from "react";

import { useArticleDrawer } from "@/components/article-drawer-context";
import { apiFetch } from "@/lib/api";
import { categoryVar, getCategory } from "@/lib/taxonomy";
import type { ArticleListOut, ArticleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How far back "bugünün" reaches. Two days, not one: an aviation wire is
 * quiet overnight and on weekends, and a strictly-today window left the row
 * empty every Sunday morning on a paper that had plenty to show. */
const HIGHLIGHT_HOURS = 48;

/** The importance floor for the row, above the list's own 0.47.
 *
 * The same focus-weighted score the list filters on (see
 * newspaper-browser.tsx MIN_IMPORTANCE for the measured table behind that
 * number), just a rung higher -- this is "of the stories that made the paper,
 * these four first", not a second, unrelated ranking.
 */
const HIGHLIGHT_MIN_IMPORTANCE = 0.75;

const COUNT = 4;

/** "Bugünün Öne Çıkanları".
 *
 * Four larger tiles above the day-grouped list. Deliberately the same
 * ordering the list already uses (the API returns published_at desc under an
 * importance floor) rather than a new score: a row that ranked stories by
 * something the rest of the page does not would be a second editorial opinion
 * nobody could explain.
 *
 * Renders nothing when the window is empty -- a heading over an empty grid is
 * worse than no heading.
 */
export function HighlightsRow({
  category,
  excludedCategories,
}: {
  category: string;
  excludedCategories: readonly string[];
}) {
  const { open } = useArticleDrawer();
  const [items, setItems] = useState<ArticleOut[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      category,
      hours: String(HIGHLIGHT_HOURS),
      limit: String(COUNT),
      translated_only: "true",
      min_importance: String(HIGHLIGHT_MIN_IMPORTANCE),
    });
    excludedCategories.forEach((slug) => params.append("exclude_categories", slug));

    apiFetch<ArticleListOut>(`/articles?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => setItems(data.items))
      .catch(() => {
        /* decorative -- never break the list underneath */
      });
    return () => controller.abort();
  }, [category, excludedCategories]);

  if (items.length === 0) return null;

  return (
    <section aria-label="Bugünün öne çıkanları" className="flex flex-col gap-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        <Star className="size-4 text-signal" aria-hidden />
        Bugünün Öne Çıkanları
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((article) => {
          const enrichment = article.enrichment;
          const categoryDef = enrichment ? getCategory(enrichment.category) : null;
          const headline =
            (enrichment?.is_translated && enrichment.headline_tr) ||
            enrichment?.headline ||
            article.title;
          const summary =
            (enrichment?.is_translated && enrichment.summary_tr) || enrichment?.summary;
          return (
            <button
              key={article.id}
              type="button"
              onClick={() => open(article)}
              style={
                categoryDef
                  ? ({ "--glow-color": categoryVar(categoryDef.slug) } as React.CSSProperties)
                  : undefined
              }
              className={cn(
                "group flex h-full flex-col gap-2 rounded-xl border bg-card p-4 text-left transition-all duration-200",
                "hover:-translate-y-1 motion-reduce:transform-none motion-reduce:transition-none",
                categoryDef ? "edge-lit hover:glow-edge" : "border-border hover:bg-accent/30",
              )}
            >
              {categoryDef && (
                <span
                  className={cn(
                    "w-fit rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                    categoryDef.textClass,
                    categoryDef.bgClass,
                  )}
                >
                  {categoryDef.label}
                </span>
              )}
              <span className="line-clamp-3 text-[15px] font-semibold leading-snug text-card-foreground group-hover:text-primary">
                {headline}
              </span>
              {summary && (
                <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                  {summary}
                </p>
              )}
              <span className="mt-auto pt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                {article.source.name}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
