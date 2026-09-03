import { formatRelativeTr, shiftDayIso, utcDayIso } from "@/lib/format";
import {
  CAMPAIGN_STATUS_LABELS_TR,
  REGION_LABELS_TR,
  ROUTE_SCOPE_LABELS_TR,
  type CampaignStatus,
  type RegionSlug,
} from "@/lib/taxonomy.gen";
import type { PromotionOut } from "@/lib/types";

/** The Kampanyalar page's filtering, ordering and label rules, kept out of the
 * components so they can be asserted directly.
 *
 * Filtering is client-side for the same reason Risk Radarı's is: the page
 * fetches every publishable campaign in one request, so narrowing it in memory
 * is exact and costs no round trip. The API grew the identical filters
 * regardless -- the export links use them, because an export must be able to
 * exceed whatever the page happens to be holding.
 *
 * Every dimension is single-select. That is a deliberate narrowing of the
 * backend's multi-select contract: a chip row where two chips can be lit at
 * once has to explain whether it means AND or OR.
 *
 * EXPIRED APPEARS NOWHERE. The API stopped returning it by default in v2, and
 * nothing here asks for it back: `campaignQueryString` never emits
 * `include_expired`, and `SELECTABLE_CAMPAIGN_STATUSES` below has no EXPIRED
 * chip to click. The status is still *named* (a row whose dates changed under
 * us must not render as a blank badge), it is simply never requested. */

/** Which sale/travel window a period filter is asking about, as a horizon in
 * days from today. `now` is "open on today's date" and is the one people mean
 * when they say "şu an". */
export type CampaignPeriod = "now" | "30" | "90";

export const CAMPAIGN_PERIODS: readonly CampaignPeriod[] = ["now", "30", "90"] as const;

export const CAMPAIGN_PERIOD_LABELS_TR: Record<CampaignPeriod, string> = {
  now: "Şu an açık",
  "30": "30 gün içinde",
  "90": "90 gün içinde",
};

export interface CampaignFilters {
  /** IATA code, or null for every carrier. */
  airline: string | null;
  /** CAMPAIGN (a price) | PROMOTION (a mechanism). */
  campaignKind: string | null;
  campaignType: string | null;
  status: string | null;
  /** World-region slug, matched against the flat column AND both JSON shapes. */
  region: string | null;
  /** Country name as the route resolver spelled it, matched case-insensitively. */
  country: string | null;
  /** OND | CITY_PAIR | COUNTRY | REGION | NETWORK_WIDE. */
  routeScope: string | null;
  /** Sale window overlaps the horizon. */
  salePeriod: CampaignPeriod | null;
  /** Travel window overlaps the horizon. */
  travelPeriod: CampaignPeriod | null;
  /** high | medium. */
  band: string | null;
  /** Only the rows the classifier flagged for a human. */
  reviewOnly: boolean;
}

export const EMPTY_CAMPAIGN_FILTERS: CampaignFilters = {
  airline: null,
  campaignKind: null,
  campaignType: null,
  status: null,
  region: null,
  country: null,
  routeScope: null,
  salePeriod: null,
  travelPeriod: null,
  band: null,
  reviewOnly: false,
};

export type CampaignFacet =
  | "airline"
  | "campaignKind"
  | "campaignType"
  | "status"
  | "region"
  | "country"
  | "routeScope"
  | "band";

export function hasActiveCampaignFilter(filters: CampaignFilters): boolean {
  return (
    filters.airline !== null ||
    filters.campaignKind !== null ||
    filters.campaignType !== null ||
    filters.status !== null ||
    filters.region !== null ||
    filters.country !== null ||
    filters.routeScope !== null ||
    filters.salePeriod !== null ||
    filters.travelPeriod !== null ||
    filters.band !== null ||
    filters.reviewOnly
  );
}

/** The statuses a reader may filter on. EXPIRED is absent by construction: the
 * API hides it and this page never asks for it back, so offering the chip
 * would be offering an empty result with an explanation nobody could see. */
