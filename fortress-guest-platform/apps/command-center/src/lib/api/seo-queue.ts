import { api } from "@/lib/api";
import type { OpenShellAuditEntry, SeoReviewPatch } from "@/lib/types";

type JsonObject = Record<string, unknown>;

export interface SeoReviewQueueResponse {
  items: SeoReviewPatch[];
  total: number;
  offset: number;
  limit: number;
}

export interface SeoReviewQueueFilters {
  status?: string;
  propertySlug?: string;
  limit?: number;
  offset?: number;
}

export interface SeoReviewFinalPayload {
  title: string | null;
  meta_description: string | null;
  og_title: string | null;
  og_description: string | null;
  h1_suggestion: string | null;
  jsonld: JsonObject;
  canonical_url: string | null;
  alt_tags: JsonObject;
}

export interface SeoReviewApproveInput {
  note?: string;
}

export interface SeoReviewEditInput {
  final_payload: SeoReviewFinalPayload;
  note?: string;
}

export interface SeoReviewRejectInput {
  note: string;
}

function trimOptional(value?: string): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export async function listSeoQueue(
  filters: SeoReviewQueueFilters = {},
): Promise<SeoReviewQueueResponse> {
  return api.get<SeoReviewQueueResponse>("/api/seo/queue", {
    status: filters.status ?? "pending_human",
    property_slug: filters.propertySlug,
    limit: filters.limit ?? 100,
    offset: filters.offset ?? 0,
  });
}

export async function getSeoQueuePatch(patchId: string): Promise<SeoReviewPatch> {
  return api.get<SeoReviewPatch>(`/api/seo/queue/${patchId}`);
}

export async function approveSeoQueuePatch(
  patchId: string,
  input: SeoReviewApproveInput = {},
): Promise<SeoReviewPatch> {
  return api.post<SeoReviewPatch>(`/api/seo/queue/${patchId}/approve`, {
    note: trimOptional(input.note),
  });
}

export async function editSeoQueuePatch(
  patchId: string,
  input: SeoReviewEditInput,
): Promise<SeoReviewPatch> {
  return api.post<SeoReviewPatch>(`/api/seo/queue/${patchId}/edit`, {
    final_payload: input.final_payload,
    note: trimOptional(input.note),
  });
}

export async function rejectSeoQueuePatch(
  patchId: string,
  input: SeoReviewRejectInput,
): Promise<SeoReviewPatch> {
  const note = input.note.trim();
  if (!note) {
    throw new Error("Reject note is required.");
  }

  return api.post<SeoReviewPatch>(`/api/seo/queue/${patchId}/reject`, {
    note,
  });
}

export async function getSeoPatchAuditTrail(
  patchId: string,
  limit = 20,
): Promise<OpenShellAuditEntry[]> {
  return api.get<OpenShellAuditEntry[]>("/api/openshell/audit/log", {
    resource_type: "seo_patch",
    resource_id: patchId,
    limit,
  });
}
