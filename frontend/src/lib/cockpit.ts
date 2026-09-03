/** Kokpit's pure rules, kept out of the components so they can be asserted
 * directly (see cockpit.test.ts).
 *
 * Everything here is presentation of numbers the backend already decided. The
 * one rule this file owns outright is `freshnessOf`, and it owns it because
 * "canlı" is a claim about data and has to be earned by a timestamp rather
 * than printed as decoration.
 */
import { PERIOD_KIND_LABELS_TR } from "@/lib/taxonomy.gen";
import type { AnnualPoint, CockpitSignal, FxForecastOut } from "@/lib/types";

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
  /** HOW FAR behind: "45 dk", "3 sa", "2 gün". Null inside the live window
   * (there is nothing to confess) and null with no reading at all.
   *
   * The header used to print "Gecikmeli · son 16:50" beside "Veri: 16:50 UTC"
   * -- one timestamp, twice, and between them not a word about the size of
   * the gap. A reader could easily take "son 16:50" for today's 16:50 while
   * the data was two days old. The magnitude is the part that decides whether
   * the number below is usable, so it is the part that gets printed. */
  delayLabel: string | null;
}

/** Coarse, honest units. Minutes below an hour, hours below two days, days
 * after that: a stale board is measured in the unit a reader would use to
 * describe it, not in 2 870 minutes. */
function delayLabelOf(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} dk`;
  const hours = minutes / 60;
  if (hours < 48) return `${Math.round(hours)} sa`;
  return `${Math.round(hours / 24)} gün`;
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
  if (!asOf) return { live: false, label: "Veri yok", timeLabel: null, delayLabel: null };
  const then = new Date(asOf);
  if (Number.isNaN(then.getTime())) {
    return { live: false, label: "Veri yok", timeLabel: null, delayLabel: null };
  }
  const time = utcTime(then);
  const minutes = (now.getTime() - then.getTime()) / 60_000;
  if (minutes <= LIVE_WINDOW_MINUTES) {
    return { live: true, label: "Canlı", timeLabel: time, delayLabel: null };
  }
  return {
    live: false,
    label: `Gecikmeli · son ${time}`,
    timeLabel: time,
    delayLabel: delayLabelOf(minutes),
  };
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

/** Every year any of the given series carries, ascending and de-duplicated.
 *
 * The x axis of a multi-series annual chart has to be built from the UNION,
 * not from whichever series happens to be first. A chart that takes
 * `chosen[0].points.map(p => p.year)` and then feeds every series a
 * POSITIONAL array is only correct while all of them carry exactly the same
 * years -- and this database already contains a series that does not (`cask`
 * lost its 2025 row upstream). One missing year would slide a whole series one
 * slot left and plot 2024's revenue under the 2023 label, silently.
 */
export function unionYears(seriesList: { points: AnnualPoint[] }[]): number[] {
  const years = new Set<number>();
  for (const entry of seriesList) for (const point of entry.points) years.add(point.year);
  return [...years].sort((a, b) => a - b);
}

/** [solid, dashed] halves of one series, aligned to an x axis.
 *
 * `years` names the axis: each output slot is that year's value, or null where
 * this series has no point for it (`connectNulls: false` then breaks the line
 * rather than interpolating a figure IATA never published). Omit `years` and
 * the series' own years are the axis, which is the single-series case.
 *
 * Nulls keep both arrays the length of the axis, and the last real year
 * appears in BOTH so the dashed tail starts on the solid line rather than
 * floating.
 */
export function splitForecast(
  points: AnnualPoint[],
  years?: number[],
): {
  actual: (number | null)[];
  projected: (number | null)[];
} {
  const byYear = new Map(points.map((point) => [point.year, point]));
  const axis = years ?? points.map((point) => point.year);
  const aligned = axis.map((year) => byYear.get(year) ?? null);
  const found = aligned.findIndex((point) => point !== null && point.kind !== "actual");
  const split = found === -1 ? aligned.length : found;
  return {
    actual: aligned.map((point, i) => (point && i < split ? point.value : null)),
    // `split - 1` is the join.
    projected: aligned.map((point, i) =>
      point && split > 0 && i >= split - 1 ? point.value : null,
    ),
  };
}

/** The one-letter suffix a year label carries when the year is not a
 * measurement: "25G" for IATA's own estimate, "26T" for its forecast.
 *
 * Lives here rather than in a component because four surfaces print it
 * (YearDots' labels, the Market Pulse badge, both delta scopes) and three
 * private copies of it had already appeared. A reader who learns "T = tahmin"
 * in one cell must not meet a different letter in the next.
 */
export const ANNUAL_KIND_SUFFIX: Record<AnnualPoint["kind"], string> = {
  actual: "",
  estimate: "G",
  forecast: "T",
};

/** "25→26T" -- the window a year-on-year figure was computed over, in the
 * page's own two-digit year vocabulary. */
export function annualScopeLabel(from: AnnualPoint, to: AnnualPoint): string {
  return `${String(from.year).slice(2)}→${String(to.year).slice(2)}${ANNUAL_KIND_SUFFIX[to.kind]}`;
}

/** The last point and the point for the year IMMEDIATELY before it, or null.
 *
 * "Last two POINTS" is the trap this exists to close. `cask` has no 2025 row
 * (an upstream de-duplication bug, D3 in the design spec), so taking the last
 * two points there hands back 2024 and 2026T -- a TWO-year change, which the
 * surfaces above then print in a pill that every neighbouring cell fills with
 * a ONE-year change. Nothing on screen distinguishes them. Refusing the
 * comparison, and saying why, is the only honest option; interpolating a 2025
 * would be inventing an IATA figure.
 */
export function adjacentYearPair(
  points: AnnualPoint[],
): { previous: AnnualPoint; latest: AnnualPoint } | null {
  const latest = points[points.length - 1];
  if (!latest) return null;
  const previous = points.find((point) => point.year === latest.year - 1);
  return previous ? { previous, latest } : null;
}

/** What a yearly point IS, in Turkish. NOT a copy: the backend owns these
 * three words (PERIOD_KIND_LABELS_TR in app/taxonomy.py, exported into
 * taxonomy.gen.ts) because it renders them itself on /kpi/<metric>'s period
 * label. This file used to hold a second set, so an IATA 2025 column read
 * "tahmini gerçekleşme" on the outlook tile and "ön gerçekleşme" on the KPI
 * page -- one fact, two words, depending on which surface you were standing
 * on. */
export const ANNUAL_KIND_LABELS_TR: Record<AnnualPoint["kind"], string> =
  PERIOD_KIND_LABELS_TR;

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
