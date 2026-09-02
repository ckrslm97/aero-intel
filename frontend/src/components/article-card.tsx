"use client";

import { memo } from "react";

import { useArticleDrawer } from "@/components/article-drawer-context";
import { Badge } from "@/components/ui/badge";
import { isBreaking } from "@/lib/gazete";
import { categoryVar, getCategory, getSubcategoryLabel } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { ArticleOut } from "@/lib/types";

// One formatter for the whole list. toLocaleString() builds a new
// Intl.DateTimeFormat on every call, which is genuinely expensive and was
// paid once per card per render -- 100 instantiations on the archive page.
const PUBLISHED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "medium",
  timeStyle: "short",
});

// The Gazete tile prints the whole stamp. It used to print the clock time
// alone, because the list was grouped under sticky per-day headers that
// carried the date; the paper is grouped by SECTION now, so a card that said
// only "14:32" would not say which day.
const GRID_DATE_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function formatPublished(iso: string | null): string {
  if (!iso) return "Tarih bilinmiyor";
  return PUBLISHED_FORMAT.format(new Date(iso));
}

function ArticleCardComponent({
  article,
  variant = "compact",
}: {
  article: ArticleOut;
  variant?: "top" | "compact" | "grid";
}) {
  const { open } = useArticleDrawer();
  const enrichment = article.enrichment;
  const isTop = variant === "top";
  const category = enrichment ? getCategory(enrichment.category) : null;
  const CategoryIcon = category?.icon;

  // Prefer the Turkish translation when a translation-capable LLM actually
  // produced one (enrichment.is_translated); otherwise fall back to the
  // original text and say so, rather than silently showing English as if it
  // were Turkish.
  const headline = (enrichment?.is_translated && enrichment.headline_tr) || enrichment?.headline || article.title;
  const summary = (enrichment?.is_translated && enrichment.summary_tr) || enrichment?.summary;

  // A category-tinted runway edge light that comes on when the row is
  // approached. The color rides on --glow-color (see globals.css), which is
  // also the override point every glow utility reads.
  //
  // This used to be an inline custom property literally named --accent, which
  // collided with the theme's own --accent token used by `hover:bg-accent/30`
  // on this very element: the hover background was being painted in the
  // category hue at 30% instead of the theme's accent surface.
  const glowVar = category ? categoryVar(category.slug) : undefined;

  // The Gazete tile. Four things and nothing else: headline, two or three
  // lines of summary, what beat it belongs to, when it ran.
  //
  // WHAT LEFT, AND WHY -- read before adding anything back.
  //
  //   * THE OUTLET'S NAME AND ITS TIER. The product owner's rule, and this is
  //     the only variant that had to change for it: `grid` has exactly one
  //     caller (the Gazete), while `top`/`compact` below are shared with the
  //     archive, BİZ, hub, search and per-date-edition pages, which are
  //     source-browsing surfaces and keep their badge. So the line is deleted
  //     here rather than hidden behind a `showSource` prop -- a prop whose
  //     false branch has one caller and whose true branch has five is a
  //     configuration option standing in for a decision that was already made.
  //     Provenance did not disappear from the product: the analysis drawer
  //     names the outlet, its tier, and every outlet that corroborated it.
  //   * "+N kaynak". Same reasoning -- corroboration is provenance, and the
  //     drawer's "Doğrulayan N kaynak" is the copy of it that can be opened
  //     and checked.
  //
  // What stays is the breaking treatment, because it costs no element: inside
  // the six-hour window the timestamp is simply critical-coloured, which is
  // also why there is no "Son Dakika" strip on the page any more.
  if (variant === "grid") {
    const stamp = article.published_at
      ? GRID_DATE_FORMAT.format(new Date(article.published_at))
      : null;
    const breaking = isBreaking(article.published_at);
    const subcategoryLabel = enrichment
      ? getSubcategoryLabel(enrichment.category, enrichment.subcategory)
      : null;
    return (
      <button
        type="button"
        onClick={() => open(article)}
        style={glowVar ? ({ "--glow-color": glowVar } as React.CSSProperties) : undefined}
        className={cn(
          "group relative flex h-full w-full flex-col gap-2 overflow-hidden rounded-xl bg-card p-4 text-left transition-all duration-200",
          "hover:-translate-y-0.5 motion-reduce:transform-none motion-reduce:transition-none",
          // One hairline, and it is the category's own hue rather than a
          // border token -- the beat is the only colour on the tile.
          "ring-1 ring-foreground/10 hover:ring-(--glow-color)",
        )}
      >
        <span className="line-clamp-3 text-[15px] font-medium leading-snug tracking-tight text-card-foreground group-hover:text-primary">
          {headline}
        </span>

        {summary && (
          <p className="line-clamp-3 text-[13px] leading-relaxed text-muted-foreground">
            {summary}
          </p>
        )}

        {/* mt-auto pins the footer down so tiles with unequal content still
            bottom-align across a row. Typography, not chips: a beat name in
            small caps beside a timestamp reads as a byline rather than as two
            more badges. */}
        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {category && CategoryIcon && (
            <span className={cn("flex items-center gap-1 font-semibold", category.textClass)}>
              <CategoryIcon className="size-3" aria-hidden />
              {category.label}
            </span>
          )}
          {subcategoryLabel && (
            <>
              <span aria-hidden>·</span>
              <span className="normal-case tracking-normal">{subcategoryLabel}</span>
            </>
          )}
          {stamp && (
            <span
              className={cn(
                "ml-auto normal-case tracking-normal tabular-nums",
                breaking && "font-semibold text-critical",
              )}
              title={breaking ? "Son 6 saat içinde yayımlandı" : undefined}
            >
              {stamp}
            </span>
          )}
        </div>
      </button>
    );
  }

  return (
    /* The card no longer navigates away: it opens the in-app analysis drawer,
       which carries the sentiment/confidence/carrier detail this row used to
       cram in, and holds the only link out to the source. */
    <button
      type="button"
      onClick={() => open(article)}
      style={glowVar ? ({ "--glow-color": glowVar } as React.CSSProperties) : undefined}
      className={cn(
        "group flex w-full flex-col gap-2.5 p-5 text-left transition-all duration-200",
        "hover:bg-accent/30 hover:-translate-y-0.5 motion-reduce:transform-none motion-reduce:transition-none",
        glowVar && "hover:glow-edge",
        isTop && "gap-3 p-6",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {category && CategoryIcon && (
          <span
            className={cn(
              "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              category.textClass,
              category.bgClass,
            )}
          >
            <CategoryIcon className="size-3" />
            {category.label}
          </span>
        )}
        <Badge variant="secondary" className="text-[10px] uppercase">
          {article.source.name}
        </Badge>
        <span className="text-[10px] text-muted-foreground">
          {formatPublished(article.published_at)}
        </span>
      </div>

      <div
        className={cn(
          "font-medium text-card-foreground group-hover:text-primary",
          isTop ? "text-xl leading-snug" : "text-sm leading-snug",
        )}
      >
        {/* Clamp as a safety belt: a runaway "headline" (e.g. a bad LLM
            translation) must never render as a wall of text. */}
        <span className="line-clamp-2">{headline}</span>
      </div>

      {summary && (
        <p
          className={cn(
            "text-muted-foreground",
            isTop ? "line-clamp-2 text-sm leading-relaxed" : "line-clamp-1 text-xs",
          )}
        >
          {summary}
        </p>
      )}
    </button>
  );
}

// Memoised: a parent state change (a loading flag, an appended page) used to
// re-render every card in the list even though their props hadn't moved.
export const ArticleCard = memo(ArticleCardComponent);
