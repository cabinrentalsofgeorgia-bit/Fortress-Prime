/* ── Extraction sub-entities ─────────────────────────────────── */

export interface ExtractedParty {
  name: string;
  role: string;
  counsel: string | null;
}

export interface ExtractedDeadline {
  description: string;
  due_date: string;
  source_text: string;
  deadline_type: string;
  urgency: string;
}

export interface ExtractedAmount {
  value: number;
  currency: string;
  description: string;
}

export interface ExtractedEntities {
  document_type: string;
  jurisdiction: string | null;
  case_number: string | null;
  parties: ExtractedParty[];
  deadlines: ExtractedDeadline[];
  amounts: ExtractedAmount[];
  key_claims: string[];
  risk_score: number;
  risk_justification: string;
  summary: string;
}

/* ── Core domain models ──────────────────────────────────────── */

export type ExtractionStatus =
  | "none"
  | "queued"
  | "processing"
  | "complete"
  | "failed";

export type ReviewStatus = "pending_review" | "approved" | "rejected";

export interface LegalCase {
  id: number;
  case_slug: string;
  case_number: string;
  case_name: string;
  court: string;
  judge: string | null;
  case_type: string;
  our_role: string;
  status: string;
  critical_date: string | null;
  critical_note: string | null;
  plan_admin: string | null;
  plan_admin_email: string | null;
  plan_admin_address: string | null;
  fiduciary: string | null;
  opposing_counsel: string | null;
  our_claim_basis: string | null;
  petition_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  risk_score: number | null;
  extraction_status: ExtractionStatus;
  extracted_entities: ExtractedEntities | Record<string, never>;
  days_remaining?: number | null;
  live_ai_status?: string | null;
  latest_action?: string | null;
  last_ai_review?: string | null;
}

export interface LegalDeadline {
  id: number;
  case_id: number;
  deadline_type: string;
  description: string;
  due_date: string;
  alert_days_before: number;
  status: string;
  extended_to: string | null;
  extension_reason: string | null;
  created_at: string;
  source_document: string | null;
  auto_extracted: boolean;
  review_status: ReviewStatus;
  content_hash: string;
  days_remaining: number;
  effective_date: string;
  urgency: string;
}

export interface Correspondence {
  id: number;
  case_id: number;
  direction: string;
  comm_type: string;
  recipient: string | null;
  recipient_email: string | null;
  subject: string;
  body: string | null;
  status: string;
  file_path: string | null;
  approved_by: string | null;
  approved_at: string | null;
  sent_at: string | null;
  created_at: string;
  risk_score: number | null;
  extracted_entities: ExtractedEntities | null;
  extraction_status: ExtractionStatus | null;
}

export interface TimelineEvent {
  event_type: string;
  summary: string;
  detail: string;
  status: string;
  event_time: string;
  ref_id: number;
}

/* ── API response wrappers ───────────────────────────────────── */

export interface CasesListResponse {
  cases: LegalCase[];
}

export interface CaseDetailResponse {
  case: LegalCase;
  actions?: unknown[];
  evidence?: unknown[];
  watchdog?: unknown[];
}

export interface DeadlinesResponse {
  deadlines: LegalDeadline[];
}

export interface CorrespondenceResponse {
  correspondence: Correspondence[];
  total: number;
}

export interface ExtractionQueuedResponse {
  extraction: "queued" | "skipped";
  target: string;
  id: number;
}
