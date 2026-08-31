/** The Gazete's filter vocabulary, as pure functions.
 *
 * Everything here is deliberately free of React: the page's filter state is
 * now URL-owned, and "does a shared link reproduce the view it was copied
 * from" is a question about serialisation, not about rendering. Keeping the
 * round trip testable is the whole reason this file exists.
 */
import type { CategorySlug } from "@/lib/taxonomy.gen";
import { NEWSPAPER_CATEGORY_SLUGS } from "@/lib/taxonomy";

/* --- the time window ------------------------------------------------------ */

/** One rung of the window chip row.
 *
 * `hours` and `days` are the two ways the API expresses the same axis and it
 * accepts exactly one of them per request (it 422s on both -- see
 * backend/app/api/v1/articles.py `_window_start`), so a rung carries whichever
 * one it means and never both.
 */
export interface WindowOption {
  /** What goes in `?window=`. Stable: these strings are in shared links. */
  id: string;
  label: string;
  hours?: number;
  days?: number;
  /** True for the one rung that sends no time param at all. Carried as a flag
   * rather than inferred from `!hours && !days`, so a rung added without
   * either by mistake fails the type check instead of silently becoming a
   * whole-archive query. */
  unbounded?: boolean;
  /** How the empty state names this rung: "Seçili dönemde (son 6 saat)". The
   * chip label is a control ("6 saat"); this is the same window written as a
   * span, which is what a sentence needs. */
  scopeLabel: string;
}

/** 30 gün stays the default, unchanged: the paper has always shown a 30-day
 * window and a shorter default would silently empty the list for anyone who
 * bookmarked it. The two short rungs are what the hour param was added for.
 *
 * "Hepsi" is available but deliberately NOT the default. It sends no `days`
 * and no `hours`, which the API already reads as "no cutoff" -- so as a
 * default it would make the first paint of the paper a query over the entire
 * archive, and the tab badges (`/articles/counts`) and the source facets are
 * unpaginated aggregates over whatever window they are given. It is a rung a
 * reader chooses, having chosen to wait for it.
 */
export const WINDOW_OPTIONS: readonly WindowOption[] = [
  { id: "6h", label: "6 saat", hours: 6, scopeLabel: "son 6 saat" },
  { id: "24h", label: "24 saat", hours: 24, scopeLabel: "son 24 saat" },
  { id: "3d", label: "3 gün", days: 3, scopeLabel: "son 3 gün" },
  { id: "7d", label: "7 gün", days: 7, scopeLabel: "son 7 gün" },
  { id: "30d", label: "30 gün", days: 30, scopeLabel: "son 30 gün" },
  { id: "all", label: "Hepsi", unbounded: true, scopeLabel: "tüm arşiv" },
] as const;

export const DEFAULT_WINDOW_ID = "30d";

export function windowOption(id: string | null): WindowOption {
  return (
    WINDOW_OPTIONS.find((option) => option.id === id) ??
    WINDOW_OPTIONS.find((option) => option.id === DEFAULT_WINDOW_ID)!
  );
}

/** Write a window onto a query string as the single param the API allows.
 *
 * Both keys are deleted first: switching 24 saat -> 7 gün on a URL that
 * already carries `hours` would otherwise send `hours=24&days=7` and earn a
 * 422 rather than a list.
 */
export function applyWindowParams(params: URLSearchParams, option: WindowOption): URLSearchParams {
  params.delete("hours");
  params.delete("days");
  // "Hepsi" writes neither, which is exactly how the API expresses "no
  // cutoff" -- there is no `days=0` or sentinel to send, and inventing one
  // would be a second way to say what an absent param already says.
  if (option.hours) params.set("hours", String(option.hours));
  else if (option.days) params.set("days", String(option.days));
  return params;
}

/* --- source tiers --------------------------------------------------------- */

/** The five tiers backend/app/taxonomy.py SOURCE_TIERS defines, in Turkish.
 *
 * Same labels the Risk Radarı prints (lib/risk.ts RISK_SOURCE_TIER_LABELS_TR)
 * because they describe the same thing about the same outlets -- an outlet
 * badged "Ajans" on a card and "Düzenleyici" in the risk drawer would be one
 * product contradicting itself. Not the campaign page's three tiers, which
 * describe a promotion's provenance rather than a newsroom's kind.
 */
export const SOURCE_TIER_LABELS_TR: Record<string, string> = {
  official: "Resmî",
  regulator: "Düzenleyici",
  agency: "Ajans",
  trade: "Basın",
  aggregator: "Toplayıcı",
};

export function sourceTierLabelTr(tier: string | null | undefined): string {
  if (!tier) return "Bilinmiyor";
  return SOURCE_TIER_LABELS_TR[tier] ?? tier;
}

/** The tier chips, as the filter row groups them.
 *
 * Four chips over five tiers: "Resmî kaynak" merges official and regulator
 * because the distinction between an airline's newsroom and a regulator's is
 * not one a reader filters on -- both mean "from the horse's mouth" -- and a
 * five-chip row on top of the four rows already there is noise. Each chip
 * sends its tiers as repeated `?tier=` values, which is exactly what the API
 * unions.
 */
export const TIER_FILTERS: readonly { id: string; label: string; tiers: string[] }[] = [
  { id: "official", label: "Resmî", tiers: ["official", "regulator"] },
  { id: "agency", label: "Ajans", tiers: ["agency"] },
  { id: "trade", label: "Basın", tiers: ["trade"] },
  { id: "aggregator", label: "Toplayıcı", tiers: ["aggregator"] },
] as const;

