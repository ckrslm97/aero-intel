import type {
  CampaignBusinessClass,
  CampaignKind,
  CampaignStatus,
  CampaignType,
  PeriodKind,
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
  /** How much the story matters to a REVENUE-MANAGEMENT desk, 0-1 -- eight
   * weighted sub-scores (backend/app/services/news_scoring.py). This is what
   * `importance_score` above should have been: that column reduces, at the
   * corroboration count every production row actually has, to
   * `0.34 + 0.21 * source.trust_weight` -- a restatement of which outlet
   * published the story, containing no term for the story.
   *
   * Null on rows the scoring pass never reached, so it must stay optional to
   * read. Null is "not judged", never "judged unimportant". */
  intelligence_score: number | null;
  /** The model's three impact axes, 0-1 each.
   *
   * NULL AND 0.0 MEAN DIFFERENT THINGS. Only the day's shortlist is scored by
   * the model, so null is the common case and means "nobody looked"; 0.0 means
   * the model read the article and found no impact on that axis. The drawer
   * renders an absence as an absence -- a "0" chip on an article nobody scored
   * would be a claim the system never made. */
  rm_impact: number | null;
  demand_impact: number | null;
  capacity_impact: number | null;
  /** The sub-scores and the weights that combined them, as stored -- so the
   * drawer can say WHY a story scored what it did without a second endpoint.
   * See `ScoreDetail` in lib/gazete.ts for the shape, and read it defensively:
   * a row scored by an older version of the scorer is still a row. */
  score_detail: Record<string, unknown> | null;
  sentiment: string;
  /** Cross-source confidence, 0-1 -- or null when nothing ever scored this
   * article.
   *
   * The backend column is NOT NULL and defaults to 0.0, so a row the
   * confidence pass never reached is STORED identically to one scored at rock
   * bottom. The schema now separates them (backend/app/schemas/article.py) and
   * publishes the unmeasured as null, because the drawer was banding that 0.0
   * and printing "Düşük güven · %0" over an article nobody had assessed.
   * Render the absence as an absence. */
  confidence_score: number | null;
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

/** `GET /articles/source-facets` -- which outlets actually filled the current
 * window, busiest first.
 *
 * The options behind the Gazete's "Kaynak adı" chip row. `name` is the exact
 * `Source.name` string `?source=` matches on, which is what makes a chip safe
 * to send blind: it cannot ask for an outlet the filter would miss. Counted
 * server-side because the list is paginated -- chips derived from the thirty
 * rows on screen would describe page 1, not the window. */
export interface ArticleSourceFacetOut {
  name: string;
  /** The EFFECTIVE tier, resolved exactly as `SourceOut.tier` is. */
  tier: string;
  count: number;
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

/** A KPI's movement is reported EITHER as a percent OR as points, never both.
 *
 * A load factor going 83.0 -> 83.4 rose 0.4 POINTS; the percent form (0.48) is
 * arithmetically true and is not what an airline means by "doluluk arttı". So
 * for a metric already denominated in points (`unit === "%"`) the backend
 * sends `delta_pct: null` and fills `delta_points`; every other unit is the
 * other way round. Read whichever is non-null -- `kpiDeltaLabel` in
 * lib/format.ts does that once, beside the two formatters it picks between. */
export interface KpiOut {
  metric_key: string;
  label: string;
  value: number;
  unit: string;
  delta_pct: number | null;
  delta_points: number | null;
  up_is_good: boolean;
  trend: number[];
  is_estimate: boolean;
  as_of: string;
  /** Same-metric value from LY (2025), when the backend has one. */
  ly_value: number | null;
  /** Percent change vs LY (2025). Null for a point-denominated metric. */
  ly_delta_pct: number | null;
  /** Point change vs LY (2025), for point-denominated metrics. */
  ly_delta_points: number | null;
  /** "2025 (LY)'e göre" when LY exists, else "önceki ölçüme göre". */
  comparison_label: string;
  /** What period `value` describes: "2026 · tahmin" for an IATA annual figure,
   * "son ölçüm" for a live reading. */
  period_label: string | null;
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
  /** When the CORROBORATING reading was taken -- compare against
   * `KpiDetailOut.as_of`, which is when the primary's was. */
  as_of: string;
  /** Null when the two readings could not be compared at all. Never 0: a
   * comparison that did not happen has no number, and 0 is the strongest
   * agreement this scale can express. */
  diff_pct: number | null;
  /** The verdict, decided on the backend (the 0.5% rule used to live in this
   * component). Render `verdict_label_tr` rather than re-deriving it. */
  verdict: "match" | "diverges" | "incomparable";
  verdict_label_tr: string;
  /** Why the comparison was refused: "no_primary_value" |
   * "as_of_too_far_apart". Null when `diff_pct` was computed. */
  incomparable_reason: string | null;
}

/** Where a detail chart's history came from. Three answers, not two:
 * `derived_external` is a REAL external archive belonging to a DIFFERENT
 * instrument, transformed by a stated rule -- jet fuel is Brent's published
 * closes plus IATA's crack spread, and nobody publishes that series. Calling
 * it "the source's own archive" claimed a history that exists nowhere. */
export type KpiHistoryProvenance = "source_archive" | "derived_external" | "own_history";

export interface KpiDetailOut {
  metric_key: string;
  label: string;
  value: number;
  unit: string;
  /** See the note on KpiOut: null for a point-denominated metric. */
  delta_pct: number | null;
  delta_points: number | null;
  up_is_good: boolean;
  is_estimate: boolean;
  as_of: string;
  /** What period `value` describes -- "2026 · tahmin" for an annual forecast.
   * Without it a projection for an unfinished year read as a spot reading. */
  period_label: string | null;
  /** What the delta is measured against. Null when there is no delta. */
  comparison_label: string | null;
  source: string;
  source_url: string | null;
  corroborations: KpiCorroborationOut[];
  /** The threshold the verdicts were decided on, so the page can state the
   * rule instead of asserting it. */
  corroboration_match_pct: number | null;
  history: KpiHistoryPointOut[];
  /** `history_provenance !== "own_history"`. Kept for older readers; the
   * three-state field below is what to read. */
  history_is_external: boolean;
  history_provenance: KpiHistoryProvenance;
  /** The sentence to print under the chart, written where the derivation is
   * known rather than reassembled here. */
  history_provenance_tr: string | null;
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
  /** IATA codes the event's traffic actually uses, from the curated table in
   * backend/app/data/event_airports.py. Empty for entries that are not cities
   * ("Çin geneli", "Küresel") -- resolving them automatically produced wrong
   * airports, so an empty list is the honest answer. */
  relevant_airports: string[];
  /** 0-1, or null when the organiser publishes no headcount. Null means "not
   * measurable", never "small": the backend refuses to score an event with no
   * attendance rather than treating it as zero. Render it as a dash. */
  importance_score: number | null;
  /** Signed days to the start -- negative for an event already under way,
   * which the calendar keeps because it filters on the end date. */
  days_until: number;
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
  /** The structured markets the flat string above cannot express. Null on a
   * legacy row -- an unextracted campaign names no market, which is not the
   * same claim as naming none.
   *
   * Serialised because the export and the screen were selecting different
   * rows without it: the backend's `_countries_of`/`_regions_of` read this
   * column, so `country=almanya` matched campaigns the on-screen chip could
   * not even offer. */
  markets_json: { countries?: string[]; regions?: string[] } | null;
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

  /* --- Kampanya v2 (PR #72) ---------------------------------------------
   *
   * `campaign_kind` says whether the offer is a PRICE (CAMPAIGN) or a
   * MECHANISM (PROMOTION). Null on the ~39 legacy rows that were never
   * classified at all -- those rows have no `campaign_type` either, and the
   * page shows them as unclassified rather than guessing a kind. */
  campaign_kind: CampaignKind | null;
  /** A ticketing deadline the carrier stated SEPARATELY from the sale window.
   * Filled in almost never, and that is the information: an empty pair means
   * nobody published one, never that it equals the booking window. */
  ticketing_start: string | null;
  ticketing_end: string | null;
  /** The campaign's own announced period, when the carrier published one that
   * is neither the sale nor the travel window. */
  campaign_start: string | null;
  campaign_end: string | null;
  /** Does the carrier itself have a source row at tier `official`?
   *
   * Computed per request by the API, never stored. False on a legacy row is
   * honest rather than pessimistic -- nobody ever filed a source for it, so
   * nobody ever verified it. */
  official_source_verified: boolean;

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

  // --- verification evidence (backend spec §7-17) --------------------------
  //
  // Optional on this interface, not because the API omits them, but because a
  // cached response served from before they existed does not carry them, and
  // a page that renders `undefined` as a confident 0 would be asserting a
  // measurement nobody made. Every consumer must handle null/undefined as
  // "unscored", never as "scored low" -- which is the same rule the three
  // backend gates follow.

  /** How much the placement is worth, 0-1. Null when nothing resolved. Below
   * the backend's threshold `country`/`city` arrive BLANKED and the signal is
   * filed under "Belirtilmemiş", so the map never pins a guess. */
  location_confidence?: number | null;
  /** Whether this signal earned a map pin. False means the list shows it and
   * the map does not. */
  is_mappable?: boolean;
  /** Every place the coverage named, with the role it played: "event" is the
   * scene, "source" is a dateline or a government quote, "unverified" is a
   * mention whose role could not be tested. The audit trail behind a blanked
   * placement. */
  mentioned_locations?: RiskMentionedLocation[];
  /** 0-1: how directly this event touches flying, as opposed to how often the
   * coverage says the word "airline". Null when nothing scored it. */
  aviation_relevance_score?: number | null;
  /** "llm" | "heuristic" | "unscored" -- which pass produced the score. */
  aviation_relevance_source?: string | null;
  /** The sentence the score was read off, in the article's own words. */
  aviation_impact_evidence?: string | null;
  /** "ACTUAL" | "POTENTIAL" -- reported, or forecast. Not a severity. */
  aviation_impact_status?: string | null;
}

export interface RiskMentionedLocation {
  name: string;
  /** "country" | "city" | "unknown" */
  kind: string;
  /** "event" | "source" | "unverified" */
  role: string;
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
  /** How many signals the confidence gate removed from this window. Served so
   * the page can state it: a list that quietly drops rows is a list whose
   * counts nobody can reconcile. */
  suppressed_low_confidence: number;
  /** How many signals were measured and found to have no operational bearing
   * on flying. Separate from the line above because they are different
   * rejections and one merged number would hide which rule is doing the work. */
  suppressed_aviation_irrelevant?: number;
  /** How many ARTICLES (not signals -- the filter runs before clustering) a
   * classifier marked as not-current: anniversaries, retrospectives, analysis
   * pieces. */
  suppressed_not_current?: number;
  /** How many PUBLISHED signals the map will not pin because their placement
   * scored too low. They are in `countries` under "Belirtilmemiş", not
   * missing -- this is what lets the page explain why the map shows fewer
   * markers than the list shows rows. */
  unplaced_low_confidence?: number;
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

/* `GET /kokpit/pulse`'s response shape used to be typed here. Kokpit V2 prints
 * no generated prose at all -- the owner asked for glyphs, not paragraphs -- so
 * `MarketPulseCard` and with it the last consumer of that endpoint is gone. The
 * ENDPOINT is deliberately untouched: `market_pulse_service` and its tests
 * still live, and the types come back with the first surface that needs them.
 */

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
  /** `year_kind`'s own three values (backend/app/ingest/historical_seed.py),
   * named once in app/taxonomy.py so the label beside the number comes from
   * the same place as the number's kind. */
  kind: PeriodKind;
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
  /** World-region slug, carried so the Sinyaller aggregate can put a region on
   * a card without a second query. */
  region: string | null;
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
  /** Every event in the window, not `events.length`. */
  count: number;
  events: BizEventOut[];
  /** True when `events` is the newest slice of `count` rather than all of it
   * (backend/app/services/biz_service.py). Declared here so a section that
   * lists ten rows under a headline reading 40 can say why -- no surface
   * renders competitor_signals yet. */
  events_truncated: boolean;
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

/* --- Sinyaller (backend/app/schemas/signals.py) --------------------------- */

/** market | risk | competitor | financial -- the four filter buckets. Which
 * real stream reaches each is documented in
 * backend/app/services/signals_service.py; nothing is detected on this page. */
export type SignalKind = "market" | "risk" | "competitor" | "financial";

/** `unknown` is not a band: it means the driver could not be read at all, and
 * must never render as an all-clear. */
export type SignalSeverity = "critical" | "high" | "medium" | "low" | "unknown";

/** One row of the early-warning list, from whichever stream produced it.
 *
 * Every field is carried FROM a stream rather than computed as a new judgement
 * about it. `severity` in particular is a band the owning stream already
 * published -- a campaign alert's priority, a risk cluster's severity, a
 * Kokpit tile's level -- and `severity_basis_tr` says which. A stream that
 * publishes no severity is mapped to `low` and says so in that sentence,
 * rather than being given a number this page invented. */
export interface SignalOut {
  id: string;
  /** Which of the seven streams produced this row. */
  stream: string;
  kind: SignalKind;
  kind_label_tr: string;
  /** What kind of thing this is inside its stream ("Yeni hat", "Kur Riski"). */
  type_label_tr: string;
  severity: SignalSeverity;
  severity_label_tr: string;
  /** How the severity was arrived at, verbatim -- the card's ⓘ note. */
  severity_basis_tr: string;
  title_tr: string;
  detail_tr: string | null;
  /** World-region slug, where the stream resolved one. */
  region: string | null;
  /** IATA codes the signal is about. Empty for a macro signal. */
  airline_codes: string[];
  /** Null where the stream is a rolling window with no point reading -- never
   * defaulted to now, so an undated row cannot lead a recency sort. */
  detected_at: string | null;
  /** 0-1, only where the owning stream actually carries one. Never
   * synthesised: a campaign alert has no confidence, a risk cluster does. */
  confidence_score: number | null;
  source_label: string;
  /** In-app drill-down, or null where no page owns this stream any more. */
  href: string | null;
}

/** One contributing stream, present whether or not it produced anything -- the
 * same structural no-filler rule the Biz sections use, so a reader can tell
 * "nothing happened" from "it broke". */
export interface SignalStreamOut {
  key: string;
  label_tr: string;
  kind: SignalKind;
  count: number;
  available: boolean;
  empty_message: string | null;
}

export interface SignalsOut {
  days: number;
  total: number;
  signals: SignalOut[];
  streams: SignalStreamOut[];
  /** When the composition ran -- a fact about the response, not about the
   * newest signal in it. */
  generated_at: string;
}

// --- Risk Radarı doğrulama ekranı (backend spec §23-24) --------------------
//
// The two payloads behind /risk-radari/dogrulama. They answer the questions
// the radar itself cannot: "is what I see six out of six, or six out of
// forty", and "why is THIS story not here". Both are read-only aggregates
// computed per request; nothing about a rejection is stored, so these types
// describe a snapshot and never a history.

/** One line of the funnel. Each stage is a subset of the one above it, and
 * `passed + dropped` equals the previous stage's `passed` -- the arithmetic a
 * reader uses to get from "toplam makale" to "sinyal" without a leap of
 * faith. */
export interface RiskFunnelStage {
  key: string;
  label_tr: string;
  passed: number;
  dropped: number;
  /** The rejection slug the dropped rows carry. Null when the drop is not a
   * rejection: the first stage has nothing above it, `risk_adayi` drops
   * ordinary news, and `kume` MERGES rather than removes.
   *
   * Only the FIRST slug when a stage carries several -- the location gate
   * splits into unresolved and conflict -- so anything that filters must read
   * `reason_counts`, never this. */
  reason: string | null;
  /** reason -> how many of `dropped` carry it, summing to `dropped`. Empty
   * when the drop is not a rejection. This is what a filter chip's label and
   * its result are both built from, so the two cannot disagree. */
  reason_counts: Record<string, number>;
  /** "rejected" | "merged" | null. The distinction the screen must not blur --
   * a merged cluster is still on the radar and a rejected article is not. */
  drop_kind: string | null;
  note_tr: string | null;
}

/** One risk candidate the gates removed, with the values the rule read. */
export interface RiskRejection {
  article_id: string;
  title: string;
  url: string;
  source_name: string;
  /** official | regulator | agency | trade | aggregator. */
  source_tier: string;
  published_at: string | null;
  reason: string;
  reason_label_tr: string;
  /** Every OTHER gate this row would also have failed. Empty is the good
   * case: fix the one rule and the article appears. */
  also_failed: string[];
  /** Every row-level gate's verdict, pass AND fail: currency | confidence |
   * aviation | location.
   *
   * `reason` and `also_failed` list only the failures, so a table built on
   * them could not tell "rejected for currency, clean otherwise" from
   * "rejected for currency, three gates never evaluated" -- an absent verdict
   * and a passing one rendered the same. */
  gates: Record<string, boolean>;
  /** Whether the confidence gate published this row. Separate from `gates`
   * because it is the only gate with an exemption ladder rather than a
   * threshold, and the pass alone does not say which rung carried it. */
  confidence_gate_passed: boolean;
  /** Which rung decided it: "corroborated" | "unscored" | "scored" |
   * "official" | "below_gate". The one that must be visible is "unscored":
   * a row published because nobody measured it did not pass anything, and a
   * null `confidence_score` is only half of that sentence. */
  confidence_gate_reason: string;
  risk_type: string | null;
  risk_severity: string | null;
  confidence_score: number | null;
  corroborating_source_count: number | null;
  aviation_relevance_score: number | null;
  aviation_relevance_source: string | null;
  location_confidence: number | null;
  /** What the resolver decided the place was, BEFORE the map gate blanked it.
   * /risks blanks a weak placement on purpose; this screen is the one place
   * the rejected answer stays visible, or a wrong placement cannot be told
   * apart from an absent one. */
  detected_country: string | null;
  detected_city: string | null;
  mentioned_locations: RiskMentionedLocation[];
}

export interface RiskQualityOut {
  days: number;
  generated_at: string;
  since: string;
  stages: RiskFunnelStage[];
  /** Rejections per reason, UNCAPPED -- so a truncated table can still say how
   * much of the whole it is showing. */
  rejected_counts: Record<string, number>;
  reason_labels_tr: Record<string, string>;
  /** How much of each gate's yield is carried by rows nobody measured. A gate
   * passing everything unscored is a gate not yet doing anything. */
  aviation_unscored: number;
  location_unscored: number;
  confidence_unscored: number;
  aviation_by_source: Record<string, number>;
}
