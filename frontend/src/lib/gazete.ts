/** The Gazete's filter vocabulary and its scoring vocabulary, as pure functions.
 *
 * Everything here is deliberately free of React: the page's filter state is
 * URL-owned, and "does a shared link reproduce the view it was copied from" is
 * a question about serialisation, not about rendering. Keeping the round trip
 * testable is the whole reason this file exists.
 */
import { EVENT_REGIONS, NEWSPAPER_CATEGORY_SLUGS } from "@/lib/taxonomy";

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

/** The rungs, unchanged. What changed is which one is the default -- see
 * DEFAULT_WINDOW_ID.
 *
 * "Hepsi" is available but deliberately NOT the default. It sends no `days`
 * and no `hours`, which the API already reads as "no cutoff" -- so as a
 * default it would make the first paint of the paper a query over the entire
 * archive, and the tab badges (`/articles/counts`) are unpaginated aggregates
 * over whatever window they are given. It is a rung a reader chooses, having
 * chosen to wait for it.
 */
export const WINDOW_OPTIONS: readonly WindowOption[] = [
  { id: "6h", label: "6 saat", hours: 6, scopeLabel: "son 6 saat" },
  { id: "24h", label: "24 saat", hours: 24, scopeLabel: "son 24 saat" },
  { id: "3d", label: "3 gün", days: 3, scopeLabel: "son 3 gün" },
  { id: "7d", label: "7 gün", days: 7, scopeLabel: "son 7 gün" },
  { id: "30d", label: "30 gün", days: 30, scopeLabel: "son 30 gün" },
  { id: "all", label: "Hepsi", unbounded: true, scopeLabel: "tüm arşiv" },
] as const;

/** 3 gün, down from 30.
 *
 * The 30-day default belonged to a paper that was a paginated archive with a
 * filter row on top. This one prints the day's CRITICAL developments, and the
 * backend hands out at most 8 + 5 + 5 of those per run with no carry-over
 * between categories (backend/app/services/critical_selection.py DEFAULT_QUOTAS)
 * -- so 30 days is roughly 500 cards under two headings, which is the
 * information bombardment this redesign exists to remove.
 *
 * 3 gün rather than 24 saat because an aviation wire is genuinely quiet
 * overnight and at weekends, and Havalimanı produces ~3.5 stories a day: a
 * 24-hour default would show a reader an empty section often enough to teach
 * them the section is broken. Three days is one comfortable reading session's
 * worth and survives a quiet Sunday.
 */
export const DEFAULT_WINDOW_ID = "3d";

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
 * badged "Ajans" in one drawer and "Düzenleyici" in another would be one
 * product contradicting itself.
 *
 * These survive the removal of the source/tier FILTERS (see the note on
 * GazeteFilters): the analysis drawer and the corroborating-source list still
 * name the outlet and its rung, which is the one place the reader asked for
 * provenance. What went away is filtering the paper BY provenance.
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
 *
 * There is no "Son Dakika" strip any more -- the card's own date simply turns
 * critical-coloured inside this window, which costs no extra element on the
 * card and no sixth block on the page.
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

/* --- the intelligence score ----------------------------------------------- */

/** The floor the paper sends as `?min_intelligence=`.
 *
 * DELIBERATELY LOW, and it is not the thing doing the narrowing. Two server
 * side facts decide that instead:
 *
 *   * the critical-selection pass fills a per-category quota (RM 8 /
 *     Havalimanı 5 / Etkinlik 5 per run, no carry-over) and only the
 *     shortlist it picks is translated, and
 *   * the paper asks for `translated_only=true`.
 *
 * So the list the reader sees is already the shortlist. What this floor is
 * actually for is the ONE thing the quota cannot express: an article the
 * scoring pass has never reached has `intelligence_score = NULL`, and the API
 * excludes NULL rather than treating it as zero -- so sending the parameter at
 * all is what keeps un-judged rows out of a paper whose whole claim is that
 * every story in it was judged. 0.35 additionally trims the bottom of the
 * deterministic-only tail (an article scored on the five free sub-scores but
 * never shortlisted) without cutting into the shortlist itself, which scores
 * far above it.
 *
 * Do NOT raise this to thin the paper. Thinning is the quota's job, upstream,
 * where it can be done per category; a floor applied here cuts whichever
 * category happens to score lowest and empties it -- which is exactly the
 * failure `min_importance` produced and the reason it was replaced.
 */
