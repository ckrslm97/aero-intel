import { ExternalLink, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { memo } from "react";

import { Badge } from "@/components/ui/badge";
import { getCategory, getSubcategoryLabel } from "@/lib/taxonomy";
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

function SentimentIcon({ sentiment }: { sentiment: string }) {
  if (sentiment === "positive") {
    return <TrendingUp className="size-3.5 text-good" />;
  }
  if (sentiment === "negative") {
    return <TrendingDown className="size-3.5 text-critical" />;
  }
  return <Minus className="size-3.5 text-muted-foreground" />;
}

function ArticleCardComponent({
  article,
  variant = "compact",
}: {
  article: ArticleOut;
  variant?: "top" | "compact";
}) {
  const enrichment = article.enrichment;
  const isTop = variant === "top";
  const category = enrichment ? getCategory(enrichment.category) : null;
  const subcategoryLabel = enrichment
    ? getSubcategoryLabel(enrichment.category, enrichment.subcategory)
    : null;
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
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      style={accentVar ? ({ "--accent": accentVar } as React.CSSProperties) : undefined}
      className={cn(
        "group flex flex-col gap-2 border-l-2 border-l-transparent p-4 transition-colors hover:bg-accent/30",
        accentVar && "hover:[border-left-color:var(--accent)]",
        isTop && "gap-3 p-5",
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
            {subcategoryLabel && (
              <span className="font-normal normal-case opacity-80">· {subcategoryLabel}</span>
            )}
          </span>
        )}
        <Badge variant="secondary" className="text-[10px] uppercase">
          {article.source.name}
        </Badge>
        {enrichment && (
          <span className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground">
            <SentimentIcon sentiment={enrichment.sentiment} />
            %{Math.round(enrichment.confidence_score * 100)} güven ·{" "}
            {enrichment.corroborating_source_count} kaynak
          </span>
        )}
        {enrichment && !enrichment.is_translated && (
          <span
            title="Çeviri için bir LLM sağlayıcısı yapılandırılmadı -- başlık ve özet İngilizce"
            className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground"
          >
            otomatik çeviri yok
          </span>
        )}
        <span className="text-[10px] text-muted-foreground">
          {formatPublished(article.published_at)}
        </span>
      </div>

      <div className="flex items-start justify-between gap-3">
        <div
          className={cn(
            "flex items-start gap-1.5 font-medium text-card-foreground group-hover:text-primary",
            isTop ? "text-xl leading-snug" : "text-sm",
          )}
        >
          {/* Clamp as a safety belt: a runaway "headline" (e.g. a bad LLM
              translation) must never render as a wall of text. */}
          <span className="line-clamp-2">{headline}</span>
          <ExternalLink className="mt-1 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        <span className="shrink-0 whitespace-nowrap pt-0.5 text-[10px] text-muted-foreground">
          {article.reading_time_minutes} dk okuma
        </span>
      </div>

      {summary && (
        <p className={cn("text-muted-foreground", isTop ? "text-sm" : "line-clamp-2 text-xs")}>
          {summary}
        </p>
      )}
    </a>
  );
}

// Memoised: a parent state change (a loading flag, an appended page) used to
// re-render every card in the list even though their props hadn't moved.
export const ArticleCard = memo(ArticleCardComponent);
