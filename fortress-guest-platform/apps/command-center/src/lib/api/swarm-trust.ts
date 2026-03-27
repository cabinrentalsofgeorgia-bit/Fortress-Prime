import { api } from "@/lib/api";

export type AgentRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "escalated"
  | "blocked";

export type TrustDecisionStatus = "auto_approved" | "escalated" | "blocked";

export type EscalationStatus = "pending" | "resolved";

export type OverrideAction = "approve" | "reject" | "modify";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonObject
  | JsonValue[];

export interface JsonObject {
  [key: string]: JsonValue;
}

export type TrustLedgerEntry = JsonObject & {
  entry_type?: string;
  amount_cents?: number;
};

export type TrustPayload = JsonObject & {
  entries?: TrustLedgerEntry[];
};

export interface TrustDecision {
  id: string;
  proposed_payload: TrustPayload;
  deterministic_score: number;
  policy_evaluation: JsonObject;
  status: TrustDecisionStatus;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  agent_name: string;
  trigger_source: string;
  status: AgentRunStatus;
  started_at: string;
  completed_at: string | null;
  decisions: TrustDecision[];
}

export interface Escalation {
  id: string;
  decision_id: string;
  run_id: string;
  agent_name: string;
  reason_code: string;
  status: EscalationStatus;
  decision_status: TrustDecisionStatus;
  proposed_payload: TrustPayload;
  policy_evaluation: JsonObject;
  deterministic_score: number;
}

export interface EscalationQueueResponse {
  items: Escalation[];
  count: number;
}

export interface OperatorOverrideInput {
  override_action: OverrideAction;
  final_payload: TrustPayload;
}

export interface OperatorOverride {
  id: string;
  escalation_id: string;
  decision_id: string;
  operator_email: string;
  override_action: OverrideAction;
  final_payload: TrustPayload;
  timestamp: string;
  escalation_status: EscalationStatus;
  decision_status: TrustDecisionStatus;
}

export interface SwarmEscalationListItem {
  escalation: Escalation;
  run: AgentRun;
}

export async function listSwarmEscalations(): Promise<EscalationQueueResponse> {
  return api.get<EscalationQueueResponse>("/api/swarm/escalations");
}

export async function getSwarmRun(runId: string): Promise<AgentRun> {
  return api.get<AgentRun>(`/api/swarm/runs/${runId}`);
}

export async function overrideSwarmEscalation(
  escalationId: string,
  input: OperatorOverrideInput,
): Promise<OperatorOverride> {
  return api.post<OperatorOverride>(`/api/swarm/escalations/${escalationId}/override`, input);
}

export async function getPendingSwarmEscalation(
  escalationId: string,
): Promise<Escalation | null> {
  const queue = await listSwarmEscalations();
  return queue.items.find((item) => item.id === escalationId) ?? null;
}

export async function listSwarmEscalationsWithRuns(): Promise<SwarmEscalationListItem[]> {
  const queue = await listSwarmEscalations();
  const uniqueRunIds = Array.from(new Set(queue.items.map((item) => item.run_id)));
  const runPairs = await Promise.all(
    uniqueRunIds.map(async (runId) => [runId, await getSwarmRun(runId)] as const),
  );
  const runsById = new Map<string, AgentRun>(runPairs);

  return queue.items.map((escalation) => {
    const run = runsById.get(escalation.run_id);
    if (!run) {
      throw new Error(`Failed to load run context for escalation ${escalation.id}.`);
    }
    return { escalation, run };
  });
}