export const MIN_INTELLIGENCE = 0.35;

/** Everything every Gazete article query has in common.
 *
 * Mutates and returns the params it is given, the same way `applyWindowParams`
 * does, so a caller can chain the two.
 *
 * There is no `exclude_categories` here any more. It existed because one
 * query filled a list under a tab row, so every other category had to be
 * named and shut out; now each SECTION issues its own query with an explicit
 * `category=`, and a query that asks for one category cannot return another.
 */
export function appendGazeteFilters(params: URLSearchParams): URLSearchParams {
  // Gazete only shows stories that actually have a Turkish translation: an
  // untranslated article falls back to its original-language headline and
  // reads as raw German/English in a Turkish paper. Filtered server-side so
  // the count in a section's caption stays in step with its cards.
  params.set("translated_only", "true");
  params.set("min_intelligence", String(MIN_INTELLIGENCE));
  return params;
}

export type ScoreBand = "critical" | "high" | "medium" | "low";

/** The intelligence score as a band, not as a number.
 *
 * The drawer prints the band and the reason; it does not print "0.6127". A
 * four-digit float invites the reader to compare two stories on a scale whose
 * units nobody published, and the score is a weighted mean of eight
 * sub-scores where three are frequently absent (see
 * backend/app/services/news_scoring.py) -- so its third decimal is noise
 * dressed as precision.
 *
 * The cuts are the ones the shortlist actually separates on: the LLM-scored
 * shortlist lands above 0.55, the deterministic-only tail below it.
 */
export function scoreBand(score: number | null | undefined): ScoreBand | null {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  if (score >= 0.7) return "critical";
  if (score >= 0.55) return "high";
  if (score >= 0.4) return "medium";
  return "low";
}

export const SCORE_BAND_LABELS_TR: Record<ScoreBand, string> = {
  critical: "Kritik",
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

/** The eight sub-scores, in Turkish, as short noun phrases -- they are read
 * inside a sentence ("Neden seçildi: rakip hamlesi + tazelik"), not as column
 * headings. */
const COMPONENT_LABELS_TR: Record<string, string> = {
  rm_impact: "gelir etkisi",
  relevance: "konu uygunluğu",
  competitive_impact: "rakip hamlesi",
  demand_impact: "talep etkisi",
  capacity_impact: "kapasite etkisi",
  freshness: "tazelik",
  geographic_relevance: "pazar yakınlığı",
  source_reliability: "kaynak güvenilirliği",
};

/** A `score_detail` blob's numeric map at `key`, or null if it is not one.
 *
 * `score_detail` is a JSONB column, so it arrives as `unknown` and has to be
 * narrowed rather than trusted: a row written by an older (or newer) version
 * of the scorer is still a row the drawer has to render.
 */
function numericMap(
  detail: Record<string, unknown> | null | undefined,
  key: string,
): Record<string, number> | null {
  const value = detail?.[key];
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const entries = Object.entries(value).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number",
  );
  return entries.length > 0 ? Object.fromEntries(entries) : null;
}

/** "Neden seçildi": the two sub-scores that CONTRIBUTED most to this story's
 * score, named.
 *
 * Contribution, not raw value: a component worth 0.9 under a weight of 0.07
 * moved the score less than one worth 0.5 under 0.20, and naming the first
 * would be an explanation that does not explain the number next to it. The
 * weights ride along inside `score_detail` precisely so this stays honest
 * after the weights themselves change (see that module's `as_detail`).
 *
 * Returns null when there is nothing to say -- an unscored row, or a detail
 * blob this build does not recognise. The drawer then omits the line entirely
 * rather than printing an empty "Neden seçildi:".
 */
