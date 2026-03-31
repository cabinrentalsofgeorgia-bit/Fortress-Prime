"use client";

import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "./api";
import { toast } from "sonner";
import type {
  CasesListResponse,
  CaseDetailResponse,
  DeadlinesResponse,
  CorrespondenceResponse,
  ExtractionQueuedResponse,
  GraphRefreshResponse,
  DiscoveryDraftResponse,
  DiscoveryDraftPacksResponse,
  DiscoveryDraftPackDetail,
  CaseGraphSnapshot,
  LegalDeadline,
  SanctionsAlertsResponse,
  DepositionKillSheetsResponse,
} from "./legal-types";

const KEYS = {
  cases: ["legal", "cases"] as const,
  caseDetail: (slug: string) => ["legal", "case", slug] as const,
  deadlines: (slug: string) => ["legal", "deadlines", slug] as const,
  correspondence: (slug: string) =>
    ["legal", "correspondence", slug] as const,
  timeline: (slug: string) => ["legal", "timeline", slug] as const,
  graph: (slug: string) => ["legal", "graph", slug] as const,
  discoveryPacks: (slug: string) => ["legal", "discovery-packs", slug] as const,
  discoveryPack: (slug: string, packId: string) =>
    ["legal", "discovery-pack", slug, packId] as const,
  sanctionsAlerts: (slug: string) => ["legal", "sanctions", slug] as const,
  depositionKillSheets: (slug: string) =>
    ["legal", "deposition-kill-sheets", slug] as const,
};

/* ── Queries ──────────────────────────────────────────────────── */

export function useLegalCases() {
  return useQuery({
    queryKey: KEYS.cases,
    queryFn: () => api.get<CasesListResponse>("/api/internal/legal/cases"),
  });
}

export function useCaseDetail(slug: string) {
  return useQuery({
    queryKey: KEYS.caseDetail(slug),
    queryFn: () => api.get<CaseDetailResponse>(`/api/internal/legal/cases/${slug}`),
  });
}

export function useCaseDeadlines(slug: string) {
  return useQuery({
    queryKey: KEYS.deadlines(slug),
    queryFn: () =>
      api.get<DeadlinesResponse>(`/api/internal/legal/cases/${slug}/deadlines`),
  });
}

export function useCaseCorrespondence(slug: string) {
  return useQuery({
    queryKey: KEYS.correspondence(slug),
    queryFn: () =>
      api.get<CorrespondenceResponse>(
        `/api/internal/legal/cases/${slug}/correspondence`,
      ),
  });
}

export function useCaseTimeline(slug: string) {
  return useQuery({
    queryKey: KEYS.timeline(slug),
    queryFn: () =>
      api.get<unknown[]>(`/api/internal/legal/cases/${slug}/timeline`),
  });
}

export function useCaseGraph(slug: string) {
  return useQuery({
    queryKey: KEYS.graph(slug),
    queryFn: () => api.get<CaseGraphSnapshot>(`/api/internal/legal/cases/${slug}/graph/snapshot`),
    enabled: !!slug,
  });
}

type DiscoveryPacksHydratedResponse = DiscoveryDraftPacksResponse & {
  latest_pack: DiscoveryDraftPackDetail | null;
};

export function useDiscoveryPacks(slug: string) {
  return useQuery<DiscoveryPacksHydratedResponse>({
    queryKey: KEYS.discoveryPacks(slug),
    queryFn: async () => {
      const packs = await api.get<DiscoveryDraftPacksResponse>(
        `/api/internal/legal/cases/${slug}/discovery/packs`,
      );
      const latest = packs?.packs?.[0];
      if (!latest?.id) {
        return { ...packs, latest_pack: null };
      }
      const detail = await api.get<DiscoveryDraftPackDetail>(
        `/api/internal/legal/cases/${slug}/discovery/packs/${latest.id}`,
      );
      return { ...packs, latest_pack: detail };
    },
    enabled: !!slug,
  });
}

/**
 * Poll for extraction status changes.
 * When extraction_status is "processing" or "queued", polls every 3s.
 * Stops polling once status reaches "complete" or "failed".
 */
