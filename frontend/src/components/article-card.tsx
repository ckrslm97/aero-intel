"use client";

import { memo } from "react";

import { useArticleDrawer } from "@/components/article-drawer-context";
import { Badge } from "@/components/ui/badge";
import { getCategory } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { ArticleOut } from "@/lib/types";

// One formatter for the whole list. toLocaleString() builds a new
// Intl.DateTimeFormat on every call, which is genuinely expensive and was
// paid once per card per render -- 100 instantiations on the archive page.
const PUBLISHED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "medium",
  timeStyle: "short",
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
  variant?: "top" | "compact";
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

  // A category-tinted left edge that lights up on hover. The color lives in a
  // CSS var (defined per slug in globals.css) so Tailwind's scanner never has
  // to see a dynamic class name -- the slug uses underscores, the token hyphens.
  const accentVar = category
    ? `var(--category-${category.slug.replace(/_/g, "-")})`
    : undefined;

  return (
    /* The card no longer navigates away: it opens the in-app analysis drawer,
       which carries the sentiment/confidence/carrier detail this row used to
       cram in, and holds the only link out to the source. */
    <button
      type="button"
      onClick={() => open(article)}
      style={accentVar ? ({ "--accent": accentVar } as React.CSSProperties) : undefined}
      className={cn(
        "group flex w-full flex-col gap-2.5 border-l-2 border-l-transparent p-5 text-left transition-all duration-200",
        "hover:bg-accent/30 hover:-translate-y-0.5 motion-reduce:transform-none motion-reduce:transition-none",
        accentVar && "hover:[border-left-color:var(--accent)]",
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
