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

export interface StaffUserDetail {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  last_login_at?: string | null;
  notification_phone?: string | null;
  notification_email?: string | null;
}

export interface StaffInvite {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
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

export interface SystemHealthResponse {
  status: "healthy" | "degraded";
  service: string;
  uptime_seconds: number;
  timestamp: string;
  collected_in_ms: number;
  nodes: Record<string, NodeMetrics>;
  services: SystemHealthService[];
  databases: SystemHealthDatabases;
}
