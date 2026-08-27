export interface SourceOut {
  id: string;
  name: string;
  url: string;
  category: string;
  trust_weight: number;
}

export interface ArticleEnrichmentOut {
  headline: string;
  summary: string;
  category: string;
  subcategory: string | null;
  region: string | null;
  importance_score: number;
  sentiment: string;
  confidence_score: number;
  corroborating_source_count: number;
  verified_at: string | null;
  tags: string;
  headline_tr: string | null;
  summary_tr: string | null;
  translated_at: string | null;
  is_translated: boolean;
}

/** A named entity the story mentions. `code` is IATA where there is one. */
export interface MentionOut {
  name: string;
  code: string | null;
}

export interface ArticleOut {
  id: string;
  url: string;
  title: string;
  author: string | null;
  published_at: string | null;
  fetched_at: string;
  status: string;
  source: SourceOut;
  enrichment: ArticleEnrichmentOut | null;
  reading_time_minutes: number;
  airlines: MentionOut[];
  airports: MentionOut[];
}

export interface ArticleListOut {
  total: number;
  items: ArticleOut[];
}

export interface HubOut {
  code: string;
  name: string;
  city: string;
  country: string;
  region: string;
  lat: number;
  lon: number;
  carriers: string[];
  note_tr: string;
  article_count: number;
}

/** A pair of airports the archive keeps discussing together. Not a schedule --
 * we have no OAG feed on the free tier. */
export interface HubRouteOut {
  from: string;
  to: string;
  from_lat: number;
  from_lon: number;
  to_lat: number;
  to_lon: number;
  article_count: number;
}

export interface HubOverviewOut {
  days: number;
  hubs: HubOut[];
  routes: HubRouteOut[];
}

export interface HubDetailOut extends Omit<HubOut, "article_count"> {
  days: number;
  article_count: number;
  categories: { slug: string; count: number }[];
  carriers_seen: { code: string; name: string; article_count: number }[];
}

export interface CountryOut {
  name: string;
  article_count: number;
  region: string | null;
}

export interface EditionSectionOut {
  section: string;
  articles: ArticleOut[];
}

export interface EditionOut {
  id: string;
  edition_date: string;
  status: string;
  headline: string;
  executive_summary: string;
  sections: EditionSectionOut[];
  pdf_available: boolean;
}

export interface EditionSummaryOut {
  id: string;
  edition_date: string;
  status: string;
  headline: string;
  story_count: number;
  pdf_available: boolean;
}

export interface KpiOut {
  metric_key: string;
  label: string;
  value: number;
  unit: string;
  delta_pct: number | null;
  up_is_good: boolean;
  trend: number[];
  is_estimate: boolean;
  as_of: string;
  /** Same-metric value from LY (2025), when the backend has one. */
  ly_value: number | null;
  /** Percent change vs LY (2025). */
  ly_delta_pct: number | null;
  /** "2025 (LY)'e göre" when LY exists, else "önceki ölçüme göre". */
  comparison_label: string;
}

export interface StatusCountOut {
  status: string;
  count: number;
}

export interface SchedulerJobOut {
  id: string;
  next_run_time: string | null;
}

export interface AdminStatusOut {
  database_ok: boolean;
  llm_provider: string;
  sources_count: number;
  articles_by_status: StatusCountOut[];
  entities_count: number;
  editions_count: number;
  latest_edition_date: string | null;
  subscribers_count: number;
  email_deliveries_by_status: StatusCountOut[];
  latest_article_fetched_at: string | null;
  scheduler_jobs: SchedulerJobOut[];
}

export type KpiPeriod = "1w" | "1m" | "3m" | "6m" | "1y";

export interface KpiHistoryPointOut {
  as_of: string;
  value: number;
}

export interface KpiCorroborationOut {
  source: string;
  source_url: string | null;
  value: number;
  as_of: string;
  diff_pct: number;
}

export interface KpiDetailOut {
  metric_key: string;
  label: string;
  value: number;
  unit: string;
  delta_pct: number | null;
  up_is_good: boolean;
  is_estimate: boolean;
  as_of: string;
  source: string;
  source_url: string | null;
  corroborations: KpiCorroborationOut[];
  history: KpiHistoryPointOut[];
  history_is_external: boolean;
  period: KpiPeriod;
}

