/* ===========================================================================
 * Risk Radarı: the page's pure rules.
 *
 * Everything here is a function of the payload and the filter state, with no
 * React and no DOM, for two reasons. The obvious one is that it is testable
 * without a renderer. The load-bearing one is that this page draws the same
 * set five ways -- a map, a hot-spot ranking, a live feed, a country-sectioned
 * list and two bottom charts -- and every one of them has to be looking at the
 * SAME filtered set. Five components each re-deriving "does this item pass the
 * filters" is five chances to disagree, which is the same argument the backend
 * makes for computing the weighted score server-side (backend/app/api/v1/
 * risks.py module docstring).
 *
 * The honesty rules the backend states in that docstring are enforced here in
 * the mappings: `is_updated` never becomes a lifecycle word, `aviation_link`
 * never becomes an impact number, and an airport is always "anılan".
 * ======================================================================== */

import type {
  RiskCountry,
  RiskFunnelStage,
  RiskItem,
  RiskQualityOut,
  RiskRejection,
  RiskTrendPoint,
} from "@/lib/types";

/** Matches backend/app/api/v1/risks.py UNKNOWN_COUNTRY: events whose country
 * never resolved. They stay in the list -- the event is real, only its
 * placement is unknown -- but they are never a "hot spot". */
export const UNKNOWN_COUNTRY = "Belirtilmemiş";

/** high=3, medium=2, low=1 -- the same weights backend/app/taxonomy.py
 * RISK_SEVERITY_WEIGHT uses. Re-declared rather than imported because the
 * generated taxonomy file carries structure, not weights; the two are checked
 * against each other by the API's own ordering, which this mirrors. */
export const SEVERITY_WEIGHT: Record<string, number> = { high: 3, medium: 2, low: 1 };

export function severityWeight(severity: string): number {
  return SEVERITY_WEIGHT[severity] ?? 1;
}

/** The five source tiers app/pipeline/clustering.py `tier_for_source` can
 * return. Not the campaign page's three (official/newsroom/secondary) -- those
 * describe a promotion's provenance, these describe a news outlet's kind, and
 * conflating them would badge a regulator as a "basın odası". */
export const RISK_SOURCE_TIER_LABELS_TR: Record<string, string> = {
  official: "Resmî",
  regulator: "Düzenleyici",
  agency: "Ajans",
  trade: "Basın",
  aggregator: "Toplayıcı",
};

export function riskSourceTierLabel(tier: string | null | undefined): string {
  if (!tier) return "Bilinmiyor";
  return RISK_SOURCE_TIER_LABELS_TR[tier] ?? tier;
}

/** Confidence score -> the band the pill shows.
 *
 * The thresholds are the app's existing ones (app/pipeline/confidence.py's
 * ladder, the same 0.75/0.5 split the campaign pill renders). A null score is
 * a null band, never "low": "we did not compute this" and "we computed this
 * and it came out weak" are different facts, and only the second one is a
 * judgement about the story. */
export function confidenceBand(score: number | null): "high" | "medium" | "low" | null {
  if (score === null || Number.isNaN(score)) return null;
  if (score >= 0.75) return "high";
  if (score >= 0.5) return "medium";
  return "low";
}

/** What the aviation_link flag is allowed to say on screen.
 *
 * "Doğrudan bağlantılı" -- the coverage names an airport, or the event type is
 * itself an aviation operation. NOT "affects flights", NOT a score: this
 * product has no schedule, OTP or route data, so any wording implying a
 * measured operational effect would be invented. `indirect` renders nothing at
 * all rather than a "dolaylı" badge -- most signals are indirect, and a badge
 * on the majority is noise. */
export function aviationLinkLabel(
  link: string,
): { label: string; title: string } | null {
  if (link !== "direct") return null;
  return {
    label: "Havacılık bağlantılı",
    title:
      "Haberde bir havalimanı anılıyor ya da olay türü doğrudan havacılık " +
      "operasyonuna ait. Uçuşların etkilendiği anlamına gelmez.",
  };
}

