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
  importance_score: number;
  sentiment: string;
  confidence_score: number;
  corroborating_source_count: number;
  verified_at: string | null;
  tags: string;
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
