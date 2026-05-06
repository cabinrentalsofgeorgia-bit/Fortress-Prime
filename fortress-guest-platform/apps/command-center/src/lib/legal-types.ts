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

export interface CounselSignoffPacketSection {
  section_id: string;
  title: string;
  item_count: number;
  readiness_status: string;
  unresolved_count: number;
  signoff_status: string;
  counsel_review_required: boolean;
  notes: string;
  source_refs_summary: {
    items: number;
    with_source_refs: number;
    without_source_refs: number;
    total_source_refs: number;
    locked_restricted_related: number;
    source_check_status_counts: Record<string, number>;
  };
}

export interface CounselSignoffReadinessCheck {
  check_id: string;
  title: string;
  passed: boolean;
}

export interface CounselSignoffCaptureState {
  signoff_recorded: boolean;
  signoff_type?: string | null;
  signer_safe_label?: string | null;
  signer_role?: string | null;
  signed_at?: string | null;
  scope_confirmation_required: boolean;
  scope_confirmed?: boolean;
  notes?: string | null;
}

export interface CounselSignoffPacketResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  packet_version: number;
  packet_checksum: string;
  source_validation_execution_id: string;
  source_workbench_execution_id: string;
  source_intelligence_execution_id: string;
  status: string;
  signoff_status: string;
  readiness_status: string;
  packet_store: string;
  baseline: CounselWorkbenchBaseline;
  sections: CounselSignoffPacketSection[];
  source_integrity_matrix: {
    material_items: number;
    items_with_source_refs: number;
    items_missing_source_refs: number;
    items_needing_source_check: number;
    locked_restricted_source_involved: number;
    unsupported_assertions_marked_final: boolean;
    recommended_action: string;
  };
  signoff_readiness_checklist: CounselSignoffReadinessCheck[];
  unresolved_items_register: Array<{
    item_id: string;
    item_type: string;
    title: string;
    validation_status: string;
    source_check_status: string;
    counsel_review_required: boolean;
  }>;
  export_snapshot: {
    snapshot_id: string;
    exportable: boolean;
    format: string;
    contains_document_body_text: boolean;
    contains_locked_content: boolean;
  };
  signoff_capture: CounselSignoffCaptureState;
  audit_history: CounselValidationAuditEntry[];
  manifest_path?: string;
}

export interface CounselSignoffActionBody {
  signoff_type:
    | "operator_review_acknowledgment"
    | "counsel_review_acknowledgment"
    | "counsel_signoff_for_review_use";
  scope_confirmed: boolean;
  notes?: string;
}

export type SourceSupportStatus =
  | "source_verified_for_review_use"
  | "partially_supported"
  | "unsupported"
  | "conflicting_sources"
  | "wrong_source"
  | "source_missing"
  | "needs_page_or_chunk_review"
  | "needs_more_evidence"
  | "locked_or_privilege_limited"
  | "duplicate_or_superseded"
  | "not_applicable"
  | "needs_counsel_review";

export interface SourceIntegritySummary {
  total_material_items: number;
  checked: number;
  source_verified_for_review_use: number;
  partially_supported: number;
  unsupported: number;
  conflicting_sources: number;
  wrong_source: number;
  source_missing: number;
  needs_page_or_chunk_review: number;
  locked_or_privilege_limited: number;
  needs_counsel_review: number;
  signoff_blockers: number;
  source_validation_complete_percent: number;
  verified_subset_count: number;
  signoff_readiness_recommendation: string;
  counsel_signoff_pending: boolean;
}

export interface SourceIntegrityRecord {
  source_validation_id: string;
  item_id: string;
  item_type: string;
  item_title: string;
  packet_section: string;
  source_support_status: SourceSupportStatus;
  source_check_status: string;
  support_strength: string;
  source_refs_claimed: unknown[];
  source_refs_checked: unknown[];
  locked_restricted_involved: boolean;
  source_notes: string;
  correction_needed: boolean;
  correction_summary?: string | null;
  unresolved_reason?: string | null;
  counsel_review_required: boolean;
  signoff_blocker: boolean;
}

export interface SourceIntegrityBatchResult {
  item_type: string;
  items_total: number;
  checked: number;
  verified: number;
  partial: number;
  unsupported: number;
  conflicting: number;
  locked_or_privilege_limited: number;
  needs_page_or_chunk_review: number;
  needs_counsel_review: number;
  signoff_blockers: number;
}