/** The two coverage-flow badges, in priority order.
 *
 * Deliberately about the COVERAGE and never about the event: nothing upstream
 * knows whether a wildfire is still burning, so "Sürüyor" or "Aktif" would be
 * a claim with no source. "Yeni" = the story broke in the last day;
 * "Güncellendi" = an older story somebody added to today. A signal can be
 * neither, and most are. */
export function coverageBadge(
  item: Pick<RiskItem, "is_fresh" | "is_updated">,
): { label: string; title: string; tone: "new" | "updated" } | null {
  if (item.is_fresh) {
    return {
      label: "Yeni",
      title: "İlk haber son 24 saat içinde yayımlandı.",
      tone: "new",
    };
  }
  if (item.is_updated) {
    return {
      label: "Güncellendi",
      title:
        "Daha eski bir olay; son 24 saat içinde yeni bir haber daha yayımlandı. " +
        "Olayın durumu hakkında bir bilgi değildir.",
      tone: "updated",
    };
  }
  return null;
}

/** How old the newest article about a signal has to be before the card says
 * so. Seven days, because the backend's own freshness vocabulary stops at 24h
 * ("Yeni", "Güncellendi") and everything past that currently renders
 * identically -- a story nobody has written about in three weeks looks exactly
 * like one from Tuesday. */
export const STALE_COVERAGE_DAYS = 7;

/** The shortest window in which the "ESKİ" tag is drawn at all. In a 7g or 14g
 * view nothing can be much older than the tag's own threshold, so it would fire
 * on most of the list and say nothing; it only carries information once the
 * window is wide enough for genuinely old coverage to sit next to today's. */
export const STALE_TAG_MIN_WINDOW = 30;

/** "ESKİ", or nothing.
 *
 * A pure display rule over data the payload already carries, and deliberately
 * a statement about the COVERAGE, exactly like coverageBadge: "nobody has
 * written about this in over a week" is a fact about the feed. It is NOT
 * "the event is over" -- there is no lifecycle anywhere in this data, and a
 * wildfire can burn for a month with the wires having moved on after day three.
 *
 * Mutually exclusive with coverageBadge by construction, and enforced rather
 * than assumed: a signal whose newest article is inside 24h cannot also be one
 * nobody has written about in a week, so the fresh badges win outright and a
 * card never carries two contradictory age tags. */
export function staleBadge(
  item: Pick<RiskItem, "is_fresh" | "is_updated" | "last_reported_at" | "published_at">,
  windowDays: number,
  now: Date = new Date(),
): { label: string; title: string } | null {
  if (windowDays < STALE_TAG_MIN_WINDOW) return null;
  if (coverageBadge(item)) return null;

  const iso = item.last_reported_at ?? item.published_at;
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;

  const ageDays = (now.getTime() - at) / 86_400_000;
  if (ageDays <= STALE_COVERAGE_DAYS) return null;

  return {
    label: "ESKİ",
    title:
      `Bu sinyal hakkındaki en yeni haber ${STALE_COVERAGE_DAYS} günden eski. ` +
      "Yayın akışıyla ilgili bir bilgidir; olayın bittiği anlamına gelmez.",
  };
}

/** Split a country's items into the ones the page states normally and the ones
 * it states quietly.
 *
 * The server already sorts low-visibility items to the end of each group (see
 * risks.py), so this preserves order rather than re-sorting -- the two lists
 * concatenated are the group exactly as the API sent it. An unknown visibility
 * value counts as normal: a new band the backend grows should render as a
 * signal, not silently drop into a collapsed block nobody opens. */
export function partitionByVisibility(items: RiskItem[]): {
  normal: RiskItem[];
  low: RiskItem[];
} {
  const normal: RiskItem[] = [];
  const low: RiskItem[] = [];
  for (const item of items) (item.visibility === "low" ? low : normal).push(item);
  return { normal, low };
}

/** Which headline text to draw, and what to say about it.
 *
 * `original` is what the source published, offered as a hover title so a
 * reader can check the Turkish against it -- the translation is a machine's
 * paraphrase, and hiding the sentence it paraphrased makes it uncheckable.
 * `untranslated` drives the app's existing quiet "otomatik çeviri yok" tag
 * (article-analysis-drawer.tsx): source-language text on a Turkish page is
 * fine, and passing it off as Turkish is not. */
