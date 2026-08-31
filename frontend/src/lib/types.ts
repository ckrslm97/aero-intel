import type {
  CampaignBusinessClass,
  CampaignStatus,
  CampaignType,
  RouteScope,
} from "@/lib/taxonomy.gen";

export interface SourceOut {
  id: string;
  name: string;
  url: string;
  category: string;
  trust_weight: number;
  /** official | regulator | agency | trade | aggregator -- the EFFECTIVE tier,
   * never null. The backend resolves an undeclared `Source.tier` through its
   * trust_weight the same way the Risk Radarı's chronology does, so a card and
   * that drawer can never badge the same outlet differently. Never "official"
   * unless a source declared it. */
  tier: string;
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
  /** low | medium | high, or null for a story the classifier read as carrying
   * no risk. Null on the great majority of rows: a badge a row may earn, never
   * a field a row is expected to have. */
  risk_severity: string | null;
  /** "Neden önemli?" -- one or two Turkish sentences the LLM wrote about what
   * this story means for a revenue-management desk. Null on nearly every row
   * by design: it costs a second model call, so only the day's few
   * highest-scoring stories earn one. The drawer renders the block when it is
   * there and omits it entirely otherwise. */
  why_important_tr: string | null;
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

/** `GET /articles/{id}/sources` -- every outlet that ran this story, oldest
 * first. This is the list behind `corroborating_source_count`: the same
 * duplicate group backend/app/pipeline/verify.py counts to produce that
 * number, so the two can never disagree. Fetched lazily, per article opened. */
export interface ArticleSourceOut {
  source_name: string;
  /** official | regulator | agency | trade | aggregator. Never null. */
  source_tier: string;
  trust_weight: number;
  url: string;
  published_at: string | null;
  title: string;
  /** The canonical article -- the one the Gazete publishes. The rest are the
   * corroboration. */
  is_primary: boolean;
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

