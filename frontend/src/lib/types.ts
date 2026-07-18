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
}

export interface ArticleListOut {
  total: number;
  items: ArticleOut[];
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

/* ------------------------------------------------------------------ */
/* /invest -- fund/ETF intelligence module (backend/app/schemas/fund.py) */
/* ------------------------------------------------------------------ */

export type VerificationStatus =
  | "verified"
  | "official_single_source"
  | "single_source"
  | "discrepancy";

export type FundMarket = "us" | "tr";

export type FundPeriod = "1m" | "3m" | "6m" | "1y";

export type FundOutlook = "positive" | "neutral" | "cautious";

export interface FundOut {
  symbol: string;
  name: string;
  market: FundMarket;
  currency: string;
  issuer: string;
  target_weight: number;
  /** Latest close/NAV; null until the first successful refresh. */
  value: number | null;
  as_of: string | null;
  /** Percent change vs previous primary observation. */
  delta_pct: number | null;
  /** Sparkline values, oldest first. */
  trend: number[];
  /** Verification status of the latest price row. */
  verification_status: VerificationStatus | null;
  metadata_verified: boolean;
}

export interface FundHistoryPointOut {
  as_of: string;
  value: number;
}

export interface FundHistoryOut {
  symbol: string;
  period: FundPeriod;
  currency: string;
  points: FundHistoryPointOut[];
}

export interface FundCorroborationOut {
  source: string;
  source_url: string | null;
  value: number;
  as_of: string;
  diff_pct: number;
}

export interface FundAnalysisOut {
  body_tr: string;
  outlook: FundOutlook;
  /** "openai_compat" | "heuristic" */
  provider: string;
  analysis_date: string;
  disclaimer: string;
}

export interface FundDetailOut {
  symbol: string;
  name: string;
  market: FundMarket;
  currency: string;
  issuer: string;
  target_weight: number;
  expense_ratio: number | null;
  aum: number | null;
  aum_as_of: string | null;
  metadata_source: string;
  metadata_verified: boolean;
  value: number | null;
  as_of: string | null;
  delta_pct: number | null;
  source: string | null;
  source_url: string | null;
  verification_status: VerificationStatus | null;
  corroborations: FundCorroborationOut[];
  analysis: FundAnalysisOut | null;
  disclaimer: string;
}

export interface FundHoldingOut {
  rank: number;
  ticker: string | null;
  holding_name: string;
  weight_pct: number;
  sector: string | null;
}

export interface FundAllocationOut {
  /** "asset_class" | "sector" */
  kind: string;
  label: string;
  weight_pct: number;
}

export interface FundHoldingsOut {
  symbol: string;
  as_of: string | null;
  source: string | null;
  verification_status: VerificationStatus | null;
  is_top10_only: boolean;
  holdings: FundHoldingOut[];
  allocations: FundAllocationOut[];
  allocations_as_of: string | null;
}

export interface PortfolioFundOut {
  symbol: string;
  name: string;
  target_weight: number;
  value: number | null;
  as_of: string | null;
  return_1y_pct: number | null;
  verification_status: VerificationStatus | null;
}

export interface PortfolioOut {
  market: string;
  funds: PortfolioFundOut[];
  /** null until every member fund has a full year of history. */
  weighted_return_1y_pct: number | null;
  analysis: FundAnalysisOut | null;
  disclaimer: string;
}

export interface PortfoliosOut {
  us: PortfolioOut;
  tr: PortfolioOut;
  disclaimer: string;
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
}