export function headlinePresentation(
  item: Pick<RiskItem, "headline" | "headline_original" | "is_translated">,
): { text: string; original: string | null; untranslated: boolean } {
  return {
    text: item.headline,
    // Never echo the shown text back as its own tooltip: a title attribute
    // repeating the words underneath it is noise a screen reader reads twice.
    original:
      item.is_translated && item.headline_original && item.headline_original !== item.headline
        ? item.headline_original
        : null,
    untranslated: !item.is_translated,
  };
}

export interface RiskFilters {
  family: string | null;
  type: string | null;
  severity: string | null;
  region: string | null;
  country: string | null;
  /** Coverage-flow toggles. Both on means "new OR updated", not "both at
   * once" -- an item cannot be both (is_fresh implies the first telling is
   * inside 24h, is_updated implies it is not). */
  onlyNew: boolean;
  onlyUpdated: boolean;
  /** Free text over the loaded window. Client-side on purpose: /risks already
   * returns the whole classified set for the window in one payload, so a
   * backend search would be a round trip to filter data the browser has. */
  search: string;
}

export const EMPTY_RISK_FILTERS: RiskFilters = {
  family: null,
  type: null,
  severity: null,
  region: null,
  country: null,
  onlyNew: false,
  onlyUpdated: false,
  search: "",
};

/** Turkish-aware fold for the search box. `toLocaleLowerCase("tr")` so
 * "İSTANBUL" and "istanbul" meet -- the default lowercase maps "İ" to "i̇"
 * (i + combining dot) and the two never match. */
function fold(value: string): string {
  return value.toLocaleLowerCase("tr").trim();
}

function matchesSearch(item: RiskItem, countryLabel: string, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    item.headline,
    item.country ?? "",
    countryLabel,
    item.city ?? "",
    item.source_name,
    item.risk_type_label_tr,
  ]
    .map(fold)
    .join(" ");
  return haystack.includes(needle);
}

/** Apply every active filter and re-derive each country's count, score and
 * severity split for the FILTERED set.
 *
 * Re-deriving rather than passing the server's numbers through is the point: a
 * "Sıcak Noktalar" ranking still scored on all nine wildfires while the list
 * below it showed the one high-severity one would be a ranking that contradicts
 * its own page. Ordering mirrors the server's exactly, including the rule that
 * the unplaced bucket sorts last regardless of score. */
export function filterRiskCountries(
  countries: RiskCountry[],
  filters: RiskFilters,
): RiskCountry[] {
  const needle = fold(filters.search);
  const flowFilterOn = filters.onlyNew || filters.onlyUpdated;

  return countries
    .map((group) => {
      const items = group.items.filter((item) => {
        if (filters.family && item.risk_family !== filters.family) return false;
        if (filters.type && item.risk_type !== filters.type) return false;
        if (filters.severity && item.severity !== filters.severity) return false;
        if (filters.region && item.region !== filters.region) return false;
        if (filters.country && group.country !== filters.country) return false;
        if (flowFilterOn) {
          const flowMatch =
            (filters.onlyNew && item.is_fresh) || (filters.onlyUpdated && item.is_updated);
          if (!flowMatch) return false;
        }
        return matchesSearch(item, group.country, needle);
      });
      if (items.length === 0) return null;

      const counts = { high: 0, medium: 0, low: 0 };
      let score = 0;
      for (const item of items) {
        if (item.severity in counts) counts[item.severity as keyof typeof counts] += 1;
        score += severityWeight(item.severity);
      }
      return { ...group, items, count: items.length, score, severity_counts: counts };
    })
    .filter((group): group is RiskCountry => group !== null)
    .sort(
      (a, b) =>
        Number(a.country === UNKNOWN_COUNTRY) - Number(b.country === UNKNOWN_COUNTRY) ||
        b.score - a.score ||
        b.count - a.count ||
        a.country.localeCompare(b.country, "tr"),
    );
}

