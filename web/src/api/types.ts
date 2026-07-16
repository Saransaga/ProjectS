export type Action = "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL";
export type OutcomeStatus = "OPEN" | "HIT_TARGET" | "HIT_STOP" | "EXPIRED";
export type Freshness = "FRESH" | "DUE" | "STALE" | "UNKNOWN";
export type Horizon = "short" | "long";

export interface RationaleComponent {
  name: string;
  subscore: number | null;
  weight: number;
  weighted: number | null;
  detail: Record<string, unknown>;
}

export interface Rationale {
  weighted_score: number | null;
  available_weight: number;
  insufficient_data: boolean;
  components: RationaleComponent[];
}

export interface RecommendationListItem {
  instrument_id: number;
  symbol: string;
  name: string;
  sector: string | null;
  score: number | null;
  action: Action | null;
  rationale: Rationale | null;
}

export interface RecommendationListResponse {
  as_of_date: string | null;
  total: number;
  items: RecommendationListItem[];
}

export interface PriceLevel {
  price: number;
  strength: number | null;
  projected: boolean;
}

export interface RecommendationDetail {
  as_of_date: string;
  short_term_score: number | null;
  short_term_action: Action | null;
  short_term_rationale: Rationale | null;
  long_term_score: number | null;
  long_term_action: Action | null;
  long_term_rationale: Rationale | null;
  short_term_top_reasons: string[];
  long_term_top_reasons: string[];
  short_term_price_targets: { target: PriceLevel | null; stop: PriceLevel | null };
  atr_14: number | null;
}

export interface RecommendationDetailResponse {
  instrument: { instrument_id: number; symbol: string; name: string; sector: string | null };
  close: { trade_date: string; close: number } | null;
  recommendation: RecommendationDetail | null;
}

export interface OutcomeSummary {
  counts: Record<OutcomeStatus, number>;
  total: number;
  win_rate: number | null;
  avg_days_to_resolution: number | null;
}

export interface OutcomeBreakdown {
  action?: Action;
  component?: string;
  counts: Record<OutcomeStatus, number>;
  total: number;
  win_rate: number | null;
}

export interface OpenPosition {
  instrument_id: number;
  symbol: string;
  name: string;
  as_of_date: string;
  action: Action;
  dominant_component: string | null;
  entry_close: number;
  target_price: number | null;
  target_is_projected: boolean;
  stop_price: number | null;
  stop_is_projected: boolean;
  status: OutcomeStatus;
  trading_days_elapsed: number;
  resolved_date: string | null;
  resolved_close: number | null;
  latest_close: number | null;
}

export interface JobCadence {
  cadence: "INTRADAY" | "DAILY" | "WEEKLY" | "MONTHLY";
  grace_hours: number;
  minutes?: number;
  hour?: number;
  day_of_week?: number;
  day_of_month?: number;
  market_hours_only?: boolean;
}

export interface JobFreshness {
  job_name: string;
  run_date: string;
  status: string;
  rows_ingested: number | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  last_success_finished_at: string | null;
  freshness: Freshness;
  cadence: JobCadence | null;
}

export interface SourceHealthItem {
  source_type: string;
  item_count: number;
  credibility_weight: number | null;
  latest_published_at: string | null;
}

export interface JobRowsHealth {
  job_name: string;
  successful_runs: number;
  total_rows_ingested: number;
  avg_rows_per_run: number | null;
}

export interface SourceHealthResponse {
  window_days: number;
  news_sources: SourceHealthItem[];
  jobs: JobRowsHealth[];
}

export interface RoadmapItem {
  domain: string;
  title: string;
  status: "DEFERRED" | "DROPPED";
  description: string;
  source_related: boolean;
}
