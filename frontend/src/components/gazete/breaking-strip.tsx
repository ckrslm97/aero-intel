"use client";

import { useEffect, useState } from "react";

import { useArticleDrawer } from "@/components/article-drawer-context";
import { apiFetch } from "@/lib/api";
import { relativeTimeTr } from "@/lib/campaigns";
import { BREAKING_WINDOW_HOURS } from "@/lib/gazete";
import type { ArticleListOut, ArticleOut } from "@/lib/types";

/** "Son Dakika" -- what landed in the last few hours.
 *
 * There is no breaking flag anywhere in this data and there should not be one:
 * a stored boolean would need a cron to un-set it six hours later on every row
 * it was ever set on. The strip is a query instead -- `hours=6`, ordered the
 * way the API already orders -- so it empties itself.
 *
 * Renders NOTHING when the window is empty, rather than an "henüz son dakika
 * haberi yok" box. A quiet six hours is the normal state of an aviation wire
 * overnight, and a permanent empty box at the top of the paper teaches the
 * reader to scroll past the place breaking news will appear.
 */
export function BreakingStrip({
  category,
  minImportance,
  excludedCategories,
}: {
  category: string;
  minImportance: number;
  excludedCategories: readonly string[];
}) {
  const { open } = useArticleDrawer();
  const [items, setItems] = useState<ArticleOut[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      category,
      hours: String(BREAKING_WINDOW_HOURS),
      limit: "6",
      translated_only: "true",
      min_importance: String(minImportance),
    });
    excludedCategories.forEach((slug) => params.append("exclude_categories", slug));

    apiFetch<ArticleListOut>(`/articles?${params.toString()}`, {
      cache: "default",
      signal: controller.signal,
    })
      .then((data) => setItems(data.items))
      .catch(() => {
        /* A strip is an addition to the page, never a precondition for it. */
      });
    return () => controller.abort();
  }, [category, minImportance, excludedCategories]);

  if (items.length === 0) return null;

  return (
    <section
      aria-label="Son dakika"
      className="flex items-stretch gap-3 overflow-hidden rounded-xl border border-critical/30 bg-critical/5"
    >
      <span
        aria-hidden
        className="w-1 shrink-0 bg-gradient-to-b from-critical to-critical/30"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-2 py-3 pr-3">
        <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-critical">
          {/* A dot, not a blink: the pulse is CSS-free on purpose so reduced
              motion needs no special case. */}
          <span aria-hidden className="size-1.5 rounded-full bg-critical" />
          Son dakika
          <span className="font-medium normal-case tracking-normal text-muted-foreground">
            son {BREAKING_WINDOW_HOURS} saat
          </span>
        </span>
        {/* Horizontal scroll on narrow screens rather than a wrapped stack:
            the strip is a glance, and three lines of it stops being one. */}
        <div className="flex gap-2 overflow-x-auto pb-0.5">
          {items.map((article) => {
            const enrichment = article.enrichment;
            const headline =
              (enrichment?.is_translated && enrichment.headline_tr) ||
              enrichment?.headline ||
              article.title;
            return (
              <button
                key={article.id}
                type="button"
                onClick={() => open(article)}
                className="flex w-64 shrink-0 flex-col gap-1 rounded-lg border border-border bg-card p-2.5 text-left transition-colors hover:bg-accent/40"
              >
                <span className="line-clamp-2 text-xs font-medium leading-snug text-card-foreground">
                  {headline}
                </span>
                <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <span className="tabular-nums text-critical">
                    {article.published_at ? relativeTimeTr(article.published_at) : "—"}
                  </span>
                  <span aria-hidden>·</span>
                  <span className="truncate">{article.source.name}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