export const SELECTABLE_CAMPAIGN_STATUSES: readonly CampaignStatus[] = [
  "ACTIVE_BOOKING",
  "UPCOMING",
  "BOOKING_CLOSED_TRAVEL_ACTIVE",
  "UNKNOWN",
] as const;

/* --- dimensions a campaign belongs to ------------------------------------ */

/** Every world region this campaign touches, from the two places a region can
 * be recorded in the payload: the flat `region` column (legacy rows have only
 * this) and the resolved route. Mirrors `_regions_of` in
 * backend/app/api/v1/promotions.py -- the export link and the on-screen list
 * have to agree about what "Avrupa" selects.
 *
 * Three places, matching `_regions_of` exactly: the flat `region` column, the
 * resolved route, and `markets_json.regions`. The flat `markets` string is
 * read too -- region slugs and city names mixed, so only the slugs
 * REGION_LABELS_TR knows are taken out of it.
 *
 * `markets_json` used to be missing from the payload, and the chip row was
 * therefore narrower than the filter the export ran: a campaign whose only
 * mention of Europe lived in that column matched `region=europe` server-side
 * and could not appear in the on-screen chip at all. */
export function campaignRegions(promo: PromotionOut): string[] {
  const found = new Set<string>();
  if (promo.region) found.add(promo.region);
  for (const side of [promo.route_json?.origin, promo.route_json?.dest]) {
    if (side?.region) found.add(side.region);
  }
  for (const slug of promo.markets_json?.regions ?? []) {
    const trimmed = slug.trim();
    if (trimmed) found.add(trimmed);
  }
  for (const part of (promo.markets ?? "").split(",")) {
    const slug = part.trim();
    if (slug && slug in REGION_LABELS_TR) found.add(slug);
  }
  return [...found];
}

/** Every country this campaign names: the resolved route AND the extracted
 * market list.
 *
 * Both, now that `markets_json` reaches the client. It used not to, so this
 * read the route alone and the chip row silently under-selected against the
 * server-side `country=` filter the export uses -- one dimension, two answers.
 * Mirrors `_countries_of` in backend/app/api/v1/promotions.py, and the chip
 * row is built from these same values, which is what keeps the offered set
 * and the matched set identical. */
export function campaignCountries(promo: PromotionOut): string[] {
  const found = new Set<string>();
  for (const side of [promo.route_json?.origin, promo.route_json?.dest]) {
    const country = side?.country?.trim();
    if (country) found.add(country);
  }
  for (const name of promo.markets_json?.countries ?? []) {
    const trimmed = name.trim();
    if (trimmed) found.add(trimmed);
  }
  return [...found];
}

/** The values a single campaign contributes to one facet. Empty when the
 * campaign says nothing about that dimension -- an unclassified legacy row
 * contributes to no type chip and is hidden by any type filter, which is the
 * honest behaviour: it is not "OTHER", it was never classified. */
export function campaignFacetValues(promo: PromotionOut, facet: CampaignFacet): string[] {
  switch (facet) {
    case "airline":
      return [promo.airline_code];
    case "campaignKind":
      return promo.campaign_kind ? [promo.campaign_kind] : [];
    case "campaignType":
      return promo.campaign_type ? [promo.campaign_type] : [];
    case "status":
      return [promo.status];
    case "region":
      return campaignRegions(promo);
    case "country":
      return campaignCountries(promo);
    case "routeScope":
      return promo.route_scope ? [promo.route_scope] : [];
    case "band":
      return promo.confidence_band ? [promo.confidence_band] : [];
  }
}

/* --- date windows -------------------------------------------------------- */

const MS_DAY = 86_400_000;

