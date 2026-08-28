import {
  CAMPAIGN_STATUS_LABELS_TR,
  REGION_LABELS_TR,
  ROUTE_SCOPE_LABELS_TR,
  type CampaignStatus,
  type RegionSlug,
} from "@/lib/taxonomy.gen";
import type { PromotionOut } from "@/lib/types";

/** The Kampanyalar page's filtering, faceting and label rules, kept out of the
 * component so they can be asserted directly.
 *
 * Filtering is client-side for the same reason Risk Radarı's is: the page
 * fetches one eight-week window in a single request, so narrowing it in memory
 * is exact and costs no round trip. The API grew the identical filters in PR7
 * regardless -- the export links use them, because an export must be able to
 * exceed whatever the page happens to be holding.
 *
 * Every dimension is single-select. That is a deliberate narrowing of the
 * backend's multi-select contract: a chip row where two chips can be lit at
 * once has to explain whether it means AND or OR, and this page already asks
 * the reader to hold six dimensions at a time. */

export interface CampaignFilters {
  /** IATA code, or null for every carrier. */
  airline: string | null;
  campaignType: string | null;
  status: string | null;
  /** World-region slug, matched against the flat column AND both JSON shapes. */
  region: string | null;
  /** high | medium. */
  band: string | null;
  /** Only the rows the classifier flagged for a human. */
  reviewOnly: boolean;
}

export const EMPTY_CAMPAIGN_FILTERS: CampaignFilters = {
  airline: null,
  campaignType: null,
  status: null,
  region: null,
  band: null,
  reviewOnly: false,
};

export type CampaignFacet = "airline" | "campaignType" | "status" | "region" | "band";

export function hasActiveCampaignFilter(filters: CampaignFilters): boolean {
  return (
    filters.airline !== null ||
    filters.campaignType !== null ||
    filters.status !== null ||
    filters.region !== null ||
    filters.band !== null ||
    filters.reviewOnly
  );
}

/** Every world region this campaign touches, from the three places a region
 * can be recorded: the flat `region` column (legacy rows have only this), the
 * market list, and the resolved route. Mirrors `_regions_of` in
 * backend/app/api/v1/promotions.py -- the export link and the on-screen list
 * have to agree about what "Avrupa" selects. */
export function campaignRegions(promo: PromotionOut): string[] {
  const found = new Set<string>();
  if (promo.region) found.add(promo.region);
  for (const side of [promo.route_json?.origin, promo.route_json?.dest]) {
    if (side?.region) found.add(side.region);
  }
  // `markets` is the legacy comma-joined column: region slugs and city names
  // mixed. Only the slugs are regions, and REGION_LABELS_TR is the test.
  for (const part of (promo.markets ?? "").split(",")) {
    const slug = part.trim();
    if (slug && slug in REGION_LABELS_TR) found.add(slug);
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
    case "campaignType":
      return promo.campaign_type ? [promo.campaign_type] : [];
    case "status":
      return [promo.status];
    case "region":
      return campaignRegions(promo);
    case "band":
      return promo.confidence_band ? [promo.confidence_band] : [];
  }
}

export function matchesCampaignFilters(
  promo: PromotionOut,
  filters: CampaignFilters,
): boolean {
  if (filters.airline && promo.airline_code !== filters.airline) return false;
  if (filters.campaignType && promo.campaign_type !== filters.campaignType) return false;
  if (filters.status && promo.status !== filters.status) return false;
  if (filters.band && promo.confidence_band !== filters.band) return false;
  if (filters.reviewOnly && promo.review_required !== true) return false;
  if (filters.region && !campaignRegions(promo).includes(filters.region)) return false;
  return true;
}

export function filterCampaigns(
  promos: readonly PromotionOut[],
  filters: CampaignFilters,
): PromotionOut[] {
  return promos.filter((promo) => matchesCampaignFilters(promo, filters));
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
): Record<string, number> {
  const others: CampaignFilters = { ...filters, [facet]: null };
  const counts: Record<string, number> = {};
  for (const promo of promos) {
    if (!matchesCampaignFilters(promo, others)) continue;
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
): number {
  const others: CampaignFilters = { ...filters, reviewOnly: false };
  return promos.filter(
    (promo) => promo.review_required === true && matchesCampaignFilters(promo, others),
  ).length;
}

/* --- presentation -------------------------------------------------------- */

/** Status is icon + word + colour, in that order of importance. Colour is
 * reinforcement only: the same house rule Risk Radarı's severity badges
 * follow, and the reason every entry below carries a `label`.
 *
 * EXPIRED and UNKNOWN are both muted rather than red -- an ended campaign is
 * not an alarm, it is history; and UNKNOWN is dashed because it is a statement
 * about our data, not about the campaign. */
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
    short: "Belirsiz",
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

function regionNames(promo: PromotionOut): string[] {
  return campaignRegions(promo)
    .map((slug) => REGION_LABELS_TR[slug as RegionSlug])
    .filter(Boolean);
}

/** What the table's "Rota" column says.
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
  markets: "Pazarlar",
  markets_json: "Pazarlar",
  region: "Bölge",
  url: "Bağlantı",
  source_name: "Kaynak",
  campaign_type: "Kampanya türü",
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

/** "3 sa önce". Deliberately coarse: the alert strip is a glance, and a
 * seconds-accurate clock there would be re-rendered noise. */
export function relativeTimeTr(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor((now - then) / 60_000);
  if (minutes < 1) return "az önce";
  if (minutes < 60) return `${minutes} dk önce`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} sa önce`;
  return `${Math.floor(hours / 24)} gün önce`;
}

/** The query string for `/promotions/export` and `/promotions`, built from the
 * same filter state the page is showing.
 *
 * Single-select on screen, repeatable on the wire: the API takes multi-select
 * lists, so this emits one value per active dimension rather than pretending
 * the shapes differ. */
export function campaignQueryString(
  filters: CampaignFilters,
  window?: { from?: string; to?: string },
): string {
  const params = new URLSearchParams();
  if (window?.from) params.set("date_from", window.from);
  if (window?.to) params.set("date_to", window.to);
  if (filters.airline) params.append("airline", filters.airline);
  if (filters.campaignType) params.append("campaign_type", filters.campaignType);
  if (filters.status) params.append("status", filters.status);
  if (filters.region) params.append("region", filters.region);
  if (filters.band) params.append("band", filters.band);
  if (filters.reviewOnly) params.set("review_required", "true");
  return params.toString();
}