/** Only these two earn a badge on a card.
 *
 * A badge on every tile is not a signal, it is a second row of chrome on
 * thirty tiles. "This came from the regulator itself" is worth interrupting
 * for; "this came from a trade outlet", which is most of the feed, is not.
 */
export const BADGED_TIERS = new Set(["official", "regulator"]);

/* --- "son dakika" --------------------------------------------------------- */

/** How recent a story has to be to read as breaking. */
export const BREAKING_WINDOW_HOURS = 6;

/** Derived, never stored: there is no "breaking" column and inventing one
 * would mean a cron to un-set it six hours later on every row. A timestamp
 * plus a clock answers the same question and cannot go stale.
 *
 * Undated stories are NOT breaking. A feed that omits dates is common, and
 * treating "we don't know when" as "just now" would put the loudest label in
 * the paper on its least certain rows.
 */
export function isBreaking(publishedAt: string | null, now: number = Date.now()): boolean {
  if (!publishedAt) return false;
  const published = new Date(publishedAt).getTime();
  if (Number.isNaN(published)) return false;
  const ageHours = (now - published) / 3_600_000;
  // A future timestamp is a feed's clock error, not tomorrow's news; it counts
  // as fresh rather than being excluded by a negative age.
  return ageHours < BREAKING_WINDOW_HOURS;
}

/* --- URL state ------------------------------------------------------------ */

/** Everything the Gazete's filter row can say, in one object.
 *
 * The page used to read the URL exactly once, on mount, after which the chips
 * owned the state -- so a filtered view could be arrived at but never shared,
 * and the back button walked out of the page instead of back through the
 * filters. This is the shape that fixed it.
 */
export interface GazeteFilters {
  category: string;
  subcategory: string | null;
  region: string | null;
  country: string | null;
  airline: string | null;
  window: string;
  tier: string | null;
  /** One named outlet, exactly as `/articles/source-facets` spelled it.
   *
   * Single-select on screen, repeatable on the wire: the API takes `?source=`
   * once per value, but a chip row that let a reader accumulate outlets would
   * put an unbounded list of names in the shared link, and the tier chips next
   * to it are single-select for the same reason. Not validated against a list
   * here the way `tier` is -- the valid names are the window's own facets,
   * which only the server knows; an outlet that produced nothing simply
   * returns an empty page, which is what the empty state is for.
   */
  source: string | null;
  page: number;
}

export const DEFAULT_CATEGORY: CategorySlug = NEWSPAPER_CATEGORY_SLUGS[0];

export const DEFAULT_FILTERS: GazeteFilters = {
  category: DEFAULT_CATEGORY,
  subcategory: null,
  region: null,
  country: null,
  airline: null,
  window: DEFAULT_WINDOW_ID,
  tier: null,
  source: null,
  page: 1,
};

/** Read filter state out of a query string.
 *
 * Validating rather than trusting, in both directions:
 *
 *   * a category outside the Gazete's allow-list (`?category=safety`, or Know
 *     How's `?category=network`) has no tab to select and would sit on an
 *     empty list nothing could fix, so it falls back to the default tab, and
 *   * an unknown window or tier id falls back rather than being passed to the
 *     API, which would 422 on the first and empty the page on the second.
 */
export function parseFilters(params: URLSearchParams): GazeteFilters {
  const category = params.get("category");
  const windowId = params.get("window");
  const tier = params.get("tier");
  const page = Number(params.get("page"));
  return {
    category: NEWSPAPER_CATEGORY_SLUGS.some((slug) => slug === category)
      ? category!
      : DEFAULT_CATEGORY,
    subcategory: params.get("subcategory"),
    region: params.get("region"),
    country: params.get("country"),
    airline: params.get("airline"),
    window: WINDOW_OPTIONS.some((option) => option.id === windowId)
      ? windowId!
      : DEFAULT_WINDOW_ID,
    tier: TIER_FILTERS.some((filter) => filter.id === tier) ? tier : null,
    source: params.get("source"),
    page: Number.isFinite(page) && page >= 1 ? Math.floor(page) : 1,
  };
}

/** The inverse. Defaults are OMITTED rather than written out, so the shared
 * link for an unfiltered paper is `/newspaper` and not
 * `/newspaper?category=revenue_management&window=30d&page=1` -- a URL that
 * says nothing should look like it. */
export function serializeFilters(filters: GazeteFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.category !== DEFAULT_CATEGORY) params.set("category", filters.category);
  if (filters.subcategory) params.set("subcategory", filters.subcategory);
  if (filters.region) params.set("region", filters.region);
  if (filters.country) params.set("country", filters.country);
  if (filters.airline) params.set("airline", filters.airline);
  if (filters.window !== DEFAULT_WINDOW_ID) params.set("window", filters.window);
  if (filters.tier) params.set("tier", filters.tier);
  if (filters.source) params.set("source", filters.source);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params;
}

/** True when the reader has narrowed the paper past its default view.
 *
 * What the "Öne Çıkanları" and "Son Dakika" strips key off. Both are summaries
 * OF the default paper -- a top-4 that ignored the region chip the reader just
 * pressed would be four stories from somewhere else sitting above their
 * filtered list, which reads as a bug. So the strips appear on the default
 * view and step out of the way the moment a filter is applied.
 *
 * The category is not part of this: a category IS the paper's tab row, not a
 * narrowing of it, and the strips follow the selected tab.
 */
export function hasNarrowingFilters(filters: GazeteFilters): boolean {
  return Boolean(
    filters.subcategory ||
      filters.region ||
      filters.country ||
      filters.airline ||
      filters.tier ||
      filters.source ||
      filters.window !== DEFAULT_WINDOW_ID ||
      filters.page > 1,
  );
}