/** Today as "YYYY-MM-DD", IN UTC -- the calendar the backend keeps.
 *
 * This read the READER's calendar day, and the two are not the same day for
 * three hours out of every twenty-four. `_today()` in
 * backend/app/api/v1/promotions.py is explicitly UTC ("status buckets must not
 * move because a cron ran at 23:40 local"), and every status, every sort key
 * and every visibility decision the API makes is cut against it. So between
 * 00:00 and 03:00 TRT the page contradicted the payload it was rendering: the
 * API had already retired a campaign whose sale window closed yesterday, and
 * the card beside it -- computing its own local "today", which was still
 * yesterday -- counted down to it as if it were live.
 *
 * A string, not a Date: every comparison in this module is a lexicographic one
 * between "YYYY-MM-DD" values, which is exactly the comparison the backend
 * makes between `date` objects and cannot drift by a timezone the way a
 * Date-to-Date comparison can.
 *
 * `now` is passed in rather than read here so the caller can supply a clock
 * that TICKS (hooks/use-now.ts). A tab left open across UTC midnight was
 * showing yesterday's countdown until it was reloaded. */
export function todayIso(now: Date = new Date()): string {
  return utcDayIso(now);
}

/** Whole days from `today` until `day`, negative once it is past. */
export function daysUntil(day: string, today: string): number {
  const at = Date.parse(`${day.slice(0, 10)}T00:00:00Z`);
  const from = Date.parse(`${today.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(at) || Number.isNaN(from)) return Number.NaN;
  return Math.round((at - from) / MS_DAY);
}

/** "2 gün kaldı" / "Son gün" / "Bugün son gün".
 *
 * Only ever called for a campaign the API has already said is still on sale,
 * so there is no past case to word: `/promotions/expiring` filters on
 * ACTIVE_BOOKING before it filters on the deadline. */
export function remainingDaysLabel(saleEnds: string, today: string): string {
  const left = daysUntil(saleEnds, today);
  if (Number.isNaN(left)) return "Bitiş tarihi okunamadı";
  if (left <= 0) return "Bugün son gün";
  if (left === 1) return "Son 1 gün";
  return `${left} gün kaldı`;
}

/** Does [start, end] overlap [from, to], with a missing edge counting as open?
 *
 * The same convention as the backend's `campaign_status` and
 * `promo_dedup._windows_overlap`: "a campaign with no stated end has not been
 * said to stop". A window with NEITHER edge stated does not overlap anything
 * -- an unstated window cannot support a claim about a period, and a period
 * filter that swept in every undated row would be the loudest possible lie on
 * this page. */
export function windowOverlaps(
  start: string | null,
  end: string | null,
  from: string,
  to: string,
): boolean {
  if (!start && !end) return false;
  if (end && end < from) return false;
  if (start && start > to) return false;
  return true;
}

/** The [from, to] a period key means, relative to `today`. */
export function periodRange(period: CampaignPeriod, today: string): [string, string] {
  if (period === "now") return [today, today];
  return [today, shiftDayIso(today, Number(period))];
}

/* --- filtering ----------------------------------------------------------- */

export function matchesCampaignFilters(
  promo: PromotionOut,
  filters: CampaignFilters,
  today: string = todayIso(),
): boolean {
  if (filters.airline && promo.airline_code !== filters.airline) return false;
  if (filters.campaignKind && promo.campaign_kind !== filters.campaignKind) return false;
  if (filters.campaignType && promo.campaign_type !== filters.campaignType) return false;
  if (filters.status && promo.status !== filters.status) return false;
  if (filters.routeScope && promo.route_scope !== filters.routeScope) return false;
  if (filters.band && promo.confidence_band !== filters.band) return false;
  if (filters.reviewOnly && promo.review_required !== true) return false;
  if (filters.region && !campaignRegions(promo).includes(filters.region)) return false;
  if (filters.country) {
    const wanted = filters.country.toLocaleLowerCase("tr");
    const found = campaignCountries(promo).some(
      (name) => name.toLocaleLowerCase("tr") === wanted,
    );
    if (!found) return false;
  }
  if (filters.salePeriod) {
    const [from, to] = periodRange(filters.salePeriod, today);
    if (!windowOverlaps(promo.sale_starts, promo.sale_ends, from, to)) return false;
  }
  if (filters.travelPeriod) {
    const [from, to] = periodRange(filters.travelPeriod, today);
    if (!windowOverlaps(promo.travel_starts, promo.travel_ends, from, to)) return false;
  }
  return true;
}

export function filterCampaigns(
  promos: readonly PromotionOut[],
  filters: CampaignFilters,
  today: string = todayIso(),
): PromotionOut[] {
  return promos.filter((promo) => matchesCampaignFilters(promo, filters, today));
}

/** Counts for one facet's chips, computed over the set narrowed by every OTHER
 * active filter.
 *
 * Counting the fully-filtered set instead would make every unselected chip in
 * the active row read 0 as soon as one was clicked, which is how a filter row
 * turns into a dead end. Counting the unfiltered set would promise rows that a
 * click cannot actually reach. */
export function campaignFacetCounts(
  promos: readonly PromotionOut[],
  filters: CampaignFilters,
  facet: CampaignFacet,
  today: string = todayIso(),
): Record<string, number> {
  const others: CampaignFilters = { ...filters, [facet]: null };
  const counts: Record<string, number> = {};
  for (const promo of promos) {
    if (!matchesCampaignFilters(promo, others, today)) continue;
    for (const value of campaignFacetValues(promo, facet)) {
      counts[value] = (counts[value] ?? 0) + 1;
    }
  }
  return counts;
}

/** How many rows the "İnceleme gerekli" toggle would leave, given the rest of
 * the filters. Its own function because the toggle is a boolean, not a facet
 * with values. */
export function reviewRequiredCount(
  promos: readonly PromotionOut[],
  filters: CampaignFilters,
  today: string = todayIso(),
): number {
  const others: CampaignFilters = { ...filters, reviewOnly: false };
  return promos.filter(
    (promo) =>
      promo.review_required === true && matchesCampaignFilters(promo, others, today),
  ).length;
}

/* --- ordering ------------------------------------------------------------ */

/** Mirrors `_STATUS_RANK` in backend/app/api/v1/promotions.py. */
const STATUS_RANK: Record<string, number> = {
  ACTIVE_BOOKING: 0,
  UPCOMING: 1,
  BOOKING_CLOSED_TRAVEL_ACTIVE: 2,
  UNKNOWN: 3,
  EXPIRED: 4,
};

/** Stands in for a missing date when sorting. A campaign with an open-ended
 * sale window has not been said to stop, so it sorts behind every campaign
 * that has a stated deadline rather than ahead of them -- "no deadline" is
 * not "deadline is today". */
const FAR_FUTURE = "9999-12-31";

/** The page's order, mirroring `order_promotions` on the API:
 *
 *   1. on sale today, soonest deadline first -- a deadline is the only thing
 *      here that expires while you read it;
 *   2. announced but not open, soonest first;
 *   3. sale closed but the travel benefit still live;
 *   4. undated;
 *   5. expired, which never reaches this page at all.
 *
 * The final tiebreaker is newest-first-seen.
 *
 * The list already arrives in this order, so applying it again is a no-op on
 * a good day. It is here anyway because the page splits, regroups and
 * re-concatenates the rows, and a resort by `detected_at` -- the order this
 * page used before v2 -- is a one-line mistake with no visible symptom. */
export function orderCampaigns(promos: readonly PromotionOut[]): PromotionOut[] {
  const key = (promo: PromotionOut): [number, string, string, number, string] => {
    const rank = STATUS_RANK[promo.status] ?? Object.keys(STATUS_RANK).length;
    const seen = Date.parse(promo.first_seen_at ?? promo.detected_at);
    return [
      rank,
      promo.status === "ACTIVE_BOOKING" ? (promo.sale_ends ?? FAR_FUTURE) : FAR_FUTURE,
      promo.status === "UPCOMING" ? (promo.sale_starts ?? FAR_FUTURE) : FAR_FUTURE,
      -(Number.isNaN(seen) ? 0 : seen),
      promo.id,
    ];
  };
  return promos
    .map((promo) => ({ promo, key: key(promo) }))
    .sort((a, b) => {
      for (let i = 0; i < a.key.length; i += 1) {
        if (a.key[i] < b.key[i]) return -1;
        if (a.key[i] > b.key[i]) return 1;
      }
      return 0;
    })
    .map((entry) => entry.promo);
}

/** Drop every expired campaign, wherever it came from.
 *
 * Deliberately redundant: `GET /promotions` stopped returning EXPIRED rows by
 * default in v2, and this page never passes `include_expired`. It is restated
 * on the client because "no expired campaign ever appears on this page" is a
 * promise the product makes to a revenue desk, and a promise that costly
 * should survive one server-side default being changed by someone who did not
 * read this file. A row whose dates moved between the query and the render
 * lands here too.
 *
 * This is the only place the word EXPIRED is acted on in the frontend. There
 * is no flag that turns it off. */
export function dropExpiredCampaigns(promos: readonly PromotionOut[]): PromotionOut[] {
  return promos.filter((promo) => promo.status !== "EXPIRED");
}

/* --- the undated group --------------------------------------------------- */

/** A campaign the sources published no date of any kind for.
 *
 * `status === "UNKNOWN"` is the whole definition, and it is the API's own:
 * `campaign_status` returns UNKNOWN only when neither the sale window nor the
 * travel window has a single stated edge. Re-deriving it here from the four
 * date fields would give the page a second opinion about the one rule the
 * feature rests on.
 *
 * Note this is NOT "has no sale start". A campaign with travel dates and no
 * sale dates is ACTIVE_BOOKING -- we know when it can be flown, which is a
 * real, dated fact -- and belongs in the main feed. */
export function isUndatedCampaign(promo: PromotionOut): boolean {
  return promo.status === "UNKNOWN";
}

export interface CampaignSplit {
  /** Campaigns with at least one stated date. The page's main feed. */
  dated: PromotionOut[];
  /** Campaigns with none. Shown apart, below, muted and collapsed. */
  undated: PromotionOut[];
}

/** Split the feed into the dated campaigns and the undated ones.
 *
 * The owner's call, and the measurement behind it: of 83 publishable
 * campaigns on 2026-09-03, 70 are UNKNOWN -- news-derived detections nobody
 * published a date for. Interleaved, they bury the 13 campaigns with a real,
 * verified window under five times their number of rows that cannot answer
 * "can I still buy this". Nothing is dropped: the undated rows keep their own
 * labelled, counted section below the feed. */
export function splitUndatedCampaigns(promos: readonly PromotionOut[]): CampaignSplit {
  const dated: PromotionOut[] = [];
  const undated: PromotionOut[] = [];
  for (const promo of promos) {
    if (isUndatedCampaign(promo)) undated.push(promo);
    else dated.push(promo);
  }
  return { dated, undated };
}

/* --- URL round-trip ------------------------------------------------------ */

/** The query-string name of each filter. Short, because all eleven can be lit
 * at once and the bar is a thing people paste into chat. */
const PARAM_NAMES: Record<keyof CampaignFilters, string> = {
  airline: "airline",
  campaignKind: "kind",
  campaignType: "type",
  status: "status",
  region: "region",
  country: "country",
  routeScope: "scope",
  salePeriod: "sale",
  travelPeriod: "travel",
  band: "band",
  reviewOnly: "review",
};

function readPeriod(value: string | null): CampaignPeriod | null {
  return CAMPAIGN_PERIODS.includes(value as CampaignPeriod)
    ? (value as CampaignPeriod)
    : null;
}

/** Filters out of the address bar.
 *
 * Unknown values are dropped rather than kept: a hand-edited `?band=purple`
 * would otherwise narrow the page to nothing while every chip read "Tümü",
 * which looks exactly like a broken build. `?status=EXPIRED` is dropped for a
 * stronger reason -- the API is not asked for expired rows, so the filter
 * could only ever empty the page. */
export function parseCampaignFilters(params: URLSearchParams): CampaignFilters {
  const status = params.get(PARAM_NAMES.status);
  return {
    airline: params.get(PARAM_NAMES.airline) || null,
    campaignKind: params.get(PARAM_NAMES.campaignKind) || null,
    campaignType: params.get(PARAM_NAMES.campaignType) || null,
    status:
      status && SELECTABLE_CAMPAIGN_STATUSES.includes(status as CampaignStatus)
        ? status
        : null,
    region: params.get(PARAM_NAMES.region) || null,
    country: params.get(PARAM_NAMES.country) || null,
    routeScope: params.get(PARAM_NAMES.routeScope) || null,
    salePeriod: readPeriod(params.get(PARAM_NAMES.salePeriod)),
    travelPeriod: readPeriod(params.get(PARAM_NAMES.travelPeriod)),
    band: params.get(PARAM_NAMES.band) || null,
    reviewOnly: params.get(PARAM_NAMES.reviewOnly) === "true",
  };
}

/** Filters back into the address bar, onto `base` so unrelated params (a view
 * toggle, a deep link's anchor) survive. A cleared filter deletes its key
 * rather than writing an empty one, so an unfiltered page has a clean URL. */
export function campaignFiltersToSearchParams(
  filters: CampaignFilters,
  base?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");
  const set = (name: string, value: string | null) => {
    if (value) params.set(name, value);
    else params.delete(name);
  };
  set(PARAM_NAMES.airline, filters.airline);
  set(PARAM_NAMES.campaignKind, filters.campaignKind);
  set(PARAM_NAMES.campaignType, filters.campaignType);
  set(PARAM_NAMES.status, filters.status);
  set(PARAM_NAMES.region, filters.region);
  set(PARAM_NAMES.country, filters.country);
  set(PARAM_NAMES.routeScope, filters.routeScope);
  set(PARAM_NAMES.salePeriod, filters.salePeriod);
  set(PARAM_NAMES.travelPeriod, filters.travelPeriod);
  set(PARAM_NAMES.band, filters.band);
  set(PARAM_NAMES.reviewOnly, filters.reviewOnly ? "true" : null);
  return params;
}

/* --- presentation -------------------------------------------------------- */

/** Status is icon + word + colour, in that order of importance. Colour is
 * reinforcement only: the same house rule Risk Radarı's severity badges
 * follow, and the reason every entry below carries a `label`.
 *
 * EXPIRED and UNKNOWN are both muted rather than red -- an ended campaign is
 * not an alarm, it is history; and UNKNOWN is dashed because it is a statement
 * about our data, not about the campaign. EXPIRED is still defined even though
 * the API no longer serves it: a row whose dates move under us must render a
 * word, never a blank badge. */
export const CAMPAIGN_STATUS_STYLE: Record<
  CampaignStatus,
  { label: string; short: string; className: string }
> = {
  ACTIVE_BOOKING: {
    label: CAMPAIGN_STATUS_LABELS_TR.ACTIVE_BOOKING,
    short: "Satışta",
    className: "border-good/40 bg-good/10 text-good",
  },
  UPCOMING: {
    label: CAMPAIGN_STATUS_LABELS_TR.UPCOMING,
    short: "Yakında",
    className: "border-primary/40 bg-primary/10 text-primary",
  },
  BOOKING_CLOSED_TRAVEL_ACTIVE: {
    label: CAMPAIGN_STATUS_LABELS_TR.BOOKING_CLOSED_TRAVEL_ACTIVE,
    short: "Seyahat sürüyor",
    className: "border-warning/40 bg-warning/10 text-warning",
  },
  EXPIRED: {
    label: CAMPAIGN_STATUS_LABELS_TR.EXPIRED,
    short: "Sona erdi",
    className: "border-border bg-muted text-muted-foreground",
  },
  UNKNOWN: {
    label: CAMPAIGN_STATUS_LABELS_TR.UNKNOWN,
    short: "Tarihsiz",
    className: "border-dashed border-border bg-transparent text-muted-foreground",
  },
};

export function campaignStatusStyle(status: string) {
  return (
    CAMPAIGN_STATUS_STYLE[status as CampaignStatus] ?? CAMPAIGN_STATUS_STYLE.UNKNOWN
  );
}

/** high/medium in Turkish. `low` never reaches this page (the API filters it
 * out) but is named anyway rather than falling through to a raw slug. */
export const CONFIDENCE_BAND_LABELS_TR: Record<string, string> = {
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

export function confidenceBandLabel(band: string | null): string {
  if (!band) return "Değerlendirilmedi";
  return CONFIDENCE_BAND_LABELS_TR[band] ?? band;
}

const PRICE_FORMAT = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });

/** The one number a row has room for: the discount rate the source published,
 * and otherwise the starting price out of `attrs_json`.
 *
 * Null when the source stated neither -- the row then shows its title alone,
 * because a "—" in a money column reads as "zero discount" rather than as
 * "not published". */
export function campaignAmountLabel(promo: PromotionOut): string | null {
  if (promo.discount_pct !== null) return `%${promo.discount_pct}`;

  const attrs = promo.attrs_json;
  const floor = attrs?.price_floor;
  if (typeof floor !== "number" || !Number.isFinite(floor)) return null;
  const currency = typeof attrs?.currency === "string" ? attrs.currency : null;
  const amount = PRICE_FORMAT.format(floor);
  return currency ? `${amount} ${currency}` : amount;
}

/** A string out of `attrs_json`, or null. The column is free-form JSON, so
 * every read of it has to survive a number, an object or a missing key. */
export function campaignAttr(promo: PromotionOut, key: string): string | null {
  const value = promo.attrs_json?.[key];
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function regionNames(promo: PromotionOut): string[] {
  return campaignRegions(promo)
    .map((slug) => REGION_LABELS_TR[slug as RegionSlug])
    .filter(Boolean);
}

/** What a row's "Rota" says.
 *
 * The OND pair when there is one, and otherwise the *scope* -- never an
 * invented pair. "Türkiye'den Avrupa'ya" is a REGION campaign; rendering it as
 * IST-LHR would be the exact error the route_scope column exists to prevent. */
export function campaignRouteLabel(promo: PromotionOut): string {
  if (promo.ond) return promo.ond;
  if (promo.origin_code && promo.dest_code) return `${promo.origin_code}-${promo.dest_code}`;

  const names = regionNames(promo);
  switch (promo.route_scope) {
    case "NETWORK_WIDE":
      return "Tüm ağ";
    case "REGION":
      return names.length > 0 ? `Bölgesel: ${names.join(", ")}` : "Bölgesel";
    case "COUNTRY": {
      const countries = [promo.route_json?.origin?.country, promo.route_json?.dest?.country]
        .filter(Boolean)
        .join(" → ");
      return countries ? `Ülke: ${countries}` : "Ülke bazlı";
    }
    case "OND":
    case "CITY_PAIR":
      return ROUTE_SCOPE_LABELS_TR[promo.route_scope];
    default:
      return names.length > 0 ? names.join(", ") : "—";
  }
}

/** Column names in Turkish, for the two places a raw field name would
 * otherwise leak onto the screen: the evidence quotes and the version
 * timeline's diff. Anything unmapped falls through as its own name rather than
 * being hidden -- a field we forgot to translate is still a change worth
 * showing. */
export const CAMPAIGN_FIELD_LABELS_TR: Record<string, string> = {
  title_tr: "Başlık",
  summary_tr: "Özet",
  discount_pct: "İndirim oranı",
  sale_starts: "Satış başlangıcı",
  sale_ends: "Satış bitişi",
  travel_starts: "Seyahat başlangıcı",
  travel_ends: "Seyahat bitişi",
  ticketing_start: "Biletleme başlangıcı",
  ticketing_end: "Biletleme bitişi",
  campaign_start: "Kampanya başlangıcı",
  campaign_end: "Kampanya bitişi",
  markets: "Pazarlar",
  markets_json: "Pazarlar",
  region: "Bölge",
  url: "Bağlantı",
  source_name: "Kaynak",
  campaign_type: "Kampanya türü",
  campaign_kind: "Kampanya sınıfı",
  business_class: "İş sınıfı",
  route_scope: "Rota kapsamı",
  ond: "Rota (OND)",
  origin_code: "Kalkış",
  dest_code: "Varış",
  confidence_score: "Güven puanı",
  confidence_band: "Güven bandı",
  promo_code: "Promosyon kodu",
  currency: "Para birimi",
  price_floor: "Başlangıç fiyatı",
  cabin: "Kabin",
};

export function campaignFieldLabel(field: string): string {
  return CAMPAIGN_FIELD_LABELS_TR[field] ?? field;
}

/** A previous/new value as one short string. `null` becomes "belirtilmedi"
 * rather than an empty cell, because "the carrier removed the end date" and
 * "we failed to render it" must not look the same. */
export function formatChangeValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "belirtilmedi";
  if (typeof value === "boolean") return value ? "Evet" : "Hayır";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** official | newsroom | secondary, in Turkish. The ordering these words
 * encode is what decided a conflict, so the badge has to name the tier rather
 * than just colour it. */
export const SOURCE_TIER_LABELS_TR: Record<string, string> = {
  official: "Resmî",
  newsroom: "Basın odası",
  secondary: "İkincil",
};

export function sourceTierLabel(tier: string | null): string {
  if (!tier) return "Bilinmiyor";
  return SOURCE_TIER_LABELS_TR[tier] ?? tier;
}

/** "3 sa önce". Deliberately coarse: these are glances, and a
 * seconds-accurate clock there would be re-rendered noise.
 *
 * The implementation moved to `formatRelativeTr` in lib/format.ts when Kokpit
 * V2's signal board needed the same string; this stays as the name several
 * call sites already import, delegating rather than duplicating. */
export const relativeTimeTr = formatRelativeTr;

/** The query string for `/promotions/export` and `/promotions`, built from the
 * same filter state the page is showing.
 *
 * Single-select on screen, repeatable on the wire: the API takes multi-select
 * lists, so this emits one value per active dimension rather than pretending
 * the shapes differ.
 *
 * `include_expired` is never emitted. The export is the page's contents in a
 * file, and the page has no expired rows in it. */
export function campaignQueryString(
  filters: CampaignFilters,
  today: string = todayIso(),
): string {
  const params = new URLSearchParams();
  if (filters.airline) params.append("airline", filters.airline);
  if (filters.campaignKind) params.append("campaign_kind", filters.campaignKind);
  if (filters.campaignType) params.append("campaign_type", filters.campaignType);
  if (filters.status) params.append("status", filters.status);
  if (filters.region) params.append("region", filters.region);
  if (filters.country) params.set("country", filters.country);
  if (filters.band) params.append("band", filters.band);
  if (filters.reviewOnly) params.set("review_required", "true");
  // `route_scope` and the two period filters have no API equivalent, so the
  // export is deliberately WIDER than the screen rather than silently
  // different: a file that quietly dropped three of the reader's filters
  // would be the harder bug to notice. The sale period is the one exception --
  // it maps exactly onto the endpoint's own date window.
  if (filters.salePeriod) {
    const [from, to] = periodRange(filters.salePeriod, today);
    params.set("date_from", from);
    params.set("date_to", to);
  }
  return params.toString();
}
