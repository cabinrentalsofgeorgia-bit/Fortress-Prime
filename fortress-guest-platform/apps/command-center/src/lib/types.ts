export interface Property {
  id: string;
  name: string;
  slug: string;
  property_type: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string;
  wifi_ssid?: string;
  wifi_password?: string;
  access_code_type?: string;
  access_code_location?: string;
  parking_instructions?: string;
  streamline_property_id?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Guest {
  id: string;
  phone_number: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  total_stays: number;
  total_messages_sent?: number;
  total_messages_received?: number;
  language_preference: string;
  opt_in_marketing: boolean;
  preferred_contact_method?: string;
  tags?: string[];
  last_stay_date?: string;
  lifetime_value?: number;
  created_at: string;
}

export interface Reservation {
  id: string;
  confirmation_code: string;
  guest_id: string;
  property_id: string;
  check_in_date: string;
  check_out_date: string;
  num_guests: number;
  num_adults?: number;
  num_children?: number;
  status: "confirmed" | "checked_in" | "checked_out" | "cancelled" | "no_show";
  booking_source?: string;
  total_amount?: number;
  paid_amount?: number;
  balance_due?: number;
  nightly_rate?: number;
  cleaning_fee?: number;
  pet_fee?: number;
  damage_waiver_fee?: number;
  service_fee?: number;
  tax_amount?: number;
  nights_count?: number;
  price_breakdown?: Record<string, unknown>;
  pre_arrival_sent: boolean;
  access_info_sent: boolean;
  digital_guide_sent: boolean;
  mid_stay_checkin_sent?: boolean;
  checkout_reminder_sent?: boolean;
  post_stay_followup_sent?: boolean;
  access_code?: string;
  special_requests?: string;
  created_at: string;
  nights?: number;
  is_current?: boolean;
  is_arriving_today?: boolean;
  is_departing_today?: boolean;
  // Flat joined fields from API
  guest_name?: string;
  guest_phone?: string;
  guest_email?: string;
  property_name?: string;
  // Optional nested objects
  guest?: Guest;
  property?: Property;
}

export interface Message {
  id: string;
  external_id?: string;
  guest_id: string;
  direction: "inbound" | "outbound";
  phone_from: string;
  phone_to: string;
  body: string;
  intent?: string;
  sentiment?: string;
  status: string;
  is_auto_response: boolean;
  ai_confidence?: number;
  created_at: string;
  guest?: Guest;
}

export interface WorkOrder {
  id: string;
  ticket_number: string;
  property_id?: string;
  reservation_id?: string;
  guest_id?: string;
  title: string;
  description: string;
  category: string;
  priority: "low" | "medium" | "high" | "urgent";
  status: "open" | "in_progress" | "completed" | "cancelled";
  created_by?: string;
  assigned_to?: string;
  completed_at?: string;
  created_at: string;
  property?: Property;
}

export interface DashboardStats {
  total_properties: number;
  total_reservations?: number;
  active_reservations: number;
  arriving_today: number;
  departing_today: number;
  current_guests: number;
  total_guests?: number;
  total_messages?: number;
  occupancy_rate: number;
  messages_today: number;
  ai_automation_rate: number;
  open_work_orders: number;
  unread_messages: number;
  total_revenue_mtd?: number;
}

export interface FinancialSignalStateLabels {
  monthly: string;
  weekly: string;
  daily: string;
  momentum: string;
}

export interface FinancialLatestSignal {
  ticker: string;
  bar_date: string;
  parameter_set_id: string;
  parameter_set_name: string;
  dochia_version: string;
  monthly_state: -1 | 0 | 1;
  weekly_state: -1 | 0 | 1;
  daily_state: -1 | 0 | 1;
  momentum_state: -1 | 0 | 1;
  composite_score: number;
  computed_at: string;
  monthly_channel_high: string | number | null;
  monthly_channel_low: string | number | null;
  weekly_channel_high: string | number | null;
  weekly_channel_low: string | number | null;
  daily_channel_high: string | number | null;
  daily_channel_low: string | number | null;
  state_labels: FinancialSignalStateLabels;
}

export type FinancialTransitionType =
  | "peak_to_exit"
  | "exit_to_reentry"
  | "full_reversal"
  | "breakout_bullish"
  | "breakout_bearish";

export interface FinancialSignalTransition {
  id: string;
  ticker: string;
  parameter_set_name: string;
  transition_type: FinancialTransitionType;
  from_score: number;
  to_score: number;
  from_bar_date: string;
  to_bar_date: string;
  from_states: Record<string, number>;
  to_states: Record<string, number>;
  detected_at: string;
  acknowledged_by_user_id: string | null;
  acknowledged_at: string | null;
  notes: string | null;
}

export interface FinancialSymbolSignalDetail {
  ticker: string;
  latest: FinancialLatestSignal;
  recent_transitions: FinancialSignalTransition[];
}

export interface FinancialSignalChartBar {
  ticker: string;
  bar_date: string;
  open: string | number;
  high: string | number;
  low: string | number;
  close: string | number;
  volume: number | null;
  daily_channel_high: string | number | null;
  daily_channel_low: string | number | null;
  weekly_channel_high: string | number | null;
  weekly_channel_low: string | number | null;
  monthly_channel_high: string | number | null;
  monthly_channel_low: string | number | null;
}

export interface FinancialSignalChartEvent {
  ticker: string;
  timeframe: "daily" | "weekly" | "monthly";
  state: "green" | "red" | "neutral";
  bar_date: string;
  trigger_price: string | number;
  channel_high: string | number;
  channel_low: string | number;
  lookback_sessions: number;
  reason: string;
}

export interface FinancialSignalChartResponse {
  ticker: string;
  parameter_set_name: string;
  daily_trigger_mode: "close" | "range";
  sessions: number;
  bars: FinancialSignalChartBar[];
  events: FinancialSignalChartEvent[];
}

export type FinancialWhipsawRiskLevel = "quiet" | "elevated" | "high";

export interface FinancialWhipsawOutcome {
  horizon_sessions: number;
  evaluated_events: number;
  win_count: number;
  win_rate: number | null;
  average_directional_return: number | null;
  median_directional_return: number | null;
  p25_directional_return: number | null;
  p75_directional_return: number | null;
}

export interface FinancialWhipsawEvent {
  event_date: string;
  state: "green" | "red" | "neutral";
  sessions_since_previous: number | null;
  is_whipsaw: boolean;
  directional_return: number | null;
}

export interface FinancialWhipsawRiskResponse {
  ticker: string;
  parameter_set_name: string;
  daily_trigger_mode: "close" | "range";
  sessions: number;
  as_of: string | null;
  whipsaw_window_sessions: number;
  outcome_horizon_sessions: number;
  event_count: number;
  whipsaw_count: number;
  whipsaw_rate: number | null;
  latest_whipsaw_date: string | null;
  risk_score: number;
  risk_level: FinancialWhipsawRiskLevel;
  outcome: FinancialWhipsawOutcome;
  recent_events: FinancialWhipsawEvent[];
}

export interface FinancialPromotionGateCalibration {
  total_observations: number;
  covered_observations: number;
  accuracy: number | null;
  exact_event_accuracy: number | null;
  window_event_accuracy: number | null;
  coverage_rate: number | null;
  exact_coverage_rate: number | null;
  score_mae: number | null;
  score_rmse: number | null;
}

export interface FinancialPromotionGateModel {
  id: "production" | "candidate";
  label: string;
  parameter_set_name: string;
  daily_trigger_mode: "close" | "range";
  latest_bar_date: string | null;
  signal_count: number;
  bullish_count: number;
  risk_count: number;
  neutral_count: number;
  reentry_count: number;
  average_score: number | null;
  calibration: FinancialPromotionGateCalibration;
}

export interface FinancialPromotionGateDeltas {
  window_event_accuracy: number | null;
  exact_event_accuracy: number | null;
  coverage_rate: number | null;
  score_mae: number | null;
  signal_count: number;
  reentry_count: number;
}

export type FinancialPromotionGateGuardrailStatus = "pass" | "watch" | "fail";
export type FinancialPromotionGateRecommendationStatus = "hold" | "review" | "ready_for_shadow";

export interface FinancialPromotionGateGuardrail {
  id: string;
  label: string;
  status: FinancialPromotionGateGuardrailStatus;
  detail: string;
}

export interface FinancialPromotionGateRecommendation {
  status: FinancialPromotionGateRecommendationStatus;
  label: string;
  rationale: string;
}

export interface FinancialPromotionGateResponse {
  generated_at: string;
  candidate_parameter_set: string;
  baseline_parameter_set: string;
  since: string | null;
  until: string | null;
  event_window_days: number;
  production: FinancialPromotionGateModel;
  candidate: FinancialPromotionGateModel;
  deltas: FinancialPromotionGateDeltas;
  guardrails: FinancialPromotionGateGuardrail[];
  recommendation: FinancialPromotionGateRecommendation;
}

export interface FinancialWatchlistCandidate {
  ticker: string;
  bar_date: string;
  parameter_set_name: string;
  monthly_state: -1 | 0 | 1;
  weekly_state: -1 | 0 | 1;
  daily_state: -1 | 0 | 1;
  momentum_state: -1 | 0 | 1;
  composite_score: number;
  latest_transition_type: FinancialTransitionType | null;
  latest_transition_bar_date: string | null;
  latest_transition_notes: string | null;
  sector: string | null;
  watchlist_signal_count: number | null;
  watchlist_last_signal_at: string | null;
  legacy_action: string | null;
  legacy_signal_type: string | null;
  legacy_confidence_score: number | null;
  legacy_price_target: string | number | null;
  legacy_signal_at: string | null;
  state_labels: FinancialSignalStateLabels;
}

export interface FinancialWatchlistCandidateLane {
  id: "bullish_alignment" | "risk_alignment" | "reentry" | "mixed_timeframes";
  label: string;
  description: string;
  candidates: FinancialWatchlistCandidate[];
}

export interface FinancialWatchlistCandidatesResponse {
  generated_at: string;
  lanes: FinancialWatchlistCandidateLane[];
}

export interface FinancialDailyCalibrationTicker {
  ticker: string;
  observations: number;
  covered_observations: number;
  exact_bar_observations: number;
  matches: number;
  accuracy: number | null;
  score_mae: number | null;
}

export interface FinancialDailyCalibrationResponse {
  parameter_set_name: string;
  generated_at: string;
  since: string | null;
  until: string | null;
  total_observations: number;
  covered_observations: number;
  exact_bar_observations: number;
  missing_observations: number;
  neutral_generated_observations: number;
  matches: number;
  exact_event_matches: number;
  exact_event_accuracy: number | null;
  window_event_matches: number;
  window_event_accuracy: number | null;
  event_window_days: number;
  no_generated_event_observations: number;
  opposite_generated_event_observations: number;
  accuracy: number | null;
  coverage_rate: number | null;
  exact_coverage_rate: number | null;
  green_precision: number | null;
  green_recall: number | null;
  red_precision: number | null;
  red_recall: number | null;
  score_mae: number | null;
  score_rmse: number | null;
  confusion: Record<"green" | "red", Record<"green" | "red" | "neutral" | "missing", number>>;
  event_confusion: Record<"green" | "red", Record<"green" | "red" | "none" | "missing", number>>;
  top_tickers: FinancialDailyCalibrationTicker[];
}

export type ServiceHealthState = "up" | "down";

export interface ServiceHealthResponse {
  legal?: ServiceHealthState;
  cluster?: ServiceHealthState;
  classifier?: ServiceHealthState;
  mission?: ServiceHealthState;
  grafana?: ServiceHealthState;
  up_count: number;
  total: number;
  [key: string]: ServiceHealthState | number | undefined;
}

export interface ClusterTelemetry {
  nodes_online: number;
  nodes_total: number;
  gpu_temp_c: number | null;
}

export interface BridgeStatusResponse {
  last_24h: string | number;
  bridge_total: number;
  latest_email: string | null;
}

export interface LegalOverviewResponse {
  total_cases?: number;
  pending_actions?: Array<Record<string, unknown>>;
  deadlines?: Array<{ effective_date?: string } & Record<string, unknown>>;
}

// ---------------------------------------------------------------------------
// VRS Hub
// ---------------------------------------------------------------------------
export interface VrsMessageStats {
  total_messages: number;
  inbound: number;
  outbound: number;
  auto_responses?: number;
  automation_rate: number;
  sentiment_distribution?: Record<string, number>;
  avg_ai_confidence: number;
  total_cost?: number;
  cost_per_message?: number;
}

export interface VrsHunterTarget {
  guest_id: string;
  full_name: string;
  email: string;
  lifetime_value: number;
  last_stay_date: string;
  days_dormant: number;
  target_score: number;
}

export interface VrsHunterDispatchResponse {
  status: "queued";
  event_id: string;
  message: string;
  queue_depth: number;
  queue_key: string;
}

export interface VrsConflictQueueItem {
  id: string;
  status: string;
  created_at: string;
  hold_reason?: string | null;
  corrective_scheduling?: string | null;
  complaint_legitimacy?: string | null;
  escalation_level?: string | null;
  field_reality?: Record<string, unknown> | null;
  session_id?: string | null;
  consensus_signal?: string | null;
  consensus_conviction: number;
  inbound_message?: string | null;
  draft_reply?: string | null;
  guest?: {
    id?: string | null;
    full_name?: string | null;
    email?: string | null;
    phone_number?: string | null;
  } | null;
  property?: {
    id?: string | null;
    name?: string | null;
    slug?: string | null;
  } | null;
  reservation?: {
    id?: string | null;
    confirmation_code?: string | null;
  } | null;
  message?: {
    id?: string | null;
    body?: string | null;
  } | null;
}

export interface VrsConflictQueueResponse {
  items: VrsConflictQueueItem[];
  summary: {
    held: number;
    dispatched: number;
    total_scanned: number;
  };
  synced?: boolean;
}

export interface VrsCouncilOpinion {
  seat: number;
  persona: string;
  slug?: string;
  signal: string;
  conviction: number;
  reasoning: string;
}

export interface VrsAdjudicationDetail extends VrsConflictQueueItem {
  council?: {
    opinions: VrsCouncilOpinion[];
  } | null;
  ledger_payload?: Record<string, unknown>;
  live_triage?: Record<string, unknown> | null;
  recommended_actions?: string[];
}

export interface VrsReservationDetailResponse {
  reservation: Reservation & {
    internal_notes?: string | null;
    streamline_notes?: string | null;
  };
  guest?: Guest | null;
  property?: Property | null;
  messages?: Message[];
  work_orders?: WorkOrder[];
  damage_claims?: Array<Record<string, unknown>>;
  agreement?: Record<string, unknown> | null;
}

export interface StreamlineQuoteProperty {
  id: string;
  name: string;
  slug: string;
  streamline_property_id: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string | null;
  is_active: boolean;
  source: string;
}

export interface StreamlineQuotePropertyCatalogResponse {
  properties: StreamlineQuoteProperty[];
  fetched_at: string;
  cache_hit: boolean;
}

export interface StreamlineCalendarDay {
  status: "available" | "booked" | "blocked";
  nightly_rate: number;
  is_peak: boolean;
  confirmation_id?: string | null;
  block_type?: string | null;
  source?: string | null;
  pricing_source?: string | null;
}

export interface StreamlineCalendarBlock {
  start_date: string;
  end_date: string;
  checkout_date?: string | null;
  status: "booked" | "blocked";
  confirmation_id?: string | null;
  block_type?: string | null;
  type_description?: string | null;
}

export interface StreamlineMasterCalendarResponse {
  property_id: string;
  property_name: string;
  streamline_property_id: string;
  requested_property_id: string;
  start_date: string;
  end_date: string;
  days: Record<string, StreamlineCalendarDay>;
  blocks: StreamlineCalendarBlock[];
  summary: {
    available_days: number;
    booked_days: number;
    blocked_days: number;
    average_nightly_rate: number;
  };
  rate_source?: string | null;
  availability_source?: string | null;
  fetched_at: string;
  cache_hit: boolean;
}

export interface StreamlineDeterministicQuoteResponse {
  property_id: string;
  property_name: string;
  streamline_property_id: string;
  requested_property_id: string;
  check_in: string;
  check_out: string;
  nights: number;
  adults: number;
  children: number;
  pets: number;
  availability_status: "available" | "unavailable";
  unavailable_dates: string[];
  base_rent: number;
  fees: number;
  tax_rate: number;
  taxes: number;
  total_amount: number;
  streamline_total?: number;
  ancillary_total?: number;
  grand_total?: number;
  pricing_source?: string | null;
  nightly_breakdown: Array<{
    date: string;
    rate: number;
    source: string;
    is_peak: boolean;
  }>;
  selected_add_on_ids?: string[];
  add_ons?: Array<{
    id: string;
    name: string;
    description: string;
    pricing_model: string;
    amount: number;
  }>;
  calendar_summary?: {
    available_days: number;
    booked_days: number;
    blocked_days: number;
    average_nightly_rate: number;
  } | null;
  fetched_at: string;
  cache_hit: boolean;
}

export interface StreamlineRefreshResponse {
  status: string;
  property_id: string;
  streamline_property_id: string;
  start_date: string;
  end_date: string;
  refreshed_at: string;
}

export interface VrsAddOn {
  id: string;
  name: string;
  description: string;
  price: string;
  pricing_model: "flat_fee" | "per_night" | "per_guest";
  is_active: boolean;
  scope: "global" | "property_specific";
  property_id: string | null;
}

export interface ReviewQueueItem {
  id: string;
  message_id?: string;
  guest_id: string;
  property_id?: string;
  original_message: string;
  ai_draft_response: string;
  ai_confidence: number;
  intent: string;
  sentiment: string;
  status: "pending" | "approved" | "edited" | "rejected";
  created_at: string;
  guest?: Guest;
  property?: Property;
}

export interface SeoReviewPatch {
  id: string;
  property_id: string;
  property_slug: string | null;
  property_name: string | null;
  rubric_id: string | null;
  page_path: string;
  patch_version: number;
  status: string;
  title: string | null;
  meta_description: string | null;
  og_title: string | null;
  og_description: string | null;
  h1_suggestion: string | null;
  canonical_url: string | null;
  jsonld_payload: Record<string, unknown> | null;
  alt_tags: Record<string, unknown> | null;
  godhead_score: number | null;
  godhead_model: string | null;
  godhead_feedback: Record<string, unknown> | null;
  grade_attempts: number;
  reviewed_by: string | null;
  reviewed_at: string | null;
  final_payload: Record<string, unknown> | null;
  deployed_at: string | null;
  deploy_task_id: string | null;
  deploy_status: "queued" | "processing" | "succeeded" | "failed" | null;
  deploy_queued_at: string | null;
  deploy_acknowledged_at: string | null;
  deploy_attempts: number;
  deploy_last_error: string | null;
  deploy_last_http_status: number | null;
  swarm_model: string | null;
  swarm_node: string | null;
  generation_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface SeoReviewPatchActionResponse {
  status: string;
  patch_id: string;
}

export interface OpenShellAuditEntry {
  id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  tool_name: string | null;
  redaction_status: string;
  model_route: string | null;
  outcome: string;
  request_id: string | null;
  created_at: string;
  entry_hash: string;
  prev_hash: string | null;
  signature: string;
  metadata_json: Record<string, unknown>;
}

export type SeoPatchQueueStatus =
  | "proposed"
  | "needs_revision"
  | "approved"
  | "rejected"
  | "deployed"
  | "superseded";

export interface SeoPatchQueueItem {
  id: string;
  target_type: "property" | "archive_review";
  target_slug: string;
  property_id: string | null;
  status: SeoPatchQueueStatus;
  target_keyword: string;
  campaign: string;
  rubric_version: string;
  source_hash: string;
  proposed_title: string;
  proposed_meta_description: string;
  proposed_h1: string;
  proposed_intro: string;
  proposed_faq: Array<Record<string, unknown>>;
  proposed_json_ld: Record<string, unknown>;
  fact_snapshot: Record<string, unknown>;
  score_overall: number | null;
  score_breakdown: Record<string, number>;
  proposed_by: string;
  proposal_run_id: string | null;
  reviewed_by: string | null;
  review_note: string | null;
  approved_payload: Record<string, unknown>;
  approved_at: string | null;
  deployed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SeoPatchQueueResponse {
  items: SeoPatchQueueItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface SeoPatchQueueFilters {
  status?: SeoPatchQueueStatus | "all";
  campaign?: string;
  target_type?: "property" | "archive_review";
  target_slug?: string;
  property_id?: string;
  limit?: number;
  offset?: number;
}

export interface SeoPatchReviewResponse {
  ok: boolean;
  item: SeoPatchQueueItem;
}

export interface SeoPatchBulkReviewResult {
  succeeded: SeoPatchQueueItem[];
  failed: Array<{
    id: string;
    message: string;
  }>;
}

export type SeoRedirectRemapStatus =
  | "proposed"
  | "promoted"
  | "rejected"
  | "applied"
  | "superseded";

export interface SeoRedirectRemapQueueItem {
  id: string;
  source_path: string;
  current_destination_path: string | null;
  proposed_destination_path: string;
  applied_destination_path: string | null;
  grounding_mode: string;
  status: SeoRedirectRemapStatus;
  campaign: string;
  rubric_version: string;
  proposal_run_id: string;
  proposed_by: string;
  extracted_entities: string[];
  source_snapshot: Record<string, unknown>;
  route_candidates: string[];
  rationale: string;
  grade_score: number | null;
  grade_payload: Record<string, unknown>;
  reviewed_by: string | null;
  review_note: string | null;
  approved_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SeoRedirectRemapQueueResponse {
  items: SeoRedirectRemapQueueItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface SeoRedirectRemapFilters {
  status?: SeoRedirectRemapStatus | "all";
  campaign?: string;
  limit?: number;
  offset?: number;
}

export interface SeoRedirectRemapReviewResponse {
  ok: boolean;
  item: SeoRedirectRemapQueueItem;
}

export interface SeoRedirectRemapBulkReviewResult {
  succeeded: SeoRedirectRemapQueueItem[];
  failed: Array<{
    id: string;
    message: string;
  }>;
}

// ---------------------------------------------------------------------------
// Email Intake
// ---------------------------------------------------------------------------
export type EmailIntakePriority = "P0" | "P1" | "P2" | "P3";

export type EmailIntakeQueueStatus =
  | "pending"
  | "seen"
  | "actioned"
  | "dismissed"
  | "deferred"
  | "snoozed";

export interface EmailIntakeEscalationItem {
  id: number;
  email_id: number;
  trigger_type: string;
  trigger_detail: string;
  priority: EmailIntakePriority;
  status: EmailIntakeQueueStatus | string;
  seen_by?: string | null;
  seen_at?: string | null;
  action_taken?: string | null;
  created_at: string;
  sender: string;
  subject: string;
  body_preview: string;
  division: string;
  division_confidence: number;
  sent_at?: string | null;
  review_grade: number;
}

export interface EmailIntakeEscalationListResponse {
  items: EmailIntakeEscalationItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface EmailIntakeQuarantineItem {
  id: number;
  sender: string;
  subject: string;
  content_preview: string;
  rule_reason?: string | null;
  rule_type?: string | null;
  status: string;
  reviewed_by?: string | null;
  created_at: string;
}

export interface EmailIntakeQuarantineResponse {
  items: EmailIntakeQuarantineItem[];
  total: number;
}

export interface EmailIntakeRoutingRule {
  id: number;
  rule_type: string;
  pattern: string;
  action: string;
  division?: string | null;
  reason?: string | null;
  is_active: boolean;
  hit_count: number;
}

export interface EmailIntakeClassificationRule {
  id: number;
  division: string;
  match_field: string;
  pattern: string;
  weight: number;
  is_active: boolean;
  hit_count: number;
  notes?: string | null;
}

export interface EmailIntakeEscalationRule {
  id: number;
  rule_name: string;
  trigger_type: string;
  match_field: string;
  pattern: string;
  priority: EmailIntakePriority;
  is_active: boolean;
}

export interface EmailIntakeRulesResponse {
  routing_rules: EmailIntakeRoutingRule[];
  classification_rules: EmailIntakeClassificationRule[];
  escalation_rules: EmailIntakeEscalationRule[];
}

export interface EmailIntakeLearningRecent {
  actor: string;
  action_type: string;
  old_division?: string | null;
  new_division?: string | null;
  review_grade?: number | null;
  created_at: string;
  subject?: string | null;
}

export interface EmailIntakeLearningGradeDistributionItem {
  grade: number;
  count: number;
}

export interface EmailIntakeLearningResponse {
  total_reviewed: number;
  total_reclassified: number;
  total_dismissed: number;
  avg_grade: string;
  grade_distribution: EmailIntakeLearningGradeDistributionItem[];
  recent: EmailIntakeLearningRecent[];
}

export interface EmailIntakeHealthResponse {
  dlq: Record<string, number>;
  escalation_pending: Partial<Record<EmailIntakePriority, number>>;
  snoozed_active: number;
  snoozed_expired: number;
  errors_last_hour: number;
  ingested_last_hour: number;
  sla_thresholds: Record<EmailIntakePriority, number>;
}

export interface EmailIntakeDlqItem {
  id: number;
  fingerprint: string;
  source_tag?: string | null;
  sender?: string | null;
  subject?: string | null;
  error_message: string;
  retry_count: number;
  max_retries: number;
  status: string;
  next_retry_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface EmailIntakeDlqResponse {
  items: EmailIntakeDlqItem[];
  counts: Record<string, number>;
}

export interface EmailIntakeDashboardResponse {
  quarantine: {
    by_status: Array<{ status: string; cnt: number }>;
    pending: EmailIntakeQuarantineItem[];
  };
  escalation: {
    pending: Array<{
      id: number;
      trigger_type: string;
      trigger_detail: string;
      priority: EmailIntakePriority;
      status: string;
      created_at: string;
      sender: string;
      subject: string;
    }>;
    stats: Array<{ priority: EmailIntakePriority; status: string; cnt: number }>;
  };
  routing_rules: EmailIntakeRoutingRule[];
  classification_rules: Array<{ division: string; rule_count: number; total_hits: number }>;
  division_distribution: Array<{ division: string; cnt: number; avg_confidence: number }>;
  dlq: Record<string, number>;
  sla_breaches: Record<EmailIntakePriority, number>;
  snoozed_count: number;
}

export interface EmailIntakeMetadataResponse {
  divisions: string[];
  dismiss_reasons: Record<string, string>;
  action_types: Record<string, string>;
  sla_hours: Record<EmailIntakePriority, number>;
}

export interface EmailIntakeSlaResponse {
  breaches: Array<{
    id: number;
    email_id: number;
    priority: EmailIntakePriority;
    created_at: string;
    sender: string;
    subject: string;
    hours_pending: number;
    sla_hours: number;
    breach_hours: number;
  }>;
  summary: Record<
    EmailIntakePriority,
    { sla_hours: number; total_pending: number; breached: number; compliant: number }
  >;
}

export interface ConversationThread {
  guest_id: string;
  guest_name: string;
  guest_phone: string;
  last_message: string;
  last_message_at: string;
  unread_count: number;
  property_name?: string;
}

export interface AiAskRequest {
  question: string;
  context?: Record<string, unknown> | null;
}

export interface AiAskResponse {
  answer?: string;
  response?: string;
  result?: string;
  [key: string]: unknown;
}

export interface AiForecastRequest {
  historical_data: Array<Record<string, unknown>>;
  forecast_months: number;
}

export interface AiForecastResponse {
  forecast?: string;
  summary?: string;
  [key: string]: unknown;
}

export interface AiOptimizeListingRequest {
  property_name: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  amenities: string[];
  location: string;
}

export interface AiOptimizeListingResponse {
  generated_description?: string;
  suggestions?: string;
  [key: string]: unknown;
}

export interface AiPredictMaintenanceRequest {
  work_orders: Array<Record<string, unknown>>;
  messages: Array<Record<string, unknown>>;
}

export interface AiPredictMaintenanceResponse {
  analysis?: string;
  alerts?: string[];
  [key: string]: unknown;
}

export interface MessageTemplate {
  id: string;
  name: string;
  category: string;
  body: string;
  variables: string[];
  trigger_type: string;
  is_active: boolean;
}

export interface PropertyUtility {
  id: string;
  property_id: string;
  service_type: string;
  provider_name: string;
  account_number?: string;
  account_holder?: string;
  portal_url?: string;
  portal_username?: string;
  has_portal_password: boolean;
  contact_phone?: string;
  contact_email?: string;
  notes?: string;
  monthly_budget?: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  total_cost_mtd?: number;
  total_cost_ytd?: number;
  latest_reading_date?: string;
}

export interface UtilityReading {
  id: string;
  utility_id: string;
  reading_date: string;
  cost: number;
  usage_amount?: number;
  usage_unit?: string;
  notes?: string;
  created_at?: string;
}

export interface UtilityCostSummary {
  property_id: string;
  property_name?: string;
  period: string;
  by_service: Record<string, number>;
  total: number;
  daily_breakdown?: Array<{ date: string; service: string; cost: number }>;
}

export interface AnalyticsEvent {
  date: string;
  messages_sent: number;
  messages_received: number;
  ai_responses: number;
  manual_responses: number;
  automation_rate: number;
}

export type StaffRole = "super_admin" | "manager" | "reviewer";

export interface StaffUserDetail {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: StaffRole;
  is_active: boolean;
  last_login_at?: string | null;
  notification_phone?: string | null;
  notification_email?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface StaffInvite {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: StaffRole;
  status: "pending" | "accepted" | "expired" | "revoked";
  invited_by: string;
  expires_at?: string | null;
  accepted_at?: string | null;
  created_at?: string | null;
}

// ---------------------------------------------------------------------------
// VRS Rule Engine / Automations
// ---------------------------------------------------------------------------

export interface AutomationRule {
  id: string;
  name: string;
  target_entity: string;
  trigger_event: string;
  conditions: { operator?: string; rules?: Array<{ field: string; op: string; value: unknown }> };
  action_type: string;
  action_payload: Record<string, unknown>;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AutomationEventEntry {
  id: string;
  rule_id?: string;
  entity_type: string;
  entity_id: string;
  event_type: string;
  previous_state: Record<string, unknown>;
  current_state: Record<string, unknown>;
  action_result?: string;
  error_detail?: string;
  created_at?: string;
}

export interface QueueStatus {
  queue_key: string;
  depth: number;
}

export interface EmailTemplateSummary {
  id: string;
  name: string;
  subject_template: string;
}

export interface FullEmailTemplate {
  id: string;
  name: string;
  trigger_event: string;
  subject_template: string;
  body_template: string;
  is_active: boolean;
  requires_human_approval: boolean;
  created_at: string | null;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// System Health (bare-metal dashboard on port 9876)
// ---------------------------------------------------------------------------

export interface GpuProcess {
  pid: string;
  name: string;
  vram_mib: string;
}

export interface NodeGpuMetrics {
  temp_c: number;
  total_mib: number;
  used_mib: number;
  pct: number;
  util_pct: number;
  power_w: number;
  pstate: string;
  driver: string;
  clock_mhz: number;
  clock_max_mhz: number;
  processes: GpuProcess[];
}

export interface NodeCpuMetrics {
  load_1m: number;
  load_5m: number;
  load_15m: number;
  cores: number;
  usage_pct: number;
}

export interface NodeRamMetrics {
  total_gb: number;
  used_gb: number;
  free_gb: number;
  avail_gb: number;
  pct: number;
}

export interface NodeDiskMetrics {
  total_gb: number;
  used_gb: number;
  avail_gb: number;
  pct: string;
}

export interface NodeThermalSensor {
  name: string;
  temps: number[];
}

export interface NodeMetrics {
  name: string;
  ip: string;
  role: string;
  online: boolean;
  gpu: NodeGpuMetrics;
  cpu: NodeCpuMetrics;
  ram: NodeRamMetrics;
  disk: NodeDiskMetrics;
  thermals?: NodeThermalSensor[];
  processes?: Array<{
    user: string;
    pid: string;
    cpu: string;
    mem: string;
    vsz_mb: number;
    rss_mb: number;
    command: string;
  }>;
}

export interface SystemHealthService {
  name: string;
  port: number;
  status: "online" | "offline";
}

export interface QdrantCollectionStats {
  points: number;
  status: string;
}

export interface SystemHealthDatabases {
  postgres: Record<string, number>;
  qdrant: Record<string, QdrantCollectionStats>;
}

export interface StreamlineSyncHealth {
  service: "streamline";
  unit: string;
  status: "online" | "degraded" | "offline";
  worker_active: boolean;
  circuit_open_recent: boolean;
  stale_data_fallback: boolean;
  recent_circuit_events: number;
  recent_circuit_methods?: Array<{ method: string; count: number }>;
  primary_circuit_method?: string | null;
  last_error_count: number | null;
  last_error_categories?: Record<string, number>;
  last_reservation_errors: number | null;
  last_properties_updated: number | null;
  last_reservations_updated: number | null;
  last_elapsed_seconds: number | null;
  last_sync_summary: string | null;
  last_cycle_summary: string | null;
  latest_circuit_summary: string | null;
  checked_at: string;
}

export interface SystemHealthIntegrations {
  streamline_sync?: StreamlineSyncHealth;
  operations?: OperationalHealth;
}

export interface OperationalHealthMetric {
  status: "online" | "degraded" | "offline" | "unknown";
  [key: string]: string | number | null;
}

export interface OperationalHealth {
  status: "online" | "degraded" | "offline" | "unknown";
  checked_at: string;
  channex: OperationalHealthMetric;
  checkout_holds: OperationalHealthMetric;
  quote_checkout: OperationalHealthMetric;
  twilio: OperationalHealthMetric;
  queues: OperationalHealthMetric;
}

export interface SystemHealthResponse {
  status: "healthy" | "degraded";
  service: string;
  uptime_seconds: number;
  timestamp: string;
  collected_in_ms: number;
  /** Backend may omit or null when collectors are offline; UI must guard Object.values. */
  nodes?: Record<string, NodeMetrics> | null;
  services: SystemHealthService[];
  integrations?: SystemHealthIntegrations;
  databases: SystemHealthDatabases;
  /** C2 pulse merged in by `/api/telemetry/ws/system-health` stream. */
  pulse?: CommandC2PulseResponse;
}

// ---------------------------------------------------------------------------
// NeMo Command Center (Trust Ledger)
// ---------------------------------------------------------------------------

export interface NemoCommandCenterLedgerEntry {
  account_name: string;
  amount_cents: number;
  entry_type: "debit" | "credit";
}

export interface NemoCommandCenterTransaction {
  id: string;
  streamline_event_id: string;
  timestamp: string;
  signature: string | null;
  previous_signature: string | null;
  entries: NemoCommandCenterLedgerEntry[];
}

export interface NemoCommandCenterHashChain {
  status: "ok" | "broken";
  verified_count: number;
  broken_at: string | null;
}

export interface NemoCommandCenterResponse {
  hash_chain: NemoCommandCenterHashChain;
  transactions: NemoCommandCenterTransaction[];
  total_transaction_count: number;
}

export interface CommandC2RootResponse {
  status: string;
  host: string;
  node_name: string;
  message: string;
  endpoints: {
    pulse: string;
    verify: string;
    restart: string;
    purge: string;
  };
}

export interface CommandC2SystemVitals {
  ram_percent: number;
  ram_gb_used: number;
  disk_percent: number;
  disk_gb_free: number;
}

export interface CommandC2GpuVitals {
  vram_used?: number;
  vram_total?: number;
  vram_percent?: number;
  temp?: number;
  utilization?: number;
  error?: string;
  details?: string;
}

export interface CommandC2PulseResponse {
  host: string;
  node_name: string;
  cpu_load: number;
  system: CommandC2SystemVitals;
  gpu: CommandC2GpuVitals;
  services: Record<string, string>;
  uptime: string;
  timestamp?: string;
}

export interface CommandC2VerificationResponse {
  status: string;
  host: string;
  node_name: string;
  report: string;
}

export interface CommandC2ActionResponse {
  status: string;
  message: string;
}

export interface ShadowAuditTrace {
  trace_id: string;
  quote_id?: string | null;
  request_id?: string | null;
  created_at: string;
  drift_status: "MATCH" | "MINOR_DRIFT" | "CRITICAL_MISMATCH" | string;
  legacy_total: number;
  sovereign_total: number;
  total_drift_pct: number;
  tax_delta: number;
  base_rate_drift_pct: number;
  hmac_signature?: string | null;
  async_job_href?: string | null;
  audit_log_href: string;
}

export interface ShadowAuditSummaryResponse {
  status: "active" | "alert" | "cold_start" | string;
  gate_target: number;
  gate_completed: number;
  gate_progress: string;
  accuracy_rate: number;
  tax_accuracy_rate: number;
  avg_base_drift_pct: number;
  critical_mismatch_count: number;
  kill_switch_armed: boolean;
  spark_node_2_status: "online" | "idle" | "unknown" | string;
  recent_traces: ShadowAuditTrace[];
}

export interface HistoricalRecoverySlug {
  slug: string;
  count: number;
}

export interface HistoricalRecoverySummaryResponse {
  window_hours: number;
  total_events: number;
  total_resurrections: number;
  soft_landed_losses: number;
  valid_signature_count: number;
  signature_health_pct: number;
  top_recovered_slugs: HistoricalRecoverySlug[];
  top_soft_landed_slugs: HistoricalRecoverySlug[];
}

export interface ShadowSeoTraceResponse {
  trace_id: string;
  page_path: string;
  property_slug: string | null;
  observed_at: string;
  status: string;
  legacy_score: number;
  sovereign_score: number;
  uplift_pct_points: number;
  legacy_rank: number | null;
  legacy_traffic: number | null;
  keyword: string | null;
}

export interface ShadowSeoSummaryResponse {
  status: string;
  source: string;
  snapshot_path: string | null;
  observed_count: number;
  superior_count: number;
  parity_count: number;
  trailing_count: number;
  missing_sovereign_count: number;
  avg_legacy_score: number;
  avg_sovereign_score: number;
  avg_uplift_pct_points: number;
  last_observed_at: string | null;
  recent_traces: ShadowSeoTraceResponse[];
}

export interface ShadowModeResponse {
  active: boolean;
  status: string;
  legacy_authority: string;
  message: string;
}

export interface QuoteObserverStatusResponse {
  agentic_system_active: boolean;
  queue_depth: number;
  running_jobs: number;
  last_job_status: string;
  last_job_created_at: string | null;
  last_job_finished_at: string | null;
  last_success_at: string | null;
  last_audit_at: string | null;
  last_drift_status: string | null;
  last_quote_id: string | null;
}

export interface LegacyTargetScorecardResponse {
  target_id: string;
  label: string;
  legacy_system: string;
  status: string;
  legacy_authority: boolean;
  observed_count: number;
  score_pct: number | null;
  last_observed_at: string | null;
  proof: string;
}

export interface AgenticObservationResponse {
  system_active: boolean;
  orchestrator_status: string;
  automation_rate_pct: number;
  total_messages: number;
  escalated_to_human: number;
  avg_ai_confidence: number;
  lanes: {
    concierge: string;
    seo_swarm: string;
    yield_engine: string;
  };
  generated_at: string;
}

export interface SeoObserverStatusResponse {
  enabled: boolean;
  agentic_system_active: boolean;
  interval_seconds: number;
  queue_depth: number;
  running_jobs: number;
  last_job_status: string;
  last_job_created_at: string | null;
  last_job_finished_at: string | null;
  last_success_at: string | null;
  last_audit_at: string | null;
}

export interface SeoObserverRunResponse {
  job_id: string;
  trigger_mode: string;
  status: string;
  requested_by: string | null;
  created_at: string;
  finished_at: string | null;
  observed_count: number | null;
  superior_count: number | null;
  error: string | null;
  async_job_href: string;
  audit_log_href: string;
}

export interface ScoutObserverStatusResponse {
  enabled: boolean;
  agentic_system_active: boolean;
  interval_seconds: number;
  queue_depth: number;
  running_jobs: number;
  last_job_status: string;
  last_job_created_at: string | null;
  last_job_finished_at: string | null;
  last_success_at: string | null;
  last_discovery_at: string | null;
  last_inserted_count: number;
  last_duplicate_count: number;
  last_seo_draft_count: number;
  last_pricing_signal_count: number;
}

export interface ConciergeAlphaObserverStatusResponse {
  enabled: boolean;
  agentic_system_active: boolean;
  interval_seconds: number;
  queue_depth: number;
  running_jobs: number;
  last_job_status: string;
  last_job_created_at: string | null;
  last_job_finished_at: string | null;
  last_success_at: string | null;
  last_candidates_considered: number;
  last_inserted_count: number;
  last_skipped_duplicate_count: number;
  last_skipped_no_template_count: number;
}

export interface RecoveryDraftComparisonResponse {
  id: string;
  dedupe_hash: string;
  session_fp: string;
  session_fp_suffix: string | null;
  property_slug: string | null;
  drop_off_point: string;
  drop_off_point_label: string | null;
  intent_score_estimate: number;
  legacy_template_key: string;
  legacy_body: string;
  sovereign_body: string;
  parity_summary: Record<string, unknown>;
  candidate_snapshot: Record<string, unknown>;
  created_at: string;
}

export interface MarketIntelligenceTargetPropertyResponse {
  id: string;
  slug: string;
  name: string;
}

export interface MarketIntelligenceFeedItemResponse {
  id: string;
  category: string;
  title: string;
  summary: string;
  market: string;
  locality: string | null;
  confidence_score: number | null;
  query_topic: string | null;
  source_urls: string[];
  dedupe_hash: string;
  target_tags: string[];
  targeted_properties: MarketIntelligenceTargetPropertyResponse[];
  seo_patch_ids: string[];
  seo_patch_statuses: string[];
  pricing_signal_ids: string[];
  pricing_signal_statuses: string[];
  discovered_at: string;
}

export interface ContextualIntelligenceInsightResponse {
  id: string;
  category: string;
  title: string;
  summary: string;
  market: string;
  locality: string | null;
  confidence_score: number | null;
  query_topic: string | null;
  source_urls: string[];
  target_tags: string[];
  discovered_at: string;
}

export interface ContextualIntelligenceProjectionResponse {
  property_id: string;
  property_slug: string;
  property_name: string;
  items: ContextualIntelligenceInsightResponse[];
  generated_at: string;
}

export interface ScoutAlphaCategoryResponse {
  category: string;
  patch_count: number;
  deployed_count: number;
  avg_godhead_score: number;
}

export interface ScoutAlphaConversionResponse {
  window_days: number;
  scout_patch_count: number;
  manual_patch_count: number;
  scout_deployed_count: number;
  manual_deployed_count: number;
  scout_pending_human_count: number;
  manual_pending_human_count: number;
  scout_avg_godhead_score: number;
  manual_avg_godhead_score: number;
  scout_intent_event_count: number;
  manual_intent_event_count: number;
  scout_hold_started_count: number;
  manual_hold_started_count: number;
  scout_insight_impression_count: number;
  category_breakdown: ScoutAlphaCategoryResponse[];
}

export interface QuoteObserverRunResponse {
  job_id: string;
  status: string;
  requested_by: string | null;
  created_at: string;
  finished_at: string | null;
  quote_id: string | null;
  drift_status: string | null;
  trace_id: string | null;
  error: string | null;
  async_job_href: string;
  audit_log_href: string;
}

export interface ParityDashboardResponse {
  shadow_mode: ShadowModeResponse;
  quote_parity: ShadowAuditSummaryResponse;
  quote_observer: QuoteObserverStatusResponse;
  quote_observer_recent_runs: QuoteObserverRunResponse[];
  seo_parity: ShadowSeoSummaryResponse;
  seo_observer: SeoObserverStatusResponse;
  seo_observer_recent_runs: SeoObserverRunResponse[];
  scout_observer: ScoutObserverStatusResponse;
  concierge_observer: ConciergeAlphaObserverStatusResponse;
  market_intelligence_feed: MarketIntelligenceFeedItemResponse[];
  scout_alpha_conversion: ScoutAlphaConversionResponse;
  recovery_ghosts: HistoricalRecoverySummaryResponse;
  recovery_comparisons: RecoveryDraftComparisonResponse[];
  legacy_targets: LegacyTargetScorecardResponse[];
  agentic_observation: AgenticObservationResponse;
  generated_at: string;
}

/** GET /api/telemetry/sovereign-pulse — Command Center ledger + Tribunal */
export interface SovereignPulseHandshake {
  holds_active: number;
  holds_converted_last_24h: number;
  direct_reservations_last_24h: number;
  orphan_risk_holds: number;
  holds_with_conversion_fk: number;
  holds_converted_legacy_no_fk: number;
  as_of: string;
}

export interface SovereignPulseSeoQueue {
  drafted: number;
  needs_rewrite: number;
  pending_human: number;
  deployed: number;
  rejected: number;
  total: number;
}

export interface SovereignPulseTribunalRow {
  patch_id: string;
  property_slug: string | null;
  property_name: string | null;
  page_path: string;
  godhead_score: number | null;
  godhead_model: string | null;
  updated_at: string;
  media_gallery_in_source: boolean;
}

export interface SovereignPulseTribunal {
  godhead_pass_threshold: number;
  pending_human_at_or_above_threshold: number;
  pending_human_below_threshold: number;
  pending_human_score_unknown: number;
  recent_pending_human: SovereignPulseTribunalRow[];
  fleet_target_properties: number;
}

export interface SovereignPulseResponse {
  handshake: SovereignPulseHandshake;
  seo_queue: SovereignPulseSeoQueue;
  tribunal: SovereignPulseTribunal;
  generated_at: string;
}

/** GET /api/telemetry/funnel-hq — Strike 10 funnel + recovery queue */
export interface FunnelHQEdge {
  from_stage: string;
  to_stage: string;
  from_label: string;
  to_label: string;
  from_count: number;
  to_count: number;
  retention_pct: number | null;
  leakage_pct: number | null;
}

export interface FunnelHQRecoveryRow {
  session_fp_suffix: string;
  session_fp: string;
  last_event_type: string;
  last_seen_at: string;
  intent_score_estimate: number;
  deepest_funnel_stage: string;
  friction_label: string;
  linked_guest_id: string | null;
  property_slug: string | null;
  /** Furthest funnel stage reached (e.g. quote_open vs checkout_step). */
  drop_off_point: string;
  drop_off_point_label: string;
  guest_email: string | null;
  guest_phone: string | null;
  guest_display_name: string | null;
}

/** Enticer Swarm SMS preview (Strike 11). */
export interface FunnelHQEnticementForge {
  sms_enabled: boolean;
  cooldown_hours: number;
  book_url: string;
  template_raw: string;
  sample_rendered_body: string;
  twilio_configured: boolean;
}

export interface FunnelHQResponse {
  window_hours: number;
  distinct_sessions_in_window: number;
  generated_at: string;
  min_stale_minutes: number;
  edges: FunnelHQEdge[];
  recovery: FunnelHQRecoveryRow[];
  ledger_ready: boolean;
  enticement_forge: FunnelHQEnticementForge;
}

/** GET /api/telemetry/checkout-parity — Step 1 Telemetry Launch console */
export interface CheckoutParityAuditRow {
  id: string;
  reservation_id: string;
  confirmation_id: string;
  local_total: number;
  streamline_total: number;
  delta: number;
  status: "confirmed" | "discrepancy";
  local_breakdown: Record<string, unknown>;
  streamline_breakdown: Record<string, unknown>;
  created_at: string | null;
}

export interface CheckoutParityRevenueSplit {
  total_rent: number;
  total_fees: number;
  total_taxes: number;
  total_deposits: number;
  commissionable_total: number;
  pass_through_total: number;
}

export interface CheckoutParityResponse {
  consecutive_confirmed: number;
  total_confirmed: number;
  total_discrepancy: number;
  target_gate: number;
  gate_progress_pct: number;
  hermes_mode: string;
  recent_audits: CheckoutParityAuditRow[];
  revenue_split: CheckoutParityRevenueSplit;
  last_audit_at: string | null;
  system_status: "NOMINAL" | "RECOVERING" | "ALERT" | "AWAITING_DATA";
}

// ── Phase G.2: Owner Statement Workflow ──────────────────────────────────────

export type StatementPeriodStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "paid"
  | "emailed"
  | "voided";

/** OwnerBalancePeriod — one row per owner per calendar period. */
export interface OwnerBalancePeriod {
  id: number;
  owner_payout_account_id: number;
  period_start: string;       // ISO date
  period_end: string;         // ISO date
  opening_balance: string;    // Decimal as string
  closing_balance: string;
  total_revenue: string;
  total_commission: string;
  total_charges: string;
  total_payments: string;
  total_owner_income: string;
  status: StatementPeriodStatus;
  /** H.2a: true = Stripe-linked OPA AND statement is approved/paid. false = not payable yet. */
  pay_enabled: boolean;
  /** I.5: Stripe Transfer ID once paid. */
  stripe_transfer_id: string | null;
  /** I.5: Amount transferred to owner (closing - opening). */
  paid_amount: string | null;
  created_at: string | null;
  updated_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  paid_at: string | null;
  paid_by: string | null;
  emailed_at: string | null;
  voided_at: string | null;
  voided_by: string | null;
  notes: string | null;
}

/** Per-reservation payout line item inside a statement. */
export interface StatementLineItem {
  reservation_id: string;
  confirmation_code: string;
  description: string;
  check_in: string;
  check_out: string;
  nights: number;
  gross_revenue: number;
  pass_through_total: number;
  commission_rate_pct: number;
  commission_amount: number;
  cc_processing_fee: number;
  net_owner_payout: number;
}

/** Statement computation result returned inline with the detail endpoint. */
export interface StatementComputedResult {
  owner_id: string;
  owner_name: string | null;
  property_id: string;
  property_name: string;
  period_start: string;
  period_end: string;
  commission_rate_pct: number;
  reservation_count: number;
  total_gross_revenue: number;
  total_commission: number;
  total_cc_processing: number;
  total_pass_through: number;
  total_net_payout: number;
  reservations: StatementLineItem[];
  source: string;
  error?: string; // present when computation failed
}

/** Response from GET /api/admin/payouts/statements/{id} */
export interface OwnerBalancePeriodDetail {
  balance_period: OwnerBalancePeriod;
  statement: StatementComputedResult | { error: string };
}

/** Response from GET /api/admin/payouts/statements */
export interface StatementListResponse {
  statements: OwnerBalancePeriod[];
  total: number;
}

/** One outcome row inside GenerateStatementsResult. */
export interface StatementGenerationOutcome {
  owner_payout_account_id: number;
  owner_name: string | null;
  property_id: string;
  outcome: "created" | "skipped" | "error";
  reason?: string;
  period_id?: number;
}

/** Response from POST /api/admin/payouts/statements/generate */
export interface GenerateStatementsResult {
  period_start: string;
  period_end: string;
  total_owners_processed: number;
  total_drafts_created: number;
  total_skipped: number;
  total_errors: number;
  dry_run: boolean;
  results: StatementGenerationOutcome[];
}

export interface StatementListFilters {
  status?: string;
  period_start?: string;
  period_end?: string;
  owner_payout_account_id?: number;
  limit?: number;
  offset?: number;
}

export interface GenerateStatementsRequest {
  period_start: string;
  period_end: string;
  dry_run?: boolean;
}

export interface VoidStatementRequest {
  reason: string;
}

export interface MarkPaidRequest {
  payment_reference: string;
}

export interface SendTestRequest {
  override_email: string;
  note?: string;
}

/** OwnerCharge — manual expense/credit entry. */
export interface OwnerCharge {
  id: number;
  owner_payout_account_id: number;
  owner_name: string | null;
  property_name: string | null;
  posting_date: string | null;
  transaction_type: string;
  transaction_type_display: string;
  description: string;
  amount: string; // Decimal as string
  reference_id: string | null;
  // Vendor + markup fields (I.1a)
  vendor_id: string | null;
  vendor_name: string | null;
  markup_percentage: string; // Decimal as string, default "0.00"
  vendor_amount: string | null; // Decimal as string
  created_at: string | null;
  created_by: string;
  voided_at: string | null;
  voided_by: string | null;
  void_reason: string | null;
  // Email notification (I.1b) — only present on create response when send_notification=true
  notification_sent?: boolean;
  notification_error?: string | null;
}

/** Response from GET /api/admin/payouts/charges */
export interface ChargeListResponse {
  charges: OwnerCharge[];
  total: number;
}

export interface ChargeListFilters {
  owner_payout_account_id?: number;
  period_start?: string;
  period_end?: string;
  include_voided?: boolean;
  limit?: number;
  offset?: number;
}

export interface CreateOwnerChargeRequest {
  owner_payout_account_id: number;
  posting_date: string;
  transaction_type: string;
  description: string;
  amount?: number;             // required when no vendor; computed when vendor set
  reference_id?: string;
  // Vendor + markup (I.1a)
  vendor_id?: string;
  markup_percentage?: number;  // default 0
  vendor_amount?: number;
  // Email notification (I.1b)
  send_notification?: boolean;
}

export interface UpdateOwnerChargeRequest {
  description?: string;
  posting_date?: string;
  amount?: number;
  reference_id?: string;
}

export interface VoidOwnerChargeRequest {
  void_reason: string;
}
