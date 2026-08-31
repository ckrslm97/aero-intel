"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Clock, Flame, Megaphone, Radar, TrendingUp, type LucideIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { DataSourceError } from "@/components/data-source-error";
import { InsightDigestCard } from "@/components/kokpit/insight-digest-card";
import { MarketPulseCard } from "@/components/kokpit/market-pulse-card";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { relativeTimeTr } from "@/lib/campaigns";
import {
  sentimentTotals,
  signalLevelStyle,
  toFeedRow,
  topByImportance,
  type SentimentTotals,
} from "@/lib/cockpit";
import { collapseSection, reduceVariants, useMeasuredHeight } from "@/lib/motion";
import { categoryVar, getCategory } from "@/lib/taxonomy";
import type { ArticleListOut, CockpitSignal, InsightsOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIGNAL_ICONS: Record<CockpitSignal["key"], LucideIcon> = {
  fx: TrendingUp,
  fuel: Flame,
  risk: Radar,
  competitor: Megaphone,
};

/** The same window and the same importance floor "Havacılık Akışı" uses, so
 * the two panels rank over identical rows. GET /articles orders by publication
 * time, not importance, so the ranking itself happens in `topByImportance` --
 * over this window, and the caption says as much rather than implying a
 * whole-archive top three. */
const TOP_WINDOW_DAYS = 4;
const TOP_QUERY = `/articles?limit=24&days=${TOP_WINDOW_DAYS}&translated_only=true&min_importance=0.5`;

/* --- Signal chips -------------------------------------------------------- */

/** The four Sinyal Panosu levels, reduced to chips.
 *
 * These are the SAME levels the full board renders, passed down from the same
 * server fetch -- not recomputed. A chip is the level and the driving number
 * and nothing else: the board below still carries each tile's reason and
 * method note, and repeating those here would make this a second, shorter copy
 * of a panel the reader is about to scroll past.
 */
function SignalChips({ signals }: { signals: CockpitSignal[] }) {
  if (signals.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">Sinyaller şu anda hesaplanamıyor.</p>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {signals.map((signal) => {
        const Icon = SIGNAL_ICONS[signal.key] ?? TrendingUp;
        const style = signalLevelStyle(signal.level);
        return (
          <span
            key={signal.key}
            title={`${signal.reason_tr}\n\n${signal.method_tr}`}
            className={cn(
              "flex cursor-help items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold",
              style.pill,
            )}
          >
            <Icon className="size-3 shrink-0" aria-hidden />
            <span className="uppercase tracking-wide">{signal.label_tr}</span>
            <span className="tabular-nums opacity-80">{signal.value_label}</span>
          </span>
        );
      })}
    </div>
  );
}

/* --- Sentiment distribution --------------------------------------------- */

const SENTIMENT_BANDS: {
  key: keyof Omit<SentimentTotals, "total">;
  label: string;
  bar: string;
  dot: string;
}[] = [
  { key: "positive", label: "Olumlu", bar: "bg-good", dot: "bg-good" },
  { key: "neutral", label: "Nötr", bar: "bg-muted-foreground/45", dot: "bg-muted-foreground/45" },
  { key: "negative", label: "Olumsuz", bar: "bg-critical", dot: "bg-critical" },
];

/** The archive's sentiment split as one stacked bar.
 *
 * This is a COUNT of classified articles, not a mood index and not a weighted
 * score -- the caption says so, because a three-colour bar invites being read
 * as sentiment "strength". Neutral gets the deliberately non-identity gray
 * that the rest of the app uses for "no signal", so the two coloured segments
 * are the ones that draw the eye.
 */