export function scoreReasonTr(
  detail: Record<string, unknown> | null | undefined,
): string | null {
  const components = numericMap(detail, "components");
  if (!components) return null;
  const weights = numericMap(detail, "weights") ?? {};
  const ranked = Object.entries(components)
    .filter(([name, value]) => COMPONENT_LABELS_TR[name] && Number.isFinite(value))
    .map(([name, value]) => ({ name, contribution: value * (weights[name] ?? 0) }))
    .filter((entry) => entry.contribution > 0)
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 2);
  if (ranked.length === 0) return null;
  return ranked.map((entry) => COMPONENT_LABELS_TR[entry.name]).join(" + ");
}

/* --- URL state ------------------------------------------------------------ */

/** Everything the Gazete's filter row can say, in one object.
 *
 * SIX FILTERS, down from eight. `tier` and `source` are gone -- the named
 * outlet row and the source-authority chips that PR #60 added. They were a
 * newsroom's question ("what did Reuters file today"), and this paper answers
 * a desk's question ("what happened that I have to price"); provenance still
 * appears where a reader goes looking for it, in the analysis drawer and the
 * corroborating-source list, and nowhere on the page's own surface.
 *
 * `page` is gone with them: sections are capped and the archive is one click
 * away, so there is no page 4 to land on.
 */
export interface GazeteFilters {
  /** One of the paper's three sections, or null for "Tümü" -- which renders
   * every section rather than defaulting to the first one. The paper is a
   * front page now, not a tab strip, so "no category" is a real view and has
   * to be representable. */
  category: string | null;
  subcategory: string | null;
  region: string | null;
  country: string | null;
  airline: string | null;
  window: string;
}

export const DEFAULT_FILTERS: GazeteFilters = {
  category: null,
  subcategory: null,
  region: null,
  country: null,
  airline: null,
  window: DEFAULT_WINDOW_ID,
};

/** Read filter state out of a query string.
 *
 * Validating rather than trusting: a category outside the Gazete's allow-list
 * (`?category=safety`, or Know How's `?category=network`) has no section to
 * select and would sit on an empty list nothing could fix, so it falls back to
 * "Tümü"; an unknown window id falls back rather than being passed to the API,
 * which would 422 on it; and an unknown region is dropped, because it is the
 * one filter this page forwards to TWO endpoints -- /events types it as an
 * enum and 422s on a typo, which would take the event blocks down over a bad
 * bookmark.
 */
export function parseFilters(params: URLSearchParams): GazeteFilters {
  const category = params.get("category");
  const windowId = params.get("window");
  const region = params.get("region");
  return {
    category: NEWSPAPER_CATEGORY_SLUGS.some((slug) => slug === category) ? category : null,
    subcategory: params.get("subcategory"),
    region: EVENT_REGIONS.some((option) => option.slug === region) ? region : null,
    country: params.get("country"),
    airline: params.get("airline"),
    window: WINDOW_OPTIONS.some((option) => option.id === windowId)
      ? windowId!
      : DEFAULT_WINDOW_ID,
  };
}

/** The inverse. Defaults are OMITTED rather than written out, so the shared
 * link for an unfiltered paper is `/newspaper` and not
 * `/newspaper?window=3d` -- a URL that says nothing should look like it. */
export function serializeFilters(filters: GazeteFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.subcategory) params.set("subcategory", filters.subcategory);
  if (filters.region) params.set("region", filters.region);
  if (filters.country) params.set("country", filters.country);
  if (filters.airline) params.set("airline", filters.airline);
  if (filters.window !== DEFAULT_WINDOW_ID) params.set("window", filters.window);
  return params;
}
