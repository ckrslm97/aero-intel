/** Kokpit's pure rules, kept out of the components so they can be asserted
 * directly (see cockpit.test.ts).
 *
 * Everything here is presentation of numbers the backend already decided. The
 * one rule this file owns outright is `freshnessOf`, and it owns it because
 * "canlı" is a claim about data and has to be earned by a timestamp rather
 * than printed as decoration.
 */
import type {
  AnnualPoint,
  ArticleOut,
  CockpitSignal,
  FxForecastOut,
  InsightsOut,
} from "@/lib/types";

/* --- Signal levels ------------------------------------------------------ */

/** Level -> the classes its pill and its tile rail are drawn with.
 *
 * `unknown` is deliberately neutral rather than green: a tile whose driver
 * could not be read must not look like an all-clear. Only warning and critical
 * take a hue at all -- a board where every tile is coloured tells a reader
 * nothing about which one to read first (the same argument
 * campaign-alert-strip.tsx makes for its priorities).
 */
export const SIGNAL_LEVEL_STYLES: Record<
  CockpitSignal["level"],
  { pill: string; glowVar: string }
> = {
  good: {
    pill: "bg-good/10 text-good ring-1 ring-good/30",
    glowVar: "var(--good)",
  },
  warning: {
    pill: "bg-warning/12 text-warning ring-1 ring-warning/35",
    glowVar: "var(--warning)",
  },
  critical: {
    pill: "bg-critical/12 text-critical ring-1 ring-critical/35",
    glowVar: "var(--critical)",
  },
  unknown: {
    pill: "bg-muted text-muted-foreground ring-1 ring-border",
    glowVar: "var(--muted-foreground)",
  },
};

export function signalLevelStyle(level: string) {
  return (
    SIGNAL_LEVEL_STYLES[level as CockpitSignal["level"]] ??
    SIGNAL_LEVEL_STYLES.unknown
  );
}

/* --- Freshness ---------------------------------------------------------- */

/** How stale a reading may be and still be called live. The FX cron runs every
 * ~15 minutes (backend/app/services/kpi_service.py), so 30 lets one run be
 * missed before the header stops claiming "Canlı". */
export const LIVE_WINDOW_MINUTES = 30;

export interface Freshness {
  live: boolean;
  label: string;
  /** UTC HH:MM of the reading, or null when there is no reading at all. */
  timeLabel: string | null;
}