/** Every visible item flattened out, newest COVERAGE first.
 *
 * Sorted by `last_reported_at` rather than `published_at`: the live feed
 * answers "what is being written about right now", and for a three-day-old
 * story that just got a fourth article, the primary's own publication time is
 * the wrong answer. Falls back to published_at for rows that predate the
 * field. */
export function liveFeedItems(
  countries: RiskCountry[],
  limit = 8,
): { item: RiskItem; country: string }[] {
  const rows = countries.flatMap((group) =>
    group.items.map((item) => ({ item, country: group.country })),
  );
  return rows
    .sort((a, b) => coverageTime(b.item) - coverageTime(a.item))
    .slice(0, limit);
}

function coverageTime(item: RiskItem): number {
  const iso = item.last_reported_at ?? item.published_at;
  if (!iso) return 0;
  const at = new Date(iso).getTime();
  return Number.isNaN(at) ? 0 : at;
}

/** Per-type totals over the visible set, worst-first.
 *
 * Client-derived rather than read from `type_counts`: that field counts the
 * whole window, and this breakdown sits under a filtered page. A bar chart
 * disagreeing with the list above it is the one thing a breakdown must never
 * do. */
export function riskTypeBreakdown(
  countries: RiskCountry[],
): { type: string; label: string; count: number; high: number }[] {
  const byType = new Map<string, { label: string; count: number; high: number }>();
  for (const group of countries) {
    for (const item of group.items) {
      const entry = byType.get(item.risk_type) ?? {
        label: item.risk_type_label_tr,
        count: 0,
        high: 0,
      };
      entry.count += 1;
      if (item.severity === "high") entry.high += 1;
      byType.set(item.risk_type, entry);
    }
  }
  return [...byType.entries()]
    .map(([type, entry]) => ({ type, ...entry }))
    .sort((a, b) => b.count - a.count || b.high - a.high || a.label.localeCompare(b.label, "tr"));
}

export interface RiskTrendSeries {
  /** One entry per day in the window, oldest first -- including days the API
   * returned nothing for. The API omits empty days (an absent day is not a
   * measured zero), and the axis needs them back or a quiet week would render
   * as a continuous bar. */
  days: string[];
  natural: number[];
  conflict: number[];
  /** High-severity publications per day, across both families. Drawn as a line
   * over the stack rather than a third bar: it is a subset of the two, and
   * stacking a subset on top of its own supersets would double-count. */
  high: number[];
}

/** Fold the API's (day, family, severity) points into three aligned series.
 *
 * `today` is injectable so the zero-fill is testable without freezing the
 * clock. */
export function buildRiskTrendSeries(
  points: RiskTrendPoint[],
  days: number,
  today: Date = new Date(),
): RiskTrendSeries {
  const dayKeys: string[] = [];
  const end = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    dayKeys.push(new Date(end - offset * 86_400_000).toISOString().slice(0, 10));
  }
  const index = new Map(dayKeys.map((day, position) => [day, position]));

  const natural = new Array<number>(dayKeys.length).fill(0);
  const conflict = new Array<number>(dayKeys.length).fill(0);
  const high = new Array<number>(dayKeys.length).fill(0);

  for (const point of points) {
    const position = index.get(point.day);
    if (position === undefined) continue; // outside the drawn window
    if (point.family === "conflict") conflict[position] += point.count;
    else natural[position] += point.count;
    if (point.severity === "high") high[position] += point.count;
  }

  return { days: dayKeys, natural, conflict, high };
}

/* ===========================================================================
 * The doğrulama screen's pure rules (spec §23-24).
 *
 * Same discipline as everything above: no React, no DOM, so the funnel's
 * arithmetic and the rejection filter can be asserted without a renderer. The
 * screen draws the funnel twice -- as bars and as a numeric column -- and both
 * must read the same widths off the same function.
 * ======================================================================== */

/** One funnel stage, ready to draw: the API's row plus the bar geometry.
 *
 * `widthPct` is measured against the FIRST stage, never against the previous
 * one. A bar scaled to its own predecessor makes every stage look like it kept
 * most of what reached it -- which is exactly the impression the funnel exists
 * to correct when 13.906 articles become 9 signals. */