export interface EventOut {
  id: string;
  name: string;
  starts: string;
  ends: string;
  city: string;
  country: string | null;
  region: string | null;
  url: string;
  summary_tr: string;
  event_type: "airshow" | "conference" | "sports" | "holiday" | "festival";
  date_range_tr: string;
  /** How hard the event moves demand into its market. Curated, never inferred. */
  impact_level: "high" | "medium" | "low";
  /** Organiser-published headcount, or null when there isn't one. */
  attendance: number | null;
  demand_effect_tr: string;
}

/* --- İçgörüler / new-route signals ------------------------------------- */

/** One resolved destination behind a route signal.
 *
 * Mirrors `airports_by_article` in
 * backend/app/services/insights_service.py exactly. The backend only emits an
 * airport it can find in the bundled reference table (app/data/airports.json),
 * so `lat`/`lon` are always real numbers -- an airport it cannot place is
 * dropped there rather than sent here without a position. That is what lets
 * the map trust these coordinates without a null check per point.
 */
export interface SignalAirport {
  code: string;
  /** The airport's own name ("Malpensa"), distinct from `city` ("Milano"). */
  name: string;
  city: string;
  /** Display name, already resolved from ISO2 by the backend. */
  country: string;
  lat: number;
  lon: number;
}

export interface RouteSignalArticle {
  id: string;
  headline: string;
  url: string;
  source_name: string;
  published_at: string | null;
  /** IATA carrier codes. */
  airlines: string[];
  airports: SignalAirport[];
}

export interface RouteSignalGroup {
  region: string | null;
  count: number;
  articles: RouteSignalArticle[];
}

export interface InsightsOut {
  airline_momentum: {
    code: string;
    name: string;
    current: number;
    previous: number;
    delta: number;
  }[];
  new_route_signals: RouteSignalGroup[];
  sentiment_by_category: {
    category: string;
    positive: number;
    neutral: number;
    negative: number;
  }[];
  digest: { date: string; body: string; provider: string } | null;
}

/** One rival campaign on the /kampanyalar timeline.
 *
 * Mirrors `PromotionOut` in backend/app/api/v1/promotions.py. Every date is
 * nullable there and so is every date here: campaigns reach us both from an
 * airline's own dated campaign page and from press coverage that says "this
 * summer" or nothing at all. The UI renders each missing field honestly --
 * an open-ended bar fades out, a campaign with no start date at all becomes a
 * point marker at `detected_at` -- so `null` is a rendering instruction, not
 * an error case to normalise away.
 */
export interface PromotionOut {
  id: string;
  /** IATA code; joins to `airlineTabs` in lib/nav.ts for brand hex and logo. */
  airline_code: string;
  airline_name: string;
  title_tr: string;
  summary_tr: string;
  /** 40 for "%40'a varan". Null when the source states no rate at all. */
  discount_pct: number | null;
  /** Comma-separated world-region slugs and/or plain city names, mixed. */
  markets: string | null;
  /** When tickets can be BOUGHT -- the window the timeline draws. "YYYY-MM-DD". */
  sale_starts: string | null;
  sale_ends: string | null;
  /** When the discounted ticket can be FLOWN. */
  travel_starts: string | null;
  travel_ends: string | null;
  url: string;
  source_name: string;
  region: string | null;
  /** When WE first saw it, ISO datetime. Drives the "Yeni" badge and the 48h
   * banner, and is the x position of a start-less campaign's point marker. */
  detected_at: string;
  /** Pre-formatted Turkish range, already saying which end is unknown. */
  sale_range_tr: string;
  travel_range_tr: string;
}

/** `GET /promotions/new-count` -- a count over the whole table rather than
 * over whatever fell inside the timeline's eight-week window. */
export interface PromotionNewCountOut {
  window_hours: number;
  count: number;
  airline_codes: string[];
}

/* --- Risk Radarı (backend/app/api/v1/risks.py) --------------------------- */

export interface RiskItem {
  id: string;
  headline: string;
  url: string;
  source_name: string;
  published_at: string | null;
  risk_type: string;
  risk_family: string;
  risk_type_label_tr: string;
  severity: string;
  country: string | null;
  city: string | null;
  region: string | null;
  /** Published within the last 24h. Computed server-side; rendered as a quiet
   * text tag, never as a flash -- see risk-radar-client.tsx. */
  is_fresh: boolean;
  /** How many articles clustered into this one signal. 1 for the common
   * case; >1 means multiple outlets reported the same event and this is
   * already the merged, reconciled view. */
  source_count: number;
}

export interface RiskSeverityCounts {
  high: number;
  medium: number;
  low: number;
}