export interface SourceIntegrityCorrectionQueueItem {
  queue_id: string;
  source_validation_id: string;
  item_id: string;
  item_type: string;
  issue_category: string;
  source_support_status: SourceSupportStatus;
  reason: string;
  suggested_correction?: string | null;
  required_next_action: string;
  priority: string;
  signoff_blocker: boolean;
  counsel_review_required: boolean;
  linked_source_refs: unknown[];
  locked_restricted_flag: boolean;
}

export interface SourceIntegrityResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  signoff_packet_execution_id: string;
  validation_execution_id: string;
  workbench_execution_id: string;
  status: string;
  source_validation_store: string;
  records: SourceIntegrityRecord[];
  batch_results: SourceIntegrityBatchResult[];
  source_integrity_summary: SourceIntegritySummary;
  correction_queue: SourceIntegrityCorrectionQueueItem[];
  signoff_blockers: SourceIntegrityRecord[];
  verified_subset: SourceIntegrityRecord[];
  signoff_packet_readiness_update: {
    previous_readiness_status: string;
    new_readiness_status: string;
    counsel_signoff_pending: boolean;
    explicit_signoff_recorded: boolean;
  };
  manifest_path?: string;
}

export type SourceRemediationOutcome =
  | "resolved_source_verified"
  | "resolved_corrected_for_review_use"
  | "resolved_duplicate_or_superseded"
  | "unresolved_partially_supported"
  | "unresolved_unsupported"
  | "unresolved_conflicting_sources"
  | "unresolved_needs_page_or_chunk_review"
  | "unresolved_needs_more_evidence"
  | "unresolved_needs_counsel_review"
  | "unresolved_locked_or_privilege_limited"
  | "unresolved_wrong_source"
  | "unable_to_check_safely";

export interface SourceRemediationRecord {
  remediation_id: string;
  source_remediation_execution_id: string;
  source_validation_id: string;
  matter_slug: string;
  item_id: string;
  item_type: string;
  blocker_type: string;
  original_status: SourceSupportStatus;
  remediation_outcome: SourceRemediationOutcome;
  remediated_status: string;
  support_status_after: SourceSupportStatus;
  signoff_blocker_after: boolean;
  correction_needed: boolean;
  corrected_claim_summary?: string | null;
  source_refs_before: unknown[];
  source_refs_after: unknown[];
  verification_method: string;
  locked_restricted_involved: boolean;
  counsel_review_required: boolean;
  source_notes_safe: string;
  required_next_action: string;
  reviewer_safe_label: string;
  version: number;
  supersedes_record_id?: string | null;
  rollback_ref: string;
  audit_hash?: string;
}

export interface SourceRemediationSummary {
  total_blockers_processed: number;
  resolved_source_verified: number;
  resolved_corrected_for_review_use: number;
  resolved_duplicate_or_superseded: number;
  unresolved_partially_supported: number;
  unresolved_unsupported: number;
  unresolved_conflicting_sources: number;
  unresolved_needs_page_or_chunk_review: number;
  unresolved_needs_more_evidence: number;
  unresolved_needs_counsel_review: number;
  unresolved_locked_or_privilege_limited: number;
  unresolved_wrong_source: number;
  unable_to_check_safely: number;
  remaining_blockers: number;
  verified_subset_count: number;
  limited_signoff_subset_available: boolean;
  counsel_signoff_pending: boolean;
}

export interface SourceRemediationCategorySummary {
  blocker_type: string;
  item_count: number;
  high_materiality_count: number;
  automated_remediation_safe: boolean;
  counsel_review_required: boolean;
  blocks_signoff: boolean;
  remediation_strategy: string;
}

export interface SourceRemediationResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  source_integrity_execution_id: string;
  signoff_packet_execution_id: string;
  status: string;
  source_remediation_store: string;
  records: SourceRemediationRecord[];
  remediation_category_summary: SourceRemediationCategorySummary[];
  remediation_summary: SourceRemediationSummary;
  verified_subset: {
    verified_subset_id: string;
    item_count: number;
    item_ids: string[];
    packet_sections_covered: string[];
    excluded_item_count: number;
    signoff_scope_recommendation: string;
    items: SourceRemediationRecord[];
  };
  refined_blocker_register: SourceRemediationRecord[];
  signoff_readiness_addendum: {
    source_remediation_execution_id: string;
    readiness_recommendation: string;
    verified_subset_status: string;
    counsel_signoff_pending: boolean;
    explicit_signoff_recorded: boolean;
  };
  manifest_path?: string;
}

