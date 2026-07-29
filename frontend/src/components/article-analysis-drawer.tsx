"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ExternalLink,
  Minus,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { useEffect } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import {
  drawerPanel,
  drawerStagger,
  fadeUpItem,
  overlayFade,
  reduceVariants,
} from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import { categoryVar, getCategory, getSubcategoryLabel } from "@/lib/taxonomy";
import type { ArticleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

const SENTIMENT_META: Record<
  string,
  { label: string; icon: typeof TrendingUp; className: string }
> = {
  positive: { label: "Olumlu", icon: TrendingUp, className: "border-good/40 bg-good/10 text-good" },
  negative: {
    label: "Olumsuz",
    icon: TrendingDown,
    className: "border-critical/40 bg-critical/10 text-critical",
  },
  neutral: {
    label: "Nötr",
    icon: Minus,
    className: "border-border bg-muted text-muted-foreground",
  },
};

const PUBLISHED_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "long",
  timeStyle: "short",
});

/** In-app analysis for one article.
 *
 * Everything shown here comes from the article object the list already
 * fetched -- category, region, sentiment, confidence, corroboration, named
 * carriers. There is deliberately no second request and no AI call: the
 * drawer explains what the pipeline already decided about the story, and the
 * footer is the one route to the external source.
 */
export function ArticleAnalysisDrawer({
  article,
  onClose,
}: {
  article: ArticleOut | null;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const item = reduceMotion ? reduceVariants(fadeUpItem) : fadeUpItem;

  useEffect(() => {
    if (!article) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [article, onClose]);

  const enrichment = article?.enrichment ?? null;
  const category = enrichment ? getCategory(enrichment.category) : null;
  const subcategoryLabel = enrichment
    ? getSubcategoryLabel(enrichment.category, enrichment.subcategory)
    : null;
  const CategoryIcon = category?.icon;
  const sentiment = enrichment
    ? (SENTIMENT_META[enrichment.sentiment] ?? SENTIMENT_META.neutral)
    : null;
  const SentimentIcon = sentiment?.icon;

  // Same rule the card uses: Turkish only when a translator actually ran.
  const headline =
    (enrichment?.is_translated && enrichment.headline_tr) ||
    enrichment?.headline ||
    article?.title ||
    "";
  const summary =
    (enrichment?.is_translated && enrichment.summary_tr) || enrichment?.summary || null;

  const tags = enrichment?.tags
    ? enrichment.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  return (
    <AnimatePresence>
      {article && (
        <>
          <motion.div
            key="article-drawer-overlay"
            variants={reduceMotion ? reduceVariants(overlayFade) : overlayFade}
            initial="hidden"
            animate="show"
            exit="exit"
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
          />
          <motion.aside
            key="article-drawer-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Haber analizi"
            variants={reduceMotion ? reduceVariants(drawerPanel) : drawerPanel}
            initial="hidden"
            animate="show"
            exit="exit"
            style={
              {
                "--glow-color": categoryVar(enrichment?.category),
              } as React.CSSProperties
            }
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl"
          >
            {/* The story's category color, as a lit edge down the seam where
                the panel meets the page. */}
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-[var(--glow-color)] via-[var(--glow-color)]/40 to-transparent"
            />
            <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-5">
              <div className="flex flex-wrap items-center gap-2">
                {category && CategoryIcon && (
                  <span
                    className={cn(
                      "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
                      category.textClass,
                      category.bgClass,
                    )}
                  >
                    <CategoryIcon className="size-3.5" />
                    {category.label}
                    {subcategoryLabel && (
                      <span className="font-normal normal-case opacity-80">
                        · {subcategoryLabel}
                      </span>
                    )}
                  </span>
                )}
                {enrichment?.region && (
                  <span className="rounded-full bg-secondary px-2.5 py-1 text-[11px] font-medium text-secondary-foreground">
                    {REGION_NAME[enrichment.region] ?? enrichment.region}
                  </span>
                )}
                {sentiment && SentimentIcon && (
                  <span
                    className={cn(
                      "flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                      sentiment.className,
                    )}
                  >
                    <SentimentIcon className="size-3.5" />
                    {sentiment.label}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Analizi kapat"
                className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </header>

            {/* Interior cascades in after the panel spring has landed
                (drawerStagger's delayChildren), so nothing is sliding while
                the panel is still travelling. */}
            <motion.div
              variants={reduceMotion ? reduceVariants(drawerStagger) : drawerStagger}
              initial="hidden"
              animate="show"
              className="flex flex-1 flex-col gap-6 overflow-y-auto px-6 py-6"
            >
              <motion.div variants={item} className="flex flex-col gap-2">
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span className="font-semibold text-foreground">{article.source.name}</span>
                  <span aria-hidden>·</span>
                  <span>
                    {article.published_at
                      ? PUBLISHED_FORMAT.format(new Date(article.published_at))
                      : "Tarih bilinmiyor"}
                  </span>
                  <span aria-hidden>·</span>
                  <span>{article.reading_time_minutes} dk okuma</span>
                </p>
                <h2 className="text-2xl font-semibold leading-snug tracking-tight text-card-foreground">
                  {headline}
                </h2>
                {enrichment && !enrichment.is_translated && (
                  <span className="w-fit rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground">
                    otomatik çeviri yok
                  </span>
                )}
              </motion.div>

              {summary && (
                <motion.p
                  variants={item}
                  className="whitespace-pre-line text-[15px] leading-relaxed text-muted-foreground"
                >
                  {summary}
                </motion.p>
              )}

              {enrichment && (
                <motion.div
                  variants={item}
                  style={
                    { "--gradient-surface": "var(--card)" } as React.CSSProperties
                  }
                  className="border-gradient flex flex-col gap-4 rounded-xl p-5"
                >
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Doğrulama
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <Metric
                      label="Güven skoru"
                      value={`%${Math.round(enrichment.confidence_score * 100)}`}
                    />
                    <Metric
                      label="Doğrulayan kaynak"
                      value={String(enrichment.corroborating_source_count)}
                    />
                    <Metric
                      label="Önem skoru"
                      value={`${Math.round(enrichment.importance_score * 100) / 100}`}
                    />
                    <Metric
                      label="Doğrulama"
                      value={
                        enrichment.verified_at
                          ? new Date(enrichment.verified_at).toLocaleDateString("tr-TR", {
                              day: "numeric",
                              month: "short",
                              year: "numeric",
                            })
                          : "—"
                      }
                    />
                  </div>
                </motion.div>
              )}

              {article.airlines.length > 0 && (
                <motion.div variants={item} className="flex flex-col gap-2.5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Adı geçen taşıyıcılar
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {article.airlines.map((airline) => (
                      <span
                        key={airline.code ?? airline.name}
                        className="flex items-center gap-2 rounded-full border border-border px-2.5 py-1 text-xs"
                      >
                        {airline.code && (
                          <AirlineLogo
                            code={airline.code}
                            name={airline.name}
                            className="size-4"
                          />
                        )}
                        {airline.name}
                      </span>
                    ))}
                  </div>
                </motion.div>
              )}

              {article.airports.length > 0 && (
                <motion.div variants={item} className="flex flex-col gap-2.5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Adı geçen havalimanları
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {article.airports.map((airport) => (
                      <span
                        key={airport.code ?? airport.name}
                        className="rounded-full border border-border px-2.5 py-1 text-xs"
                      >
                        {airport.name}
                        {airport.code && (
                          <span className="ml-1 font-mono text-[10px] text-muted-foreground">
                            {airport.code}
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                </motion.div>
              )}

              {tags.length > 0 && (
                <motion.div variants={item} className="flex flex-col gap-2.5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Etiketler
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </motion.div>
              )}

              <motion.p
                variants={item}
                className="text-[11px] leading-relaxed text-muted-foreground"
              >
                Bu analiz, haber alındığında boru hattının ürettiği sınıflandırma ve
                doğrulama verisinden oluşur — yeni bir model çağrısı yapılmaz.
              </motion.p>
            </motion.div>

            <footer className="border-t border-border px-6 py-4">
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-chart-4 px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-shadow duration-300 hover:glow"
              >
                Kaynağa git
                <ExternalLink className="size-4" />
              </a>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums">{value}</span>
    </div>
  );
}
