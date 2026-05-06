export type ExtractionStatus =
  | "pending"
  | "queued"
  | "processing"
  | "complete"
  | "failed";

export interface ExtractedParty {
  name: string;
  role: string;
}

export interface ExtractedAmount {
  value: number;
  currency: string;
  description: string;
}

export interface ExtractedDeadline {
  description: string;
  due_date: string;
  source_text?: string | null;
}

export interface ExtractedEntities {
  summary?: string;
  risk_score: number;
  risk_justification?: string | null;
  document_type?: string | null;
  jurisdiction?: string | null;
  case_number?: string | null;
  parties: ExtractedParty[];
  amounts: ExtractedAmount[];
  key_claims: string[];
  deadlines: ExtractedDeadline[];
}

export interface LegalCase {
  id?: number;
  case_slug: string;
  case_number: string;
  case_name: string;
  court?: string | null;
  judge?: string | null;
  case_type?: string | null;
  our_role?: string | null;
  risk_score: number | null;
  extraction_status: ExtractionStatus;
  extracted_entities?: ExtractedEntities | Record<string, never> | null;
  critical_date?: string | null;
  critical_note?: string | null;
  notes?: string | null;
  our_claim_basis?: string | null;
  days_remaining?: number | null;
  // PR G — privilege architecture metadata
  privileged_counsel_domains?: string[] | null;
  related_matters?: string[] | null;
  case_phase?: string | null;
}

export interface LegalDeadline {
  id: number;
  description: string;
  due_date: string;
  urgency: string;
  auto_extracted?: boolean;
  review_status?: "pending_review" | "approved" | "rejected" | string;
}

export interface Correspondence {
  id: number;
  direction: "inbound" | "outbound" | string;
  subject: string;
  comm_type: string;
  status: string;
  recipient?: string | null;
  body?: string | null;
  created_at: string;
  sent_at?: string | null;
  file_path?: string | null;
}

export interface TimelineEvent {
  event_type: string;
  event_time: string;
  summary: string;
}

export interface CasesListResponse {
  cases: LegalCase[];
  total?: number;
}

export interface CaseDetailResponse {
  case: LegalCase;
  deadlines?: LegalDeadline[];
  recent_actions?: unknown[];
  evidence?: unknown[];
}

export interface DeadlinesResponse {
  deadlines: LegalDeadline[];
  case_slug?: string;
  total?: number;
}

export interface CorrespondenceResponse {
  correspondence: Correspondence[];
  total?: number;
}

export interface LegalVaultDocument {
  id: string;
  file_name: string;
  mime_type?: string | null;
  file_size_bytes?: number | null;
  chunk_count?: number | null;
  processing_status: string;
  error_detail?: string | null;
  created_at?: string | null;
}

export interface LegalVaultDocumentsResponse {
  case_slug: string;
  documents: LegalVaultDocument[];
  total: number;
}

export interface ExtractionQueuedResponse {
  queued?: boolean;
  status?: string;
  message?: string;
}

export interface GraphRefreshResponse {
  status: string;
  action: string;
  case_slug: string;
}

export interface CaseGraphNode {
  id: string;
  entity_type: string;
  entity_reference_id?: string | null;
  label: string;
  properties_json?: Record<string, unknown>;
  node_metadata?: Record<string, unknown>;
}

export interface CaseGraphEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  weight: number;
  source_ref?: string | null;
  source_evidence_id?: string | null;
}

export interface CaseGraphSnapshot {
  nodes: CaseGraphNode[];
  edges: CaseGraphEdge[];
}

export interface DiscoveryDraftItem {
  id: string;
  category: string;
  content: string;
  rationale_from_graph?: string;
  sequence_number?: number;
  lethality_score?: number | null;
  proportionality_score?: number | null;
  correction_notes?: string | null;
}

export interface DiscoveryDraftPack {
  id: string;
  case_slug: string;
  target_entity: string;
  status: string;
  created_at: string | null;
}

export interface DiscoveryDraftPackDetail {
  pack: DiscoveryDraftPack;
  items: DiscoveryDraftItem[];
}

export interface DiscoveryDraftPacksResponse {
  case_slug: string;
  count: number;
  packs: DiscoveryDraftPack[];
}

export interface DiscoveryDraftResponse {
  pack_id: string;
  case_slug: string;
  target_entity: string;
  status: string;
  items_generated: number;
  max_items?: number;
}

export interface SanctionsAlert {
  id: string;
  case_slug: string;
  alert_type: "RULE_11" | "SPOLIATION" | string;
  contradiction_summary: string | null;
  confidence_score: number | null;
  status: string;
  created_at: string;
}

export interface SanctionsAlertsResponse {
  case_slug: string;
  alerts: SanctionsAlert[];
  total: number;
}

export interface DepositionKillSheetDocument {
  doc_name: string;
  tactical_purpose: string;
}

export interface DepositionKillSheet {
  id: string;
  case_slug: string;
  deponent_entity: string;
  status: string;
  summary: string;
  high_risk_topics: string[];
  document_sequence: DepositionKillSheetDocument[];
  suggested_questions: string[];
  created_at: string | null;
}

export interface DepositionKillSheetsResponse {
  case_slug: string;
  kill_sheets: DepositionKillSheet[];
  total: number;
}

export interface CounselWorkbenchBaseline {
  documents: number;
  completed_analyzed: number;
  locked_restricted: number;
  timeline_events: number;
  graph_nodes: number;
  graph_edges: number;
  contradiction_candidates: number;
  qdrant_vector_points?: number;
}

