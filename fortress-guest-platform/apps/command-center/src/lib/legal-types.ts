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