export type SourceLinkRepairState =
  | "verified_for_review_use"
  | "corrected_verified_for_review_use"
  | "partially_supported"
  | "unsupported"
  | "conflicting_sources"
  | "wrong_source_unresolved"
  | "needs_page_or_chunk_review"
  | "needs_more_evidence"
  | "needs_counsel_review"
  | "locked_or_privilege_limited"
  | "unable_to_check_safely";

export interface SourceLinkRepairRecord {
  source_link_repair_id: string;
  source_link_repair_execution_id: string;
  source_remediation_id: string;
  source_validation_id: string;
  matter_slug: string;
  item_id: string;
  item_type: string;
  prior_remediation_outcome: SourceRemediationOutcome;
  final_remediation_state: SourceLinkRepairState;
  repair_outcome: string;
  verified_for_review_use: boolean;
  signoff_blocker_after: boolean;
  corrected_claim_summary?: string | null;
  source_refs_before: unknown[];
  source_refs_after: unknown[];
  verification_method: string;
  locked_restricted_involved: boolean;
  counsel_review_required: boolean;
  source_notes_safe: string;
  required_next_action: string;
  reviewer_safe_label: string;
  version: number;
  rollback_ref: string;
  audit_hash?: string;
}

export interface SourceLinkRepairSummary {
  total_blockers_processed: number;
  verified_for_review_use: number;
  corrected_verified_for_review_use: number;
  partially_supported: number;
  unsupported: number;
  conflicting_sources: number;
  needs_page_or_chunk_review: number;
  needs_more_evidence: number;
  needs_counsel_review: number;
  locked_or_privilege_limited: number;
  unable_to_check_safely: number;
  remaining_unresolved: number;
  verified_subset_count: number;
  counsel_signoff_pending: boolean;
}

export interface SourceLinkRepairResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  source_remediation_execution_id: string;
  source_integrity_execution_id: string;
  signoff_packet_execution_id: string;
  status: string;
  source_link_repair_store: string;
  records: SourceLinkRepairRecord[];
  repair_summary: SourceLinkRepairSummary;
  packet_section_summary: Array<{
    item_type: string;
    item_count: number;
    verified_subset_count: number;
    unresolved_count: number;
  }>;
  verified_subset: {
    verified_subset_id: string;
    item_count: number;
    item_ids: string[];
    packet_sections_covered: string[];
    excluded_item_count: number;
    signoff_scope_recommendation: string;
    items: SourceLinkRepairRecord[];
  };
  refined_unresolved_register: SourceLinkRepairRecord[];
  signoff_readiness_addendum: {
    source_link_repair_execution_id: string;
    readiness_recommendation: string;
    full_packet_ready: boolean;
    counsel_signoff_pending: boolean;
    explicit_signoff_recorded: boolean;
  };
  manifest_path?: string;
}

export interface TargetedSourceCompletionRecord {
  targeted_source_completion_id: string;
  targeted_source_completion_execution_id: string;
  source_link_repair_id: string;
  source_remediation_id: string;
  source_validation_id: string;
  matter_slug: string;
  item_id: string;
  item_type: string;
  track: string;
  prior_state: SourceLinkRepairState;
  final_state: SourceLinkRepairState;
  completion_outcome: string;
  verified_for_review_use: boolean;
  signoff_blocker_after: boolean;
  corrected_claim_summary?: string | null;
  source_refs_before: unknown[];
  source_refs_after: unknown[];
  verification_method: string;
  locked_restricted_involved: boolean;
  counsel_review_required: boolean;
  source_notes_safe: string;
  required_next_action: string;
  reviewer_safe_label: string;
  version: number;
  rollback_ref: string;
  audit_hash?: string;
}

export interface TargetedSourceCompletionSummary {
  starting_unresolved: number;
  items_processed: number;
  prior_verified_subset_count: number;
  new_items_verified: number;
  new_verified_subset_count: number;
  verified_subset_delta: number;
  remaining_unresolved: number;
  verified_for_review_use: number;
  corrected_verified_for_review_use: number;
  partially_supported: number;
  unsupported: number;
  conflicting_sources: number;
  needs_page_or_chunk_review: number;
  needs_more_evidence: number;
  needs_counsel_review: number;
  locked_or_privilege_limited: number;
  unable_to_check_safely: number;
  track_results: {
    track_a_page_chunk_review: {
      items: number;
      verified: number;
      corrected: number;
      partial: number;
      unresolved: number;
    };
    track_b_unsupported_recheck: {
      items: number;
      verified: number;
      corrected: number;
      partial: number;
      still_unsupported: number;
    };
    track_c_locked_privilege_limited: {
      items: number;
      preserved_metadata_only: number;
    };
  };
  counsel_signoff_pending: boolean;
}