export function useCaseExtractionPoll(slug: string) {
  return useQuery({
    queryKey: [...KEYS.caseDetail(slug), "poll"],
    queryFn: () => api.get<CaseDetailResponse>(`/api/internal/legal/cases/${slug}`),
    refetchInterval: (query) => {
      const status = query.state.data?.case?.extraction_status;
      if (status === "processing" || status === "queued") return 3000;
      return false;
    },
  });
}

/* ── Mutations ────────────────────────────────────────────────── */

export function useTriggerExtraction(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { target: string; text?: string; correspondence_id?: number }) =>
      api.post<ExtractionQueuedResponse>(
        `/api/internal/legal/cases/${slug}/extract`,
        body,
      ),
    onSuccess: () => {
      toast.success("Extraction queued");
      qc.invalidateQueries({ queryKey: KEYS.caseDetail(slug) });
    },
    onError: (e) => toast.error(`Extraction failed: ${e.message}`),
  });
}

/**
 * Approve or reject a deadline with optimistic update.
 * Immediately removes the deadline from the pending_review list in the cache.
 */
export function useDeadlineReview(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deadlineId,
      action,
    }: {
      deadlineId: number;
      action: "approved" | "rejected";
    }) =>
      api.put<{ updated: boolean }>(
        `/api/internal/legal/deadlines/${deadlineId}`,
        { review_status: action },
      ),
    onMutate: async ({ deadlineId, action }) => {
      await qc.cancelQueries({ queryKey: KEYS.deadlines(slug) });
      const prev = qc.getQueryData<DeadlinesResponse>(KEYS.deadlines(slug));

      qc.setQueryData<DeadlinesResponse>(KEYS.deadlines(slug), (old) => {
        if (!old) return old;
        return {
          deadlines: old.deadlines.map((d: LegalDeadline) =>
            d.id === deadlineId ? { ...d, review_status: action } : d,
          ),
        };
      });

      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) {
        qc.setQueryData(KEYS.deadlines(slug), ctx.prev);
      }
      toast.error("Failed to update deadline");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: KEYS.deadlines(slug) });
    },
    onSuccess: (_data, { action }) => {
      toast.success(
        action === "approved" ? "Deadline approved" : "Deadline rejected",
      );
    },
  });
}

export function useCreateCorrespondence(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      subject: string;
      body?: string;
      direction?: string;
      comm_type?: string;
      recipient?: string;
      recipient_email?: string;
    }) =>
      api.post<{ created: boolean; correspondence_id: number }>(
        `/api/internal/legal/cases/${slug}/correspondence`,
        body,
      ),
    onSuccess: () => {
      toast.success("Correspondence created");
      qc.invalidateQueries({ queryKey: KEYS.correspondence(slug) });
      qc.invalidateQueries({ queryKey: KEYS.caseDetail(slug) });
    },
  });
}

export function useRefreshGraphMutation(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<GraphRefreshResponse>(`/api/internal/legal/cases/${slug}/graph/refresh`),
    onSuccess: () => {
      toast.success("Case graph refreshed");
      qc.invalidateQueries({ queryKey: KEYS.caseDetail(slug) });
      qc.invalidateQueries({ queryKey: KEYS.timeline(slug) });
    },
    onError: (e) => toast.error(`Graph refresh failed: ${e.message}`),
  });
}

export function useGenerateDiscoveryDraftPack(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_entity: string; max_items?: number }) =>
      api.post<DiscoveryDraftResponse>(
        `/api/internal/legal/cases/${slug}/discovery/draft-pack`,
        body,
      ),
    onSuccess: () => {
      toast.success("Discovery draft pack generated");
      qc.invalidateQueries({ queryKey: KEYS.discoveryPacks(slug) });
      qc.invalidateQueries({ queryKey: KEYS.timeline(slug) });
    },
    onError: (e) => toast.error(`Discovery generation failed: ${e.message}`),
  });
}

export function useDraftDiscoveryMutation(slug: string) {
  return useGenerateDiscoveryDraftPack(slug);
}