export interface RiskFunnelBar {
  key: string;
  label: string;
  passed: number;
  dropped: number;
  reason: string | null;
  /** Every reason this stage's drops carry, with its own count -- one entry
   * for most stages, two for the location gate. A chip built from `reason`
   * alone would promise the stage's whole drop and deliver one reason's share
   * of it. */
  reasons: { reason: string; count: number }[];
  dropKind: string | null;
  note: string | null;
  /** 0-100, relative to the widest (first) stage. */
  widthPct: number;
  /** What share of the stage ABOVE reached this one, 0-100. Null on the first
   * stage, which has nothing above it. */
  keptPct: number | null;
}

export function buildRiskFunnel(stages: readonly RiskFunnelStage[]): RiskFunnelBar[] {
  const top = stages[0]?.passed ?? 0;
  return stages.map((stage, index) => {
    const previous = index > 0 ? stages[index - 1].passed : null;
    return {
      key: stage.key,
      label: stage.label_tr,
      passed: stage.passed,
      dropped: stage.dropped,
      reason: stage.reason,
      reasons: Object.entries(stage.reason_counts ?? {}).map(([reason, count]) => ({
        reason,
        count,
      })),
      dropKind: stage.drop_kind,
      note: stage.note_tr,
      // A zero-length bar for a real, non-zero stage would read as "nothing
      // here"; 0 stays 0, and anything else gets at least a sliver.
      widthPct: top > 0 ? Math.max(stage.passed > 0 ? 0.6 : 0, (stage.passed / top) * 100) : 0,
      keptPct: previous && previous > 0 ? (stage.passed / previous) * 100 : null,
    };
  });
}

/** The reason filter's options, in funnel order, each with its uncapped count.
 *
 * Built from the STAGES rather than from `rejected_counts`, so the order a
 * reader sees matches the order the rules run in -- and so a reason with zero
 * rejections this window still appears, greyed, instead of vanishing. A filter
 * whose options come and go with the data cannot be learned. */
export interface RiskRejectionFilterOption {
  reason: string;
  label: string;
  count: number;
}

export function rejectionFilterOptions(
  quality: Pick<RiskQualityOut, "stages" | "rejected_counts" | "reason_labels_tr">,
): RiskRejectionFilterOption[] {
  const seen = new Set<string>();
  const options: RiskRejectionFilterOption[] = [];
  for (const stage of quality.stages) {
    if (stage.drop_kind !== "rejected" || !stage.reason || seen.has(stage.reason)) continue;
    seen.add(stage.reason);
    options.push({
      reason: stage.reason,
      label: quality.reason_labels_tr[stage.reason] ?? stage.reason,
      count: quality.rejected_counts[stage.reason] ?? 0,
    });
  }
  // The location stage carries one of its two reasons; the other only ever
  // appears in `rejected_counts`, and leaving it out would make a whole class
  // of rejection unreachable from the filter.
  for (const [reason, count] of Object.entries(quality.rejected_counts)) {
    if (seen.has(reason)) continue;
    seen.add(reason);
    options.push({
      reason,
      label: quality.reason_labels_tr[reason] ?? reason,
      count,
    });
  }
  return options;
}

/** What a rejected row's location evidence says, as one short line.
 *
 * The three fields it folds are meaningless apart: a country with no
 * confidence is a guess presented as a fact, and a confidence with no country
 * is a number about nothing. */
export function rejectionPlaceLabel(
  row: Pick<RiskRejection, "detected_country" | "detected_city" | "location_confidence">,
): string {
  const place = [row.detected_city, row.detected_country].filter(Boolean).join(", ");
  if (!place) return "Konum çözülemedi";
  if (row.location_confidence === null) return `${place} (ölçülmedi)`;
  return `${place} (${row.location_confidence.toFixed(2)})`;
}

/** A score, or the word for "nobody measured this".
 *
 * Never "0.00" for a null: the whole revision exists because "we did not
 * measure this" and "we measured this and it was zero" are different facts,
 * and a table that renders them identically re-creates the bug on screen. */
export function scoreOrUnscored(score: number | null | undefined): string {
  return score === null || score === undefined ? "ölçülmedi" : score.toFixed(2);
}
