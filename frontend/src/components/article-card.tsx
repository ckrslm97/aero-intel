import { ExternalLink, Minus, TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ArticleOut } from "@/lib/types";

function formatPublished(iso: string | null): string {
  if (!iso) return "Unknown date";
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
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

export function ArticleCard({
  article,
  variant = "compact",
}: {
  article: ArticleOut;
  variant?: "top" | "compact";
}) {
  const enrichment = article.enrichment;
  const isTop = variant === "top";

  return (
    <article className={cn("flex flex-col gap-2 p-4", isTop && "gap-3 p-5")}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" className="text-[10px] uppercase">
          {article.source.name}
        </Badge>
        {enrichment && (
          <>
            <Badge variant="outline" className="text-[10px] uppercase">
              {enrichment.category}
            </Badge>
            <span className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground">
              <SentimentIcon sentiment={enrichment.sentiment} />
              {Math.round(enrichment.confidence_score * 100)}% confidence ·{" "}
              {enrichment.corroborating_source_count} source
              {enrichment.corroborating_source_count === 1 ? "" : "s"}
            </span>
          </>
        )}
        <span className="text-[10px] text-muted-foreground">
          {formatPublished(article.published_at)}
        </span>
      </div>

      <a
        href={article.url}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "group flex items-start gap-1.5 font-medium text-card-foreground hover:text-primary",
          isTop ? "text-xl leading-snug" : "text-sm",
        )}
      >
        <span>{enrichment?.headline || article.title}</span>
        <ExternalLink className="mt-1 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
      </a>

      {enrichment?.summary && (
        <p className={cn("text-muted-foreground", isTop ? "text-sm" : "line-clamp-2 text-xs")}>
          {enrichment.summary}
        </p>
      )}
    </article>
  );
}