export function useRunSanctionsSweep(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/api/internal/legal/cases/${slug}/sanctions/sweep`),
    onSuccess: () => {
      toast.success("Sanctions sweep complete");
      qc.invalidateQueries({ queryKey: KEYS.sanctionsAlerts(slug) });
      qc.invalidateQueries({ queryKey: KEYS.timeline(slug) });
    },
    onError: (e) => toast.error(`Sanctions sweep failed: ${e.message}`),
  });
}

export function useGenerateDepositionKillSheet(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { deponent_entity: string }) =>
      api.post(`/api/internal/legal/cases/${slug}/deposition/kill-sheet`, body),
    onSuccess: () => {
      toast.success("Deposition kill-sheet generated");
      qc.invalidateQueries({ queryKey: KEYS.depositionKillSheets(slug) });
      qc.invalidateQueries({ queryKey: KEYS.timeline(slug) });
    },
    onError: (e) => toast.error(`Kill-sheet generation failed: ${e.message}`),
  });
}

/* ── Correspondence Vault ────────────────────────────────────── */

export function useUpdateCorrespondenceStatus(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      corrId,
      status,
    }: {
      corrId: number;
      status: "draft" | "approved" | "sent" | "cancelled";
    }) =>
      api.put<{ updated: boolean; id: number; status: string; sent_at: string | null }>(
        `/api/internal/legal/correspondence/${corrId}/status`,
        { status },
      ),
    onSuccess: (_data, { status }) => {
      const label =
        status === "sent" ? "Marked as sent" :
        status === "approved" ? "Approved" :
        status === "cancelled" ? "Cancelled" : "Updated";
      toast.success(label);
      qc.invalidateQueries({ queryKey: KEYS.correspondence(slug) });
      qc.invalidateQueries({ queryKey: KEYS.timeline(slug) });
    },
    onError: (e) => toast.error(`Status update failed: ${e.message}`),
  });
}

export async function downloadCorrespondence(corrId: number): Promise<void> {
  try {
    const res = await fetch(`/api/internal/legal/correspondence/${corrId}/download`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem("fgp_token") ?? ""}`,
      },
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      toast.error(`Download failed: ${detail}`);
      return;
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition");
    const filenameMatch = cd?.match(/filename="?([^";\n]+)"?/);
    const filename = filenameMatch?.[1] ?? `correspondence_${corrId}`;

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${filename}`);
  } catch (e) {
    toast.error(`Download error: ${e instanceof Error ? e.message : "Unknown"}`);
  }
}

export function useSanctionsAlerts(slug: string) {
  return useQuery<SanctionsAlertsResponse>({
    queryKey: KEYS.sanctionsAlerts(slug),
    queryFn: () =>
      api.get<SanctionsAlertsResponse>(
        `/api/internal/legal/cases/${slug}/sanctions/alerts`,
      ),
    enabled: !!slug,
    refetchInterval: 60_000,
  });
}

export function useDepositionKillSheets(slug: string) {
  return useQuery<DepositionKillSheetsResponse>({
    queryKey: KEYS.depositionKillSheets(slug),
    queryFn: () =>
      api.get<DepositionKillSheetsResponse>(
        `/api/internal/legal/cases/${slug}/deposition/kill-sheets`,
      ),
    enabled: !!slug,
    refetchInterval: 60_000,
  });
}

export async function downloadKillSheetMarkdown(
  caseSlug: string,
  sheetId: string,
  suggestedFileName?: string,
): Promise<void> {
  try {
    const res = await fetch(
      `/api/internal/legal/cases/${caseSlug}/deposition/kill-sheets/${sheetId}/export`,
      {
        headers: {
          Accept: "text/markdown",
          Authorization: `Bearer ${localStorage.getItem("fgp_token") ?? ""}`,
        },
      },
    );
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      toast.error(`Kill-sheet export failed: ${detail}`);
      return;
    }
    const blob = await res.blob();
    const filename = suggestedFileName || `${caseSlug}_kill_sheet.md`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${filename}`);
  } catch (e) {
    toast.error(
      `Kill-sheet export failed: ${e instanceof Error ? e.message : "Unknown error"}`,
    );
  }
}

export async function copyCorrespondenceContent(corrId: number): Promise<void> {
  try {
    const data = await api.get<{ content: string; filename: string }>(
      `/api/internal/legal/correspondence/${corrId}/content`,
    );
    await navigator.clipboard.writeText(data.content);
    toast.success(`Copied ${data.filename} to clipboard`);
  } catch (e) {
    toast.error(`Copy failed: ${e instanceof Error ? e.message : "Unknown"}`);
  }
}