export interface CounselWorkbenchIssue {
  id: string;
  title: string;
  issue_type: string;
  confidence_score: number;
  materiality_score: number;
  status: string;
  counsel_review_required: boolean;
  recommended_next_review_step: string;
  supporting_documents?: unknown[];
  relevant_timeline_events?: unknown[];
  contradiction_candidates?: unknown[];
}

export interface CounselWorkbenchBinder {
  id: string;
  title: string;
  purpose: string;
  document_count: number;
  review_priority: string;
  locked_restricted_handling: string;
}

export interface CounselWorkbenchTriageItem {
  id: string;
  contradiction_id: string;
  conflict_type: string;
  materiality_score: number;
  confidence_score: number | null;
  status: string;
  counsel_review_required: boolean;
  suggested_counsel_question: string;
}

export interface CounselWorkbenchEntityDossier {
  id: string;
  canonical_name: string;
  entity_type: string;
  graph_degree: number;
  confidence_score: number;
  counsel_review_notes: string;
}

export interface CounselWorkbenchReviewItem {
  id: string;
  category: string;
  title: string;
  reason: string;
  priority: string;
  recommended_next_action: string;
  counsel_review_required: boolean;
}

export interface CounselWorkbenchQuestion {
  id: string;
  category: string;
  title: string;
  priority: string;
  counsel_review_required: boolean;
}

export interface CounselWorkbenchResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  source_intelligence_execution_id: string;
  status: string;
  manifest_path?: string;
  baseline: CounselWorkbenchBaseline;
  issue_matrix: CounselWorkbenchIssue[];
  chronology_review_packet: {
    status: string;
    total_events: number;
    critical_events: unknown[];
    high_materiality_events: unknown[];
    events_requiring_counsel_review: unknown[];
  };
  contradiction_triage: CounselWorkbenchTriageItem[];
  evidence_binders: CounselWorkbenchBinder[];
  entity_dossier: CounselWorkbenchEntityDossier[];
  theory_packets: Record<string, unknown>;
  counsel_questions: CounselWorkbenchQuestion[];
  action_checklist: CounselWorkbenchQuestion[];
  consolidated_review_queue: CounselWorkbenchReviewItem[];
  privileged_locked_handling: {
    locked_restricted_count: number;
    content_analyzed: boolean;
    handling: string;
  };
}

export type CounselValidationStatus =
  | "unreviewed"
  | "accepted_for_review_use"
  | "rejected"
  | "corrected"
  | "needs_source_check"
  | "needs_counsel_review"
  | "needs_more_evidence"
  | "privileged_locked_metadata_only"
  | "duplicate_or_superseded"
  | "unresolved"
  | "final_counsel_signoff_pending";

export type CounselSourceCheckStatus =
  | "not_checked"
  | "verified"
  | "incomplete"
  | "wrong_source"
  | "needs_page_chunk_verification"
  | "unsupported";

export interface CounselValidationSummary {
  total_workbench_items: number;
  validation_complete_percent: number;
  unreviewed_items: number;
  accepted_for_review_use: number;
  rejected: number;
  corrected: number;
  needs_source_check: number;
  needs_counsel_review: number;
  high_priority_unresolved: number;
  privileged_locked_metadata_only: number;
  counsel_signoff_pending: boolean;
  last_reviewer?: string | null;
  last_validation_timestamp?: string | null;
  progress_label: string;
}

export interface CounselValidationQueue {
  queue_id: string;
  title: string;
  item_count: number;
  unreviewed_count: number;
  accepted_count: number;
  rejected_count: number;
  corrected_count: number;
  needs_source_check_count: number;
  needs_counsel_review_count: number;
  high_priority_count: number;
}

export interface CounselValidationRecord {
  validation_id: string;
  source_execution_id: string;
  validation_execution_id: string;
  matter_slug: string;
  item_type: string;
  item_id: string;
  item_title: string;
  current_status: string;
  proposed_status?: string | null;
  validation_status: CounselValidationStatus;
  source_check_status: CounselSourceCheckStatus;
  reviewer_type?: string | null;
  reviewer_identity_safe_label?: string | null;
  reviewer_role?: string | null;
  reviewed_at?: string | null;
  confidence_before?: number | null;
  confidence_after?: number | null;
  materiality?: number | null;
  correction_summary?: string | null;
  note?: string | null;
  source_refs: unknown[];
  locked_restricted_related: boolean;
  counsel_review_required: boolean;
  version: number;
  supersedes_validation_id?: string | null;
  audit_hash?: string;
}

export interface CounselValidationAuditEntry {
  audit_id: string;
  action: string;
  created_at: string;
  item_id?: string;
  reviewer_identity_safe_label: string;
  reviewer_role: string;
  audit_hash?: string;
}

export interface CounselValidationResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  source_workbench_execution_id: string;
  source_intelligence_execution_id: string;
  status: string;
  validation_store: string;
  validation_status_policy: string;
  baseline: CounselWorkbenchBaseline;
  records: CounselValidationRecord[];
  queues: CounselValidationQueue[];
  summary: CounselValidationSummary;
  audit_history: CounselValidationAuditEntry[];
  manifest_path?: string;
}

export interface CounselValidationActionBody {
  item_id: string;
  action:
    | "accept"
    | "reject"
    | "correct"
    | "needs_source_check"
    | "needs_more_evidence"
    | "needs_counsel_review"
    | "reopen";
  validation_status?: CounselValidationStatus;
  source_check_status?: CounselSourceCheckStatus;
  note?: string;
  correction_summary?: string;
}