  /* --- Kampanya İstihbaratı (PR1-PR7) -----------------------------------
   *
   * Computed at read time, never stored: a status column would be stale every
   * morning until a cron caught up. Everything else below is NULL on the ~200
   * legacy rows and stays NULL -- the analyst table renders "—" for an
   * unclassified campaign rather than inventing a type for it, so none of
   * these may be treated as guaranteed content. */
  status: CampaignStatus;
  campaign_type: CampaignType | null;
  business_class: CampaignBusinessClass | null;
  route_scope: RouteScope | null;
  /** "IST-LHR", set only when route_scope is OND. */
  ond: string | null;
  origin_code: string | null;
  dest_code: string | null;
  /** {"origin": {airport, city, country, region}, "dest": {...}} */
  route_json: CampaignRouteJson | null;
  confidence_score: number | null;
  /** high | medium. Low never reaches this endpoint; null means never assessed. */
  confidence_band: string | null;
  review_required: boolean | null;
  conflict_detected: boolean | null;
  classification_reason: string | null;
  first_seen_at: string | null;
  last_changed_at: string | null;
  /** cabin, promo_code, currency, price_floor, discount_type, ... */
  attrs_json: Record<string, unknown> | null;
  /** {field: {value, source_text, confidence}} -- the drawer quotes source_text. */
  evidence_json: Record<string, CampaignEvidence> | null;
  /** e.g. {"inferred_year": true} when the page said "30 Eylül" with no year. */
  date_flags_json: Record<string, unknown> | null;
  /** Recorded edits, and how many pages told us about this campaign. */
  version_count: number;
  source_count: number;
}

export interface CampaignRouteLeg {
  airport?: string | null;
  city?: string | null;
  country?: string | null;
  region?: string | null;
}

export interface CampaignRouteJson {
  origin?: CampaignRouteLeg | null;
  dest?: CampaignRouteLeg | null;
}

/** One field's provenance: what we read, and the sentence we read it from. */
export interface CampaignEvidence {
  value?: unknown;
  source_text?: string | null;
  confidence?: number | null;
}

/** `GET /promotions/{id}/versions` -- what changed, newest edit first.
 *
 * A campaign page is edited in place (the URL never moves), so an in-place row
 * update would erase the single fact a revenue desk most wants: that the rival
 * moved. Each accepted change is a row here instead. */
export interface PromotionVersion {
  version_no: number;
  changed_fields: Record<string, PromotionFieldChange>;
  source_url: string | null;
  created_at: string;
}

export interface PromotionFieldChange {
  previous?: unknown;
  new?: unknown;
  /** True when two sources disagreed and the more official one won. */
  conflict?: boolean;
  /** The losing value, kept on the record rather than discarded. */
  rejected?: unknown;
}

/** `GET /promotions/{id}/sources` -- every page that told us, most official
 * first. `source_tier` is the ordering that decided who won a conflict. */
export interface PromotionSource {
  url: string;
  source_name: string | null;
  /** official | newsroom | secondary */
  source_tier: string | null;
  source_quality: number | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

/** `GET /promotions/count` -- how many rows the same filters would list. */
export interface PromotionCountOut {
  total: number;
}

/** `GET /campaign-alerts` (PR6). Unacknowledged, CRITICAL first.
 *
 * The strip that renders these degrades to nothing at all when the endpoint is
 * missing: alerts are an addition to the page, never a precondition for it. */
export interface CampaignAlert {
  id: string;
  promotion_id: string;
  alert_type: "NEW" | "CHANGE" | "EXPIRING" | "EXPIRED" | "LOW_CONFIDENCE";
  priority: "CRITICAL" | "HIGH" | "MEDIUM" | "INFO";
  title_tr: string;
  detail_json: Record<string, unknown> | null;
  created_at: string;
}

/** `GET /promotions/new-count` -- a count over the whole table rather than
 * over whatever fell inside the timeline's eight-week window. */
export interface PromotionNewCountOut {
  window_hours: number;
  count: number;
  airline_codes: string[];
}

/* --- Risk Radarı (backend/app/api/v1/risks.py) --------------------------- */

/** An airport NAMED IN the coverage of a signal -- never one we claim is
 * affected by it. There is no schedule or operations feed behind this product,
 * so the UI label is "Anılan havalimanları" and never "etkilenen". */
export interface RiskAirportRef {
  code: string;
  name: string;
}

/** One article inside a signal's cluster: a telling of the event. */
export interface RiskMember {
  title: string;
  url: string;
  source_name: string;
  /** official | regulator | agency | trade | aggregator. */
  source_tier: string;
  published_at: string | null;
}

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
  /** The primary article's Turkish summary. Null -- never "" -- when the
   * enrichment produced none, so the card can leave the slot out entirely
   * instead of rendering a blank paragraph. */
  summary_tr: string | null;
  confidence_score: number | null;
  corroborating_source_count: number | null;
  /** PUBLICATION span of the cluster: first and last time somebody wrote about
   * it. Not the event's own start and end -- nothing upstream knows when an
   * earthquake began, only when it was reported. */
  first_reported_at: string | null;
  last_reported_at: string | null;
  /** First telling older than 24h, newest one inside it: "still being written
   * about". A statement about coverage, never a lifecycle status -- there is
   * no active/contained/resolved anywhere in this data. */
  is_updated: boolean;
  airports: RiskAirportRef[];
  /** "direct" | "indirect" -- how close the coverage sits to aviation (an
   * aviation-operational event type, or an airport named). A link-strength
   * hint, NOT an impact score. */
  aviation_link: string;
  /** The publication chronology, oldest first. Capped server-side. */
  members: RiskMember[];
  members_truncated: boolean;
  /** "normal" | "low" -- how loudly the page may state this signal. Decided
   * server-side from the confidence score and the number of corroborating
   * outlets (see backend/app/api/v1/risks.py CONFIDENCE GATING); items below
   * the publish floor never arrive here at all. "low" items are rendered
   * de-emphasised in a collapsed block, never hidden. */
  visibility: string;
  /** The source-language headline, when `headline` is a translation of it.
   * Null when the two are the same string -- there is nothing to reveal. */
  headline_original: string | null;
  /** Whether `headline` is translator-produced Turkish. False means the card
   * is showing source-language text, which the page says out loud with the
   * app's "otomatik çeviri yok" tag rather than letting it pass as Turkish. */
  is_translated: boolean;
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
  /** How many signals the confidence floor removed from this window. Served so
   * the page can state it: a list that quietly drops rows is a list whose
   * counts nobody can reconcile. */
  suppressed_low_confidence: number;
  countries: RiskCountry[];
  type_counts: Record<string, number>;
  family_counts: Record<string, number>;
  /** When the rollup was computed -- the page's freshness stamp. Distinct from
   * the newest article's timestamp, which is a different number and is shown
   * separately. */
  generated_at: string;
}

/** One (day, family, severity) bucket of the publication-volume series. */
export interface RiskTrendPoint {
  /** UTC day, "YYYY-MM-DD". */
  day: string;
  family: string;
  severity: string;
  /** ARTICLES published that day, not events that happened that day. */
  count: number;
}

export interface RiskTrendOut {
  days: number;
  points: RiskTrendPoint[];
  /** The backend's own sentence about what the series counts. Rendered as the
   * chart's caption rather than restated in the component, so the API and the
   * page can never disagree about it. */
  note: string;
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
  /** The date this forecast is FOR -- derived server-side purely so a chart
   * has an x coordinate for the marker, never published by the institution.
   * `horizon_label` above stays the only thing the table prints. null where
   * the wording supports no honest date, in which case the row appears in the
   * table and simply has no marker on the chart. */
  target_date: string | null;
  /** How `target_date` was arrived at, for the marker's tooltip. */
  target_date_basis_tr: string | null;
}

/** One row of "Yakıt & Enerji". Mirrors `EnergyMetricOut` in
 * backend/app/schemas/kokpit.py: every percentage is arithmetic over that
 * contract's own daily closes, and every null means the series does not
 * support the figure -- never zero. */
export interface EnergyMetricOut {
  metric_key: string;
  label_tr: string;
  unit: string;
  value: number | null;
  as_of: string | null;
  day_change_pct: number | null;
  week_change_pct: number | null;
  month_change_pct: number | null;
  ytd_change_pct: number | null;
  /** 0-100: where today's close sits inside its own last year of closes. */
  percentile_1y: number | null;
  /** Annualised REALISED volatility over ~21 sessions. Not implied -- there is
   * no options data in this system. */
  volatility_30d_pct: number | null;
  sparkline: number[];
  source: string;
  source_url: string;
  href: string;
  is_estimate: boolean;
  note_tr: string | null;
}

export interface EnergyBoardOut {
  metrics: EnergyMetricOut[];
  volatility_method_tr: string;
  percentile_method_tr: string;
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
  /** What the previous edition of the same IATA report printed for this period.
   * Null on actuals and on forecasts whose prior edition is unverified. */
  previous_value: number | null;
  previous_publication_date: string | null;
  previous_source_url: string | null;
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

/** One "Sinyal Panosu" tile. Deliberately NOT a score -- see
 * backend/app/services/cockpit_signals_service.py for why four stated drivers
 * beat one blended number, and for the threshold tables behind `level`. */
export interface CockpitSignal {
  key: "fx" | "fuel" | "risk" | "competitor";
  label_tr: string;
  /** `unknown` is not a band: it means the driver could not be read at all,
   * and must never render as a green "all clear". */
  level: "good" | "warning" | "critical" | "unknown";
  level_label_tr: string;
  /** Already formatted server-side, so the tile's headline number and the
   * sentence beneath it can never round differently. */
  value_label: string;
  reason_tr: string;
  method_tr: string;
  source: string;
  source_url: string | null;
  href: string | null;
  as_of: string | null;
}

export interface CockpitSignalsOut {
  signals: CockpitSignal[];
  generated_at: string;
}

/** One year of an IATA industry series. `kind` is why the chart draws the tail
 * dashed: 2026 is a forecast and 2025 an estimate in IATA's June 2026 report. */
export interface AnnualPoint {
  year: number;
  value: number;
  kind: "actual" | "estimate" | "forecast";
}

export interface AnnualSeries {
  metric_key: string;
  label_tr: string;
  unit: string;
  up_is_good: boolean;
  points: AnnualPoint[];
}

export interface AnnualSeriesBoardOut {
  series: AnnualSeries[];
  source: string;
  source_url: string;
  /** "sektör geneli · yıllık · ..." -- the caveat every surface showing these
   * numbers must print, so none of them can read as company figures. */
  scope_tr: string;
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