function SentimentBar({ totals }: { totals: SentimentTotals }) {
  if (totals.total === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Henüz sınıflandırılmış haber yok.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="flex h-2 w-full overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={`Duygu dağılımı: ${SENTIMENT_BANDS.map(
          (band) => `${band.label} ${totals[band.key]}`,
        ).join(", ")}`}
      >
        {SENTIMENT_BANDS.map((band) => {
          const share = (totals[band.key] / totals.total) * 100;
          if (share === 0) return null;
          return (
            <span
              key={band.key}
              className={band.bar}
              style={{ width: `${share}%` }}
              title={`${band.label}: ${totals[band.key]} haber (%${share.toFixed(0)})`}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {SENTIMENT_BANDS.map((band) => (
          <span
            key={band.key}
            className="flex items-center gap-1 text-[10px] text-muted-foreground"
          >
            <span className={cn("size-1.5 rounded-full", band.dot)} aria-hidden />
            {band.label}
            <span className="font-semibold tabular-nums text-foreground">{totals[band.key]}</span>
          </span>
        ))}
        <span className="text-[10px] text-muted-foreground">
          · son 30 günde {totals.total} sınıflandırılmış haber
        </span>
      </div>
    </div>
  );
}

/* --- Top three developments --------------------------------------------- */

function TopDevelopments({ data }: { data: ArticleListOut | null }) {
  const rows = useMemo(
    () => topByImportance((data?.items ?? []).map(toFeedRow)),
    [data],
  );

  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Son günlerde eşiği geçen çevrilmiş bir haber yok.
      </p>
    );
  }

  return (
    <MotionList role="list" className="flex flex-col gap-1">
      {rows.map((row, index) => {
        const category = getCategory(row.category);
        return (
          <MotionItem
            key={row.id}
            role="listitem"
            style={{ "--glow-color": categoryVar(row.category) } as React.CSSProperties}
            className="rounded-md transition-colors hover:bg-accent/40"
          >
            <a
              href={row.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-2 rounded-md px-1.5 py-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span className="mt-px shrink-0 text-[11px] font-semibold tabular-nums text-muted-foreground">
                {index + 1}
              </span>
              <span
                aria-hidden
                className="mt-1 h-3 w-0.5 shrink-0 rounded-full"
                style={{ backgroundColor: categoryVar(row.category) }}
              />
              <span className="min-w-0 flex-1 text-[12px] leading-snug">{row.headline}</span>
              <span className="flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-muted-foreground">
                <Clock className="size-2.5" aria-hidden />
                {row.publishedAt ? relativeTimeTr(row.publishedAt) : "—"}
              </span>
              <span className="sr-only">{category.label}</span>
            </a>
          </MotionItem>
        );
      })}
    </MotionList>
  );
}

/* --- Panel scaffolding --------------------------------------------------- */

function Panel({
  title,
  caption,
  children,
}: {
  title: string;
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-card bg-card-sheen p-3 shadow-elev-1">
      <div className="flex flex-col gap-0.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        <p className="text-[10px] leading-relaxed text-muted-foreground/80">{caption}</p>
      </div>
      {children}
    </div>
  );
}

/**
 * "Bugünün İstihbaratı" -- what changed today, shown rather than narrated.
 *
 * WHY THE PROSE MOVED
 * -------------------
 * This section used to be two paragraphs side by side: the Market Pulse
 * synthesis and the daily digest. Both are real, both are labelled with the
 * provider that wrote them, and both are still here -- but a reader scanning
 * the page for five seconds does not read two paragraphs, and putting the
 * slowest-to-read element in the most valuable position on the page cost the
 * things they could have absorbed at a glance.
 *
 * So the default view is the glanceable half: the four signal levels as chips,
 * the archive's sentiment split as one bar, and the three highest-importance
 * stories. The prose is one click away behind "Detayı Gör", with its provider
 * labels intact -- hidden, never deleted, and never summarised into something
 * this component wrote itself.
 */
export function TodaysIntelligence({ signals }: { signals: CockpitSignal[] }) {
  const [open, setOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  const [contentRef, measuredHeight] = useMeasuredHeight<HTMLDivElement>();
  const variants = collapseSection(measuredHeight);

  const insightsFetcher = useCallback(
    (signal: AbortSignal) => apiFetch<InsightsOut>("/insights", { cache: "default", signal }),
    [],
  );
  const insights = useDataSource(insightsFetcher, []);

  const topFetcher = useCallback(
    (signal: AbortSignal) => apiFetch<ArticleListOut>(TOP_QUERY, { cache: "default", signal }),
    [],
  );
  const top = useDataSource(topFetcher, []);

  const totals = useMemo(
    () => sentimentTotals(insights.data?.sentiment_by_category),
    [insights.data],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Panel
          title="Sinyal Seviyeleri"
          caption="Sinyal Panosu'nun kendi seviyeleri — yeniden hesaplanmaz."
        >
          <SignalChips signals={signals} />
        </Panel>

        <Panel
          title="Duygu Dağılımı"
          caption="Son 30 günün sınıflandırılmış haber SAYILARI; ağırlıklı bir skor değildir."
        >
          {!insights.loaded ? (
            <Skeleton className="h-12 w-full rounded-lg" />
          ) : insights.error && !insights.data ? (
            <DataSourceError onRetry={insights.retry} lastUpdated={insights.lastUpdated} />
          ) : (
            <SentimentBar totals={totals} />
          )}
        </Panel>

        <Panel
          title="En Önemli 3 Gelişme"
          caption={`Zenginleştirmenin kendi önem skoruna göre, son ${TOP_WINDOW_DAYS} günün akışı içinde.`}
        >
          {!top.loaded ? (
            <div className="flex flex-col gap-1">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-6 w-full rounded-md" />
              ))}
            </div>
          ) : top.error && !top.data ? (
            <DataSourceError onRetry={top.retry} lastUpdated={top.lastUpdated} />
          ) : (
            <TopDevelopments data={top.data} />
          )}
        </Panel>
      </div>

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-fit items-center gap-1.5 rounded-full border border-border px-3 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <ChevronDown
          className={cn("size-3 transition-transform duration-200", open && "rotate-180")}
          aria-hidden
        />
        {open ? "Detayı gizle" : "Detayı gör"}
        <span className="text-muted-foreground/70">· Market Pulse ve Günün Özeti</span>
      </button>

      {/* Animated-height reveal, the same one the hub panels and /insights
          use: the wrapper animates to a measured pixel height rather than to
          "auto", which cannot be composited. Under reduced motion
          `reduceVariants` drops the height key entirely. */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            variants={reduceMotion ? reduceVariants(variants) : variants}
            initial="hidden"
            animate="show"
            exit="exit"
            className="overflow-hidden"
          >
            <div ref={contentRef} className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <MarketPulseCard />
              <InsightDigestCard />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
