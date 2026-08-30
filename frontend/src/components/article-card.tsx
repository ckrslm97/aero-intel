"use client";

import { memo } from "react";

import { useArticleDrawer } from "@/components/article-drawer-context";
import { Badge } from "@/components/ui/badge";
import { BADGED_TIERS, isBreaking, sourceTierLabelTr } from "@/lib/gazete";
import { categoryVar, getCategory } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { ArticleOut } from "@/lib/types";

// One formatter for the whole list. toLocaleString() builds a new
// Intl.DateTimeFormat on every call, which is genuinely expensive and was
// paid once per card per render -- 100 instantiations on the archive page.
const PUBLISHED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "medium",
  timeStyle: "short",
});

// Grid tiles carry the day in their sticky date header, so the tile itself
// only needs the clock time -- "14:32".
const TIME_FORMAT = new Intl.DateTimeFormat("tr-TR", { hour: "2-digit", minute: "2-digit" });

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

  // The Gazete grid: an apron of individually-lit tiles rather than one long
  // taxiway. `edge-lit` paints the resting perimeter/rail; hover:glow-edge
  // takes the box-shadow over on hover so the rail brightens, never flickers.
  if (variant === "grid") {
    const time = article.published_at ? TIME_FORMAT.format(new Date(article.published_at)) : null;
    // Three quiet additions, each earned rather than shown on every tile:
    //
    //   * the tier badge only for official/regulator. "From the regulator
    //     itself" is worth a badge; "from a trade outlet", which is most of
    //     the feed, is a second row of chrome on thirty tiles.
    //   * "+N kaynak" only when somebody else ran the story too, which is the
    //     one number on the card the reader can act on (it opens the list).
    //   * the time turns red inside the breaking window instead of gaining a
    //     label, so the tile does not get taller.
    const showTier = BADGED_TIERS.has(article.source.tier);
    const corroborating = enrichment?.corroborating_source_count ?? 1;
    const breaking = isBreaking(article.published_at);
    return (
      <button
        type="button"
        onClick={() => open(article)}
        style={glowVar ? ({ "--glow-color": glowVar } as React.CSSProperties) : undefined}
        className={cn(
          "group relative flex h-full w-full flex-col gap-2.5 overflow-hidden rounded-xl border bg-card p-5 text-left transition-all duration-200",
          "hover:-translate-y-1 motion-reduce:transform-none motion-reduce:transition-none",
          glowVar ? "edge-lit hover:glow-edge" : "border-border hover:bg-accent/30",
        )}
      >
        <div className="flex items-center gap-2">
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
          {time && (
            <span
              className={cn(
                "ml-auto flex items-center gap-1 text-[10px] tabular-nums",
                breaking ? "font-semibold text-critical" : "text-muted-foreground",
              )}
              title={breaking ? "Son 6 saat içinde yayımlandı" : undefined}
            >
              {breaking && <span aria-hidden className="size-1.5 rounded-full bg-critical" />}
              {time}
            </span>
          )}
        </div>

        <span className="line-clamp-2 text-sm font-medium leading-snug text-card-foreground group-hover:text-primary">
          {headline}
        </span>

        {summary && (
          <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{summary}</p>
        )}

        {/* mt-auto pins the source to the bottom so tiles with unequal
            content still bottom-align across a row. */}
        <div className="mt-auto flex items-center gap-1.5 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          <span className="truncate">{article.source.name}</span>
          {showTier && (
            <span className="shrink-0 rounded-full border border-border px-1.5 py-px text-[9px] font-semibold normal-case">
              {sourceTierLabelTr(article.source.tier)}
            </span>
          )}
          {corroborating > 1 && (
            <span
              title={`${corroborating} kaynak bu haberi işledi`}
              className="ml-auto shrink-0 rounded-full bg-muted px-1.5 py-px text-[9px] font-semibold normal-case tabular-nums"
            >
              +{corroborating - 1} kaynak
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