export interface TargetedSourceCompletionResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  source_link_repair_execution_id: string;
  source_remediation_execution_id: string;
  source_integrity_execution_id: string;
  signoff_packet_execution_id: string;
  status: string;
  targeted_source_completion_store: string;
  records: TargetedSourceCompletionRecord[];
  completion_summary: TargetedSourceCompletionSummary;
  packet_section_summary: Array<{
    item_type: string;
    item_count: number;
    verified_subset_delta: number;
    unresolved_count: number;
  }>;
  expanded_verified_subset: {
    verified_subset_id: string;
    prior_item_count: number;
    new_item_count: number;
    delta: number;
    item_ids: string[];
    new_item_ids: string[];
    packet_sections_covered: string[];
    excluded_item_count: number;
    signoff_scope_recommendation: string;
    prior_items: SourceLinkRepairRecord[];
    new_items: TargetedSourceCompletionRecord[];
  };
  refined_unresolved_register: TargetedSourceCompletionRecord[];
  signoff_readiness_addendum: {
    targeted_source_completion_execution_id: string;
    status: string;
    verified_subset_status: string;
    full_packet_ready: boolean;
    limited_signoff_subset_available: boolean;
    readiness_recommendation: string;
    counsel_signoff_pending: boolean;
    explicit_signoff_recorded: boolean;
  };
  manifest_path?: string;
}

export interface LimitedSignoffExcludedItem {
  limited_signoff_review_id: string;
  source_record_id: string;
  source_validation_id: string;
  item_id: string;
  item_type: string;
  item_title: string;
  materiality?: number | null;
  confidence?: number | null;
  materiality_tier: string;
  blocker_type: string;
  source_status: string;
  candidate_outcome: string;
  reason_excluded: string;
  required_next_action: string;
  owner_placeholder: string;
  counsel_review_required: boolean;
  evidence_needed: boolean;
  can_proceed_without_this_item: boolean;
  signoff_impact: string;
  locked_restricted_involved: boolean;
  audit_hash?: string;
}

export interface LimitedSignoffIncludedItem {
  limited_signoff_item_id: string;
  source_record_id: string;
  item_id: string;
  item_type: string;
  source_status: string;
  candidate_outcome: string;
  source_refs_count: number;
  counsel_review_required: boolean;
  signoff_status: string;
  legal_conclusion_status: string;
  locked_restricted_involved: boolean;
  safe_note: string;
  audit_hash?: string;
}

export interface LimitedSignoffCandidateResponse {
  execution_id: string;
  created_at: string;
  case_slug: string;
  targeted_source_completion_execution_id: string;
  source_link_repair_execution_id: string;
  signoff_packet_execution_id: string;
  status: string;
  packet_label: string;
  governance_labels: string[];
  packet_store: string;
  verified_subset_used: {
    item_count: number;
    source: string;
  };
  high_materiality_source_review: {
    items_reviewed: number;
    items: LimitedSignoffExcludedItem[];
  };
  limited_signoff_candidate_packet: {
    candidate_packet_id: string;
    included_item_count: number;
    excluded_item_count: number;
    included_items: LimitedSignoffIncludedItem[];
    packet_sections: Array<{
      section_id: string;
      title: string;
      item_count: number;
      counsel_review_required: boolean;
      signoff_status: string;
    }>;
    section_summary: Array<{
      item_type: string;
      included: number;
      excluded: number;
    }>;
    signoff_scope_recommendation: string;
    counsel_signoff_pending: boolean;
    explicit_signoff_recorded: boolean;
  };
  unresolved_blocker_register_v2: LimitedSignoffExcludedItem[];
  tier_summary: {
    tier_1_count: number;
    tier_2_count: number;
    tier_3_count: number;
    excluded_from_packet: number;
    requires_counsel_interpretation: number;
    requires_more_evidence: number;
    locked_privilege_limited: number;
    unsupported: number;
    hypothesis_context_only: number;
  };
  signoff_readiness_addendum: {
    limited_signoff_candidate_execution_id: string;
    limited_packet_available: boolean;
    full_packet_ready: boolean;
    remaining_unresolved: number;
    readiness_recommendation: string;
    counsel_signoff_pending: boolean;
    explicit_signoff_recorded: boolean;
  };
  manifest_path?: string;
}