function utcTime(date: Date): string {
  return date.toLocaleTimeString("tr-TR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "Canlı" only when a real observation is recent enough to deserve it.
 *
 * The header used to be able to say nothing at all about its own data. It must
 * not gain a decorative "%98,7 veri sağlığı" instead: this returns exactly what
 * the newest as_of supports, and says "Veri yok" when it supports nothing.
 */
export function freshnessOf(asOf: string | null | undefined, now: Date = new Date()): Freshness {
  if (!asOf) return { live: false, label: "Veri yok", timeLabel: null };
  const then = new Date(asOf);
  if (Number.isNaN(then.getTime())) {
    return { live: false, label: "Veri yok", timeLabel: null };
  }
  const time = utcTime(then);
  const minutes = (now.getTime() - then.getTime()) / 60_000;
  if (minutes <= LIVE_WINDOW_MINUTES) {
    return { live: true, label: "Canlı", timeLabel: time };
  }
  return { live: false, label: `Gecikmeli · son ${time}`, timeLabel: time };
}

/** The newest as_of across the FX board's pairs, or null for an empty board. */
export function latestAsOf(pairs: { as_of: string }[]): string | null {
  if (pairs.length === 0) return null;
  return pairs.reduce(
    (newest, pair) => (new Date(pair.as_of) > new Date(newest) ? pair.as_of : newest),
    pairs[0].as_of,
  );
}

/* --- Sector chart ------------------------------------------------------- */

/** Which years are not yet history. Years at or after the first non-`actual`
 * point are drawn dashed, including that boundary point itself -- a dashed
 * segment has to start somewhere solid or the line visibly breaks. */
export function forecastSplitIndex(points: AnnualPoint[]): number {
  const index = points.findIndex((point) => point.kind !== "actual");
  return index === -1 ? points.length : index;
}

/** [solid, dashed] halves of one series, overlapping by a point so the two
 * lines meet. Nulls keep both arrays the length of the x axis. */
export function splitForecast(points: AnnualPoint[]): {
  actual: (number | null)[];
  projected: (number | null)[];
} {
  const split = forecastSplitIndex(points);
  return {
    actual: points.map((point, i) => (i < split ? point.value : null)),
    // `split - 1` is the join: the last real year appears in both series so
    // the dashed tail starts on the solid line rather than floating.
    projected: points.map((point, i) => (i >= split - 1 && split > 0 ? point.value : null)),
  };
}

export const ANNUAL_KIND_LABELS_TR: Record<AnnualPoint["kind"], string> = {
  actual: "gerçekleşme",
  estimate: "tahmini gerçekleşme",
  forecast: "tahmin",
};

/* --- Aviation feed ------------------------------------------------------ */

/** One row of "Havacılık Akışı", reduced to what the row actually draws.
 *
 * Every field is either present on the article or explicitly null. Nothing is
 * defaulted: a story with no Turkish headline falls back to its original title
 * rather than to an invented translation, and `highImpact` is earned by a real
 * classification, never by "looks important".
 */
export interface FeedRow {
  id: string;
  headline: string;
  url: string;
  category: string;
  region: string | null;
  publishedAt: string | null;
  sourceName: string;
  /** True for a high-severity risk story or a top-decile importance score --
   * the two flags the enrichment genuinely produces. */
  highImpact: boolean;
  sentiment: string | null;
  /** The enrichment's own 0-1 importance score, or null for an article with no
   * enrichment at all. Kept nullable rather than defaulted to 0: "never
   * classified" and "classified as unimportant" are different, and only the
   * first should sink a row silently. */
  importance: number | null;
  /** The classified risk severity, where the enrichment assigned one. */
  riskSeverity: string | null;
}

/** Above this, the enrichment's own importance score is "top of the feed". */
export const HIGH_IMPACT_IMPORTANCE = 0.8;

export function toFeedRow(article: ArticleOut): FeedRow {
  const enrichment = article.enrichment;
  return {
    id: article.id,
    headline: enrichment?.headline_tr || enrichment?.headline || article.title,
    url: article.url,
    category: enrichment?.category ?? "general",
    region: enrichment?.region ?? null,
    publishedAt: article.published_at,
    sourceName: article.source?.name ?? "",
    highImpact:
      enrichment?.risk_severity === "high" ||
      (enrichment?.importance_score ?? 0) > HIGH_IMPACT_IMPORTANCE,
    sentiment: enrichment?.sentiment ?? null,
    importance: enrichment?.importance_score ?? null,
    riskSeverity: enrichment?.risk_severity ?? null,
  };
}

/** The `count` highest-scoring rows, most important first.
 *
 * GET /articles orders by publication time, not by importance -- so "en önemli
 * 3" has to be a ranking over rows already fetched, and it is only ever the
 * top three OF THAT WINDOW (the last few days, above the same importance floor
 * the feed uses). It is not a claim about the archive, which is why the panel
 * prints its window in the caption.
 *
 * Unenriched rows sort last rather than being dropped: a story the pipeline
 * never classified is still a story, and it should only lose to one that
 * actually scored higher. Ties keep the incoming (most recent first) order.
 */
export function topByImportance(rows: FeedRow[], count = 3): FeedRow[] {
  return [...rows]
    .sort((a, b) => (b.importance ?? -1) - (a.importance ?? -1))
    .slice(0, count);
}

export const SENTIMENT_LABELS_TR: Record<string, string> = {
  positive: "Olumlu",
  negative: "Olumsuz",
  neutral: "Nötr",
};

/** Only the two that carry information. A "Nötr" badge on two thirds of the
 * feed is noise, so neutral gets no badge at all. */
export const SENTIMENT_STYLES: Record<string, string> = {
  positive: "bg-good/10 text-good",
  negative: "bg-critical/10 text-critical",
};

/* --- Sentiment distribution --------------------------------------------- */

export interface SentimentTotals {
  positive: number;
  neutral: number;
  negative: number;
  total: number;
}

/** The whole archive's sentiment split, summed across categories.
 *
 * `/insights` returns sentiment PER CATEGORY (see
 * backend/app/services/insights_service.py); the Kokpit bar is the same counts
 * rolled up, so the bar and the per-category view on /insights can never
 * disagree about how many articles there were. Nothing is weighted or scored:
 * these are counts of classified articles, which is all the classification
 * produces.
 *
 * A zero total is returned as-is rather than as an empty object, so the caller
 * renders "henüz sınıflandırılmış haber yok" instead of a three-way 33% split
 * of nothing.
 */
export function sentimentTotals(
  rows: InsightsOut["sentiment_by_category"] | undefined,
): SentimentTotals {
  const totals = { positive: 0, neutral: 0, negative: 0, total: 0 };
  for (const row of rows ?? []) {
    totals.positive += row.positive;
    totals.neutral += row.neutral;
    totals.negative += row.negative;
  }
  totals.total = totals.positive + totals.neutral + totals.negative;
  return totals;
}

/* --- FX forecast buckets ------------------------------------------------- */

/** Institutions that published for the same target date, for one pair. */
export interface ForecastBucket {
  /** ISO date every row in this bucket targets. */
  targetDate: string;
  rows: FxForecastOut[];
  min: number;
  max: number;
  /** The median, but ONLY where at least `MEDIAN_MIN_INSTITUTIONS` distinct
   * institutions share this exact target date. null otherwise -- see below. */
  median: number | null;
  /** How many distinct institutions are in the bucket. Printed next to the
   * median line so "medyan" is never an unqualified claim. */
  institutionCount: number;
}

/** Below three institutions there is no median worth drawing.
 *
 * backend/app/ingest/curated_seed.py is explicit that converting one
 * institution's horizon wording into another's would be "our arithmetic
 * presented as their forecast", and app/services/cockpit_signals_service.py
 * says the same of averaging: the FX tile prints the curated forecasts as a
 * RANGE and never as a consensus. This gate is the same rule applied to a
 * chart. Two numbers have a midpoint, not a consensus; a median of two is just
 * their average wearing a statistical word, and drawing it would turn two
 * attributable claims into one unattributable invention.
 *
 * Three is the smallest count where a median is a middle observation rather
 * than an arithmetic blend -- and even then it is only drawn across rows that
 * target the SAME date, never across horizons.
 */
export const MEDIAN_MIN_INSTITUTIONS = 3;

function medianOf(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Group one pair's forecasts by the date they target.
 *
 * Rows with no `target_date` are dropped from the chart entirely (they stay in
 * the table): a marker needs an x, and inventing one is the thing the mapping
 * refused to do server-side.
 */
export function forecastBuckets(rows: FxForecastOut[]): ForecastBucket[] {
  const groups = new Map<string, FxForecastOut[]>();
  for (const row of rows) {
    if (!row.target_date) continue;
    const existing = groups.get(row.target_date);
    if (existing) existing.push(row);
    else groups.set(row.target_date, [row]);
  }

  return [...groups.entries()]
    .map(([targetDate, bucketRows]) => {
      const values = bucketRows.map((row) => row.value);
      // Distinct institutions, not row count: one bank publishing two horizons
      // that happen to land on one date is still one opinion.
      const institutionCount = new Set(bucketRows.map((row) => row.institution)).size;
      return {
        targetDate,
        rows: bucketRows,
        min: Math.min(...values),
        max: Math.max(...values),
        median: institutionCount >= MEDIAN_MIN_INSTITUTIONS ? medianOf(values) : null,
        institutionCount,
      };
    })
    .sort((a, b) => a.targetDate.localeCompare(b.targetDate));
}