export interface RiskCountry {
  country: string;
  region: string | null;
  count: number;
  /** high=3, medium=2, low=1, summed server-side. The map, the "Sıcak
   * Noktalar" ranking and the list all sort by this one number. */
  score: number;
  severity_counts: RiskSeverityCounts;
  items: RiskItem[];
}

export interface RiskRadarOut {
  days: number;
  total: number;
  countries: RiskCountry[];
  type_counts: Record<string, number>;
  family_counts: Record<string, number>;
}

/* --- Kokpit ------------------------------------------------------------- */
/** Mirrors backend/app/schemas/kokpit.py. */

export interface KokpitFxPairOut {
  currency_pair: string;
  value: number;
  unit: string;
  /** null where there isn't yet a reading far enough back -- an honest "not
   * enough history", never a fabricated 0%. Fills in as the 15-minute refresh
   * job (see backend/app/services/kpi_service.py) accumulates history. */
  day_delta_pct: number | null;
  week_delta_pct: number | null;
  month_delta_pct: number | null;
  sparkline: number[];
  as_of: string;
  source: string;
  source_url: string | null;
  frequency_label: string;
}

export interface KokpitFxPegOut {
  currency_pair: string;
  value: number;
  label: string;
  source: string;
  source_url: string;
}

export interface KokpitFxBoardOut {
  pairs: KokpitFxPairOut[];
  peg: KokpitFxPegOut;
}

/** A single bank's own forecast for one pair/horizon -- never normalised
 * across institutions, see backend/app/models/curated.py. */
export interface FxForecastOut {
  institution: string;
  currency_pair: string;
  horizon_label: string;
  horizon_months: number | null;
  value: number;
  publication_date: string;
  source_url: string;
  note_tr: string | null;
}

export interface IataIndicatorOut {
  metric: string;
  kind: "forecast" | "actual";
  value: number;
  unit: string;
  period_start: string;
  period_end: string;
  period_label_tr: string;
  region: string | null;
  publication_date: string;
  source_url: string;
  interpretation_tr: string | null;
}

export interface MarketPulseCitationOut {
  claim: string;
  source: string;
  source_url: string;
}

export interface MarketPulseOut {
  summary_tr: string;
  citations: MarketPulseCitationOut[];
  generated_at: string;
}

/* --- Hub network signals -------------------------------------------------- */
/** Same shape as InsightsOut['new_route_signals'], produced from pipeline v2
 * events instead of raw articles -- see
 * backend/app/services/network_signals_service.py. */
export type NetworkSignalGroup = RouteSignalGroup;

/* --- Biz ------------------------------------------------------------------ */
/** Mirrors backend/app/services/biz_service.py. */

export interface BizEventOut {
  id: string;
  slug: string;
  headline: string | null;
  category: string | null;
  confidence_band: string | null;
  last_seen: string;
}

export interface BizRiskEventOut extends BizEventOut {
  risk_type: string | null;
  risk_family: string | null;
  risk_severity: string | null;
  risk_score: number | null;
}

export interface BizCampaignOut {
  id: string;
  airline_code: string;
  airline_name: string;
  title: string;
  discount_pct: number | null;
  sale_starts: string | null;
  sale_ends: string | null;
  confidence_band: string | null;
  url: string;
}

export interface BizCompetitorSignal {
  airline_code: string;
  airline_name: string;
  count: number;
  events: BizEventOut[];
}

/** The structural no-filler wrapper every Biz section shares: a section is
 * either genuinely populated, or honestly says so -- never a bare `[]` a
 * caller could render as if it meant something. See biz_service._section(). */
export interface BizSection<T> {
  available: boolean;
  items: T[];
  empty_message: string | null;
}

/** Mirrors the `Recommendation` interface recommendations-client.tsx declares
 * for itself (that page's own comment explains why it doesn't import from
 * here) -- same backend shape (backend/app/services/recommendations.py),
 * declared again here because Biz's commercial_signals section is a second,
 * independent consumer. */
export interface BizCommercialSignal {
  id: string;
  title: string;
  rationale: string;
  severity: "high" | "medium" | "low";
  category: string | null;
  region: string | null;
  airline_code: string | null;
  evidence: { headline: string; url: string; source_name: string; published_at: string | null }[];
  metric: { label: string; value: number; previous: number | null } | null;
}

export interface BizOverviewOut {
  days: number;
  competitor_signals: BizSection<BizCompetitorSignal>;
  network_signals: BizSection<NetworkSignalGroup>;
  commercial_signals: BizSection<BizCommercialSignal>;
  strategic_developments: BizSection<BizEventOut>;
}
