"use client";

import { Clock, Zap } from "lucide-react";
import { useCallback, useMemo } from "react";

import { DataSourceError } from "@/components/data-source-error";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { relativeTimeTr } from "@/lib/campaigns";
import { SENTIMENT_LABELS_TR, SENTIMENT_STYLES, toFeedRow } from "@/lib/cockpit";
import { worldRegions } from "@/lib/nav";
import { categoryVar, getCategory } from "@/lib/taxonomy";
import type { ArticleListOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROW_COUNT = 6;

// Reuses GET /articles rather than adding a Kokpit-only feed endpoint. The
// filters it already exposes are exactly the ones this row needs: a real
// Turkish translation, a floor on the focus-weighted importance score, and a
// recent window. A thin /kokpit/feed would have been a fourth caller of the
// same repository method with a fourth opinion about what "important" means.
const FEED_QUERY = `/articles?limit=${ROW_COUNT}&days=4&translated_only=true&min_importance=0.5`;

const REGION_NAME = new Map<string, string>(
  worldRegions.map((region) => [region.slug, region.name]),
);

/** "Havacılık Akışı": the last few days' most important translated stories.
 *
 * Badges are earned, never decorative. "YÜKSEK ETKİ" appears only for a story
 * the enrichment classified as high-severity risk or scored above
 * `HIGH_IMPACT_IMPORTANCE`; sentiment appears only when it is positive or
 * negative, because a "Nötr" chip on two thirds of the feed is noise that
 * makes the other third harder to see.
 */
export function AviationFeed() {
  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<ArticleListOut>(FEED_QUERY, { cache: "default", signal }),
    [],
  );
  const { data, error, loaded, retry, lastUpdated } = useDataSource(fetcher, []);

  const rows = useMemo(() => (data?.items ?? []).map(toFeedRow), [data]);

  if (!loaded) {
    return (
      <div className="flex flex-col gap-1.5">
        {Array.from({ length: ROW_COUNT }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (error && !data) return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />;
  if (rows.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        Son günlerde eşiği geçen çevrilmiş bir haber yok.
      </p>
    );
  }

  return (
    // role="list"/"listitem" rather than <ul>/<li>: MotionList renders a
    // motion.div and cannot be re-tagged, and a real <li> inside a <div> would
    // be invalid markup. The roles give a screen reader the same structure.
    <MotionList role="list" aria-label="Havacılık akışı" className="flex flex-col gap-1">
      {rows.map((row) => {
        const category = getCategory(row.category);
        const sentimentStyle = row.sentiment ? SENTIMENT_STYLES[row.sentiment] : undefined;
        return (
          <MotionItem
            key={row.id}
            role="listitem"
            style={{ "--glow-color": categoryVar(row.category) } as React.CSSProperties}
            className="rounded-lg transition-colors hover:bg-accent/40"
          >
            <a
              href={row.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2 py-1.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span
                className={cn(
                  "shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium",
                  category.bgClass,
                  category.textClass,
                )}
              >
                {category.label}
              </span>
              {row.highImpact && (
                <span className="flex shrink-0 items-center gap-0.5 rounded-full bg-critical/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-critical">
                  <Zap className="size-2.5" aria-hidden />
                  Yüksek etki
                </span>
              )}
              <span className="min-w-0 flex-1 basis-full text-sm leading-snug sm:basis-0">
                {row.headline}
              </span>
              {sentimentStyle && row.sentiment && (
                <span
                  className={cn(
                    "shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium",
                    sentimentStyle,
                  )}
                >
                  {SENTIMENT_LABELS_TR[row.sentiment]}
                </span>
              )}
              {row.region && (
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {REGION_NAME.get(row.region) ?? row.region}
                </span>
              )}
              <span className="flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-muted-foreground">
                <Clock className="size-2.5" aria-hidden />
                {row.publishedAt ? relativeTimeTr(row.publishedAt) : "—"}
              </span>
            </a>
          </MotionItem>
        );
      })}
    </MotionList>
  );
}
