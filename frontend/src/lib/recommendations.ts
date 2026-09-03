/** The Öneriler tab's URL contract, kept out of the component so it can be
 * asserted directly, and exercised end to end through
 * components/recommendations-client.test.tsx.
 *
 * Modelled on `parseCampaignFilters` / `campaignFiltersToSearchParams` in
 * lib/campaigns.ts: parse the whole filter state out of the address bar,
 * serialise it back onto the existing params so unrelated keys (here: the
 * `?tab=oneriler` that put the reader on this tab at all) survive, and drop
 * any value the page does not recognise.
 *
 * REPEATED KEYS, NOT A JOINED STRING. `?region=europe&region=middle-east` is
 * exactly what FastAPI parses into a list, and it is exactly what this page
 * already sends to `/recommendations`. Keeping the address bar and the request
 * in the same notation means there is one thing to read when the two disagree.
 */
import { CATEGORY_SLUGS, CARRIER_CODES, REGION_SLUGS } from "@/lib/taxonomy.gen";

/** The comparison windows the Dönem chips offer. Mirrors the `days` values
 * `/recommendations` is asked for. */
export const RECOMMENDATION_DAY_OPTIONS = [7, 14, 30] as const;
export type RecommendationDays = (typeof RECOMMENDATION_DAY_OPTIONS)[number];
export const DEFAULT_RECOMMENDATION_DAYS: RecommendationDays = 7;

/** Gelir Yönetimi is the portal's focus category, so it is both pinned first
 * in the chip row and pre-selected. */
export const PINNED_RECOMMENDATION_CATEGORY = "revenue_management";

/** What `?category=` says when the reader pressed "Tümü".
 *
 * A sentinel rather than an absent key, because absent already means something
 * else on this axis: "no opinion, open on Gelir Yönetimi". Without it,
 * clearing the category filter would produce a URL identical to the page's
 * default, and sending that link would re-narrow the page to Gelir Yönetimi
 * for whoever opened it -- the sender's own "show me everything" silently
 * reversed in transit. The region and airline axes need no sentinel: their
 * default IS empty, so absent and cleared mean the same thing. */
export const ALL_CATEGORIES_PARAM = "all";

export interface RecommendationFilters {
  days: RecommendationDays;
  /** Empty means every category -- see ALL_CATEGORIES_PARAM. */
  category: string[];
  region: string[];
  airline: string[];
}

export const DEFAULT_RECOMMENDATION_FILTERS: RecommendationFilters = {
  days: DEFAULT_RECOMMENDATION_DAYS,
  category: [PINNED_RECOMMENDATION_CATEGORY],
  region: [],
  airline: [],
};

/** Recognised values only, de-duplicated, in the order the URL listed them. */
function readList(
  params: URLSearchParams,
  name: string,
  allowed: readonly string[],
): string[] {
  const seen = new Set<string>();
  for (const raw of params.getAll(name)) {
    const value = raw.trim();
    if (value && allowed.includes(value)) seen.add(value);
  }
  return [...seen];
}

export function parseRecommendationFilters(
  params: URLSearchParams,
): RecommendationFilters {
  const days = Number(params.get("days"));
  const clearedCategories = params.getAll("category").includes(ALL_CATEGORIES_PARAM);
  const categories = readList(params, "category", CATEGORY_SLUGS);

  return {
    days: (RECOMMENDATION_DAY_OPTIONS as readonly number[]).includes(days)
      ? (days as RecommendationDays)
      : DEFAULT_RECOMMENDATION_DAYS,
    // Absent -> the page's default. `all` -> explicitly every category. A list
    // of slugs -> those slugs. An unrecognised slug with no valid siblings
    // falls back to the default rather than to "everything": a typo must not
    // silently widen the page past what the link asked for.
    category: clearedCategories
      ? []
      : categories.length > 0
        ? categories
        : DEFAULT_RECOMMENDATION_FILTERS.category,
    region: readList(params, "region", REGION_SLUGS),
    airline: readList(params, "airline", CARRIER_CODES),
  };
}

export function recommendationFiltersToSearchParams(
  filters: RecommendationFilters,
  base?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");

  if (filters.days === DEFAULT_RECOMMENDATION_DAYS) params.delete("days");
  else params.set("days", String(filters.days));

  params.delete("category");
  if (filters.category.length === 0) params.set("category", ALL_CATEGORIES_PARAM);
  else for (const slug of filters.category) params.append("category", slug);

  for (const [name, values] of [
    ["region", filters.region],
    ["airline", filters.airline],
  ] as const) {
    params.delete(name);
    for (const value of values) params.append(name, value);
  }

  return params;
}

/** The query `/recommendations` is asked for.
 *
 * Deliberately NOT the same object as the address bar: `all` is a statement
 * about the URL ("the reader cleared this axis"), and sending it to the API
 * would ask for a category literally named "all". An empty selection appends
 * nothing, which is exactly "no filter". */
export function recommendationQuery(filters: RecommendationFilters): URLSearchParams {
  const params = new URLSearchParams({ days: String(filters.days) });
  for (const slug of filters.category) params.append("category", slug);
  for (const slug of filters.region) params.append("region", slug);
  for (const code of filters.airline) params.append("airline", code);
  return params;
}
