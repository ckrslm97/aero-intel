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
