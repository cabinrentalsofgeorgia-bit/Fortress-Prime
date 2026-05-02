"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { ApiError } from "./api";
import { toast } from "sonner";
import type {
  Property,
  Guest,
  Reservation,
  Message,
  WorkOrder,
  DashboardStats,
  FinancialLatestSignal,
  FinancialDailyCalibrationResponse,
  FinancialSignalTransition,
  FinancialSymbolSignalDetail,
  FinancialTransitionType,
  FinancialWatchlistCandidatesResponse,
  ReviewQueueItem,
  ConversationThread,
  MessageTemplate,
  PropertyUtility,
  UtilityReading,
  UtilityCostSummary,
  StaffUserDetail,
  StaffInvite,
  AutomationRule,
  AutomationEventEntry,
  QueueStatus,
  EmailTemplateSummary,
  FullEmailTemplate,
  VrsMessageStats,
  VrsReservationDetailResponse,
  StreamlineDeterministicQuoteResponse,
  StreamlineMasterCalendarResponse,
  StreamlineQuotePropertyCatalogResponse,
  StreamlineRefreshResponse,
  VrsAddOn,
  VrsAdjudicationDetail,
  VrsConflictQueueResponse,
  VrsHunterDispatchResponse,
  SystemHealthResponse,
  NemoCommandCenterResponse,
  CommandC2ActionResponse,
  CommandC2PulseResponse,
  CommandC2RootResponse,
  CommandC2VerificationResponse,
  SovereignPulseResponse,
  FunnelHQResponse,
  HistoricalRecoverySummaryResponse,
  ParityDashboardResponse,
  ShadowAuditSummaryResponse,
  SeoReviewPatch,
  SeoPatchBulkReviewResult,
  SeoPatchQueueFilters,
  SeoPatchQueueItem,
  SeoPatchQueueResponse,
  SeoRedirectRemapBulkReviewResult,
  SeoRedirectRemapFilters,
  SeoRedirectRemapQueueResponse,
  SeoRedirectRemapReviewResponse,
  VrsHunterTarget,
  CheckoutParityResponse,
} from "./types";

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ["dashboard-stats"],
    queryFn: () => api.get("/api/analytics/dashboard"),
    refetchInterval: 30_000,
  });
}

// ---------------------------------------------------------------------------
// Financial / Hedge Fund
// ---------------------------------------------------------------------------
export function useFinancialLatestSignals(params?: {
  limit?: number;
  ticker?: string;
  min_score?: number;
  max_score?: number;
}) {
  return useQuery<FinancialLatestSignal[]>({
    queryKey: ["financial", "signals", "latest", params],
    queryFn: () => api.get("/api/financial/signals/latest", params),
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
}

export function useFinancialSignalTransitions(params?: {
  limit?: number;
  ticker?: string;
  transition_type?: FinancialTransitionType;
  since?: string;
  lookback_days?: number;
}) {
  return useQuery<FinancialSignalTransition[]>({
    queryKey: ["financial", "signals", "transitions", params],
    queryFn: () => api.get("/api/financial/signals/transitions", params),
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
}

export function useFinancialSignalDetail(
  ticker: string | null,
  params?: {
    transition_limit?: number;
    lookback_days?: number;
  },
) {
  const normalized = ticker?.trim().toUpperCase() ?? "";
  return useQuery<FinancialSymbolSignalDetail>({
    queryKey: ["financial", "signals", "detail", normalized, params],
    queryFn: () => api.get(`/api/financial/signals/${encodeURIComponent(normalized)}`, params),
    enabled: Boolean(normalized),
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
}

export function useFinancialWatchlistCandidates(params?: { limit?: number }) {
  return useQuery<FinancialWatchlistCandidatesResponse>({
    queryKey: ["financial", "signals", "watchlist-candidates", params],
    queryFn: () => api.get("/api/financial/signals/watchlist-candidates", params),
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
}

export function useFinancialDailyCalibration(params?: {
  since?: string;
  until?: string;
  ticker?: string;
  parameter_set?: string;
  top_tickers?: number;
}) {
  return useQuery<FinancialDailyCalibrationResponse>({
    queryKey: ["financial", "signals", "calibration", "daily", params],
    queryFn: () => api.get("/api/financial/signals/calibration/daily", params),
    staleTime: 10 * 60_000,
  });
}

// ---------------------------------------------------------------------------
// Properties
// ---------------------------------------------------------------------------
export function useProperties() {
  return useQuery<Property[]>({
    queryKey: ["properties", { limit: 1000 }],
    queryFn: () => api.get("/api/properties/", { limit: 1000 }),
  });
}

export function useProperty(id: string) {
  return useQuery<Property>({
    queryKey: ["properties", id],
    queryFn: () => api.get(`/api/properties/${id}`),
    enabled: !!id,
  });
}

export function useUpdateProperty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Property>) =>
      api.patch(`/api/properties/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["properties"] });
      toast.success("Property updated");
    },
    onError: () => toast.error("Failed to update property"),
  });
}

// ---------------------------------------------------------------------------
// Reservations
// ---------------------------------------------------------------------------
export function useReservations(params?: Record<string, string | number | boolean | undefined>) {
  return useQuery<Reservation[]>({
    queryKey: ["reservations", params],
    queryFn: () => api.get("/api/reservations/", params),
    staleTime: 0,
  });
}

export function useReservation(id: string) {
  return useQuery<Reservation>({
    queryKey: ["reservations", id],
    queryFn: () => api.get(`/api/reservations/${id}`),
    enabled: !!id,
    staleTime: 0,
  });
}

type StranglerGatewayReservation = {
  reservation_id: string;
  guest?: {
    guest_id?: string;
    first_name?: string;
    last_name?: string;
    email?: string;
    phone_number?: string;
    language_preference?: string;
  };
  property_name?: string;
  unit_id?: string;
  checkin_date?: string;
  checkout_date?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

type StranglerGatewayCurrentResponse = {
  reservation: StranglerGatewayReservation;
  trace_id: string;
};

type StranglerGatewayHistoryResponse = {
  phone_number: string;
  count: number;
  reservations: StranglerGatewayReservation[];
  trace_id: string;
};

function normalizeDate(dateLike?: string): string {
  if (!dateLike) return "";
  const d = new Date(dateLike);
  if (Number.isNaN(d.getTime())) return String(dateLike).slice(0, 10);
  return d.toISOString().slice(0, 10);
}

function mapStranglerReservation(input: StranglerGatewayReservation): Reservation {
  const now = new Date().toISOString();
  const confirmation = String(input.reservation_id || "");
  return {
    id: confirmation,
    confirmation_code: confirmation,
    guest_id: String(input.guest?.guest_id || ""),
    property_id: String(input.unit_id || ""),
    check_in_date: normalizeDate(input.checkin_date),
    check_out_date: normalizeDate(input.checkout_date),
    num_guests: 0,
    status: (input.status as Reservation["status"]) || "confirmed",
    pre_arrival_sent: false,
    access_info_sent: false,
    digital_guide_sent: false,
    created_at: input.created_at || now,
    property_name: input.property_name || "Unknown Property",
    guest_name: `${input.guest?.first_name || ""} ${input.guest?.last_name || ""}`.trim(),
    guest_email: input.guest?.email,
    guest_phone: input.guest?.phone_number,
  };
}

export function useStranglerCurrentReservation(phoneNumber: string) {
  const normalized = phoneNumber.trim();
  return useQuery<Reservation | null>({
    queryKey: ["strangler", "reservation-current", normalized],
    enabled: Boolean(normalized),
    queryFn: async () => {
      const data = await api.get<StranglerGatewayCurrentResponse>(
        `/api/strangler/reservations/${encodeURIComponent(normalized)}`,
      );
      if (!data?.reservation) return null;
      return mapStranglerReservation(data.reservation);
    },
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 2;
    },
    staleTime: 0,
  });
}

export function useStranglerReservationHistory(phoneNumber: string, maxPages = 5) {
  const normalized = phoneNumber.trim();
  return useQuery<Reservation[]>({
    queryKey: ["strangler", "reservation-history", normalized, maxPages],
    enabled: Boolean(normalized),
    queryFn: async () => {
      const data = await api.get<StranglerGatewayHistoryResponse>(
        `/api/strangler/reservations/history/${encodeURIComponent(normalized)}`,
        { max_pages: maxPages },
      );
      const rows = Array.isArray(data?.reservations) ? data.reservations : [];
      return rows.map(mapStranglerReservation);
    },
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 429) return failureCount < 3;
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 2;
    },
    retryDelay: (attempt, error) => {
      if (error instanceof ApiError && error.status === 429) {
        return Math.min(60_000, 10_000 * attempt);
      }
      return Math.min(5_000, 1_000 * attempt);
    },
    staleTime: 0,
  });
}

export function useUpdateReservation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; status?: string; internal_notes?: string; special_requests?: string; access_code?: string }) =>
      api.patch(`/api/reservations/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reservations"] });
      toast.success("Reservation updated");
    },
    onError: () => toast.error("Failed to update reservation"),
  });
}

export function useArrivingToday() {
  return useQuery<Reservation[]>({
    queryKey: ["reservations", "arriving-today"],
    queryFn: () => api.get("/api/reservations/arriving/today"),
    refetchInterval: 60_000,
    staleTime: 0,
  });
}

export function useDepartingToday() {
  return useQuery<Reservation[]>({
    queryKey: ["reservations", "departing-today"],
    queryFn: () => api.get("/api/reservations/departing/today"),
    refetchInterval: 60_000,
    staleTime: 0,
  });
}

// ---------------------------------------------------------------------------
// Guests
// ---------------------------------------------------------------------------
export function useGuests(params?: Record<string, string | number | boolean | undefined>) {
  return useQuery<Guest[]>({
    queryKey: ["guests", params],
    queryFn: () => api.get("/api/guests/", params),
  });
}

export function useGuest(id: string) {
  return useQuery<Guest>({
    queryKey: ["guests", id],
    queryFn: () => api.get(`/api/guests/${id}`),
    enabled: !!id,
  });
}

export function useCreateGuest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { first_name: string; last_name: string; phone_number: string; email?: string }) =>
      api.post("/api/guests/", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["guests"] });
      toast.success("Guest created");
    },
    onError: () => toast.error("Failed to create guest"),
  });
}

export function useUpdateGuest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<Guest>) =>
      api.patch(`/api/guests/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["guests"] });
      toast.success("Guest updated");
    },
    onError: () => toast.error("Failed to update guest"),
  });
}

export function useGuestActivity(id: string) {
  return useQuery({
    queryKey: ["guest-activity", id],
    queryFn: () => api.get(`/api/guests/${id}/activity`),
    enabled: !!id,
  });
}

export function useGuest360(id: string) {
  return useQuery({
    queryKey: ["guest-360", id],
    queryFn: () => api.get(`/api/guests/${id}/360`),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------
export function useConversations() {
  return useQuery<ConversationThread[]>({
    queryKey: ["conversations"],
    queryFn: () => api.get("/api/messages/threads"),
    refetchInterval: 15_000,
  });
}

export function useMessages(guestId: string) {
  return useQuery<Message[]>({
    queryKey: ["messages", guestId],
    queryFn: () => api.get(`/api/messages/`, { guest_id: guestId }),
    enabled: !!guestId,
    refetchInterval: 10_000,
  });
}

export function useMessagesByPhone(phone: string) {
  return useQuery<Message[]>({
    queryKey: ["messages-phone", phone],
    queryFn: () => api.get(`/api/messages/`, { phone_number: phone }),
    enabled: !!phone,
    refetchInterval: 10_000,
  });
}

export function useSendMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { to_phone: string; body: string; guest_id?: string }) =>
      api.post("/api/messages/send", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["messages"] });
      qc.invalidateQueries({ queryKey: ["messages-phone"] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: () => toast.error("Failed to send message"),
  });
}

export function useUnreadMessages() {
  return useQuery<Message[]>({
    queryKey: ["unread-messages"],
    queryFn: () => api.get("/api/messages/unread"),
    refetchInterval: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Work Orders
// ---------------------------------------------------------------------------
export function useWorkOrders(params?: Record<string, string | number | boolean | undefined>) {
  return useQuery<WorkOrder[]>({
    queryKey: ["work-orders", params],
    queryFn: () => api.get("/api/work-orders/", params),
  });
}

export function useCreateWorkOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { property_id: string; title: string; description: string; category?: string; priority?: string }) =>
      api.post("/api/work-orders/", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Work order created");
    },
    onError: () => toast.error("Failed to create work order"),
  });
}

export function useUpdateWorkOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; status?: string; assigned_to?: string; priority?: string; resolution_notes?: string }) =>
      api.patch(`/api/work-orders/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      toast.success("Work order updated");
    },
    onError: () => toast.error("Failed to update work order"),
  });
}

// ---------------------------------------------------------------------------
// Review Queue (DISABLED — backend endpoint /api/review-queue not yet migrated;
// was flooding logs with 404s every 15s. Re-enable when backend route exists.)
// ---------------------------------------------------------------------------
export function useReviewQueue() {
  return useQuery<ReviewQueueItem[]>({
    queryKey: ["review-queue"],
    queryFn: async () => [] as ReviewQueueItem[],
    enabled: false,
  });
}

export function useReviewAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { id: string; action: "approve" | "edit" | "reject"; edited_response?: string }) =>
      api.post(`/api/review-queue/${data.id}/${data.action}`, {
        edited_response: data.edited_response,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Review action applied");
    },
    onError: () => toast.error("Review action failed"),
  });
}

// ---------------------------------------------------------------------------
// SEO Review Queue (God Head / pending_human)
// ---------------------------------------------------------------------------
export function useSeoReviewQueue(status = "pending_human", limit = 50, offset = 0) {
  return useQuery<SeoReviewPatch[]>({
    queryKey: ["seo-review", "queue", status, limit, offset],
    queryFn: async () => {
      const response = await api.get<{ items: SeoReviewPatch[] }>("/api/seo/queue", {
        status,
        limit,
        offset,
      });
      return response.items ?? [];
    },
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
}

export function useSeoReviewPatch(patchId: string | null) {
  return useQuery<SeoReviewPatch>({
    queryKey: ["seo-review", "patch", patchId],
    queryFn: () => api.get<SeoReviewPatch>(`/api/seo/queue/${patchId}`),
    enabled: Boolean(patchId),
    staleTime: 5_000,
  });
}

export function useApproveSeoReviewPatch() {
  const qc = useQueryClient();
  return useMutation<
    SeoReviewPatch,
    Error,
    { patchId: string; final_payload?: Record<string, unknown>; note?: string }
  >({
    mutationFn: ({ patchId, ...payload }) => api.post(`/api/seo/queue/${patchId}/approve`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["seo-review"] });
      toast.success("Edge cache strike initiated.");
    },
    onError: (err) => toast.error(err.message || "Failed to approve SEO patch"),
  });
}

export function useRejectSeoReviewPatch() {
  const qc = useQueryClient();
  return useMutation<
    SeoReviewPatch,
    Error,
    { patchId: string; note?: string }
  >({
    mutationFn: ({ patchId, ...payload }) => api.post(`/api/seo/queue/${patchId}/reject`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["seo-review"] });
      toast.success("SEO patch rejected and archived.");
    },
    onError: (err) => toast.error(err.message || "Failed to reject SEO patch"),
  });
}

function normalizeSeoPatchFilters(
  params: SeoPatchQueueFilters | undefined,
): Required<Pick<SeoPatchQueueFilters, "status" | "limit" | "offset">> &
  Omit<SeoPatchQueueFilters, "status" | "limit" | "offset"> {
  return {
    status: params?.status ?? "proposed",
    campaign: params?.campaign,
    target_type: params?.target_type,
    target_slug: params?.target_slug,
    property_id: params?.property_id,
    limit: params?.limit ?? 100,
    offset: params?.offset ?? 0,
  };
}

function mapSeoReviewPatchStatus(status: string): SeoPatchQueueItem["status"] {
  switch (status) {
    case "needs_rewrite":
      return "needs_revision";
    case "approved":
    case "edited":
      return "approved";
    case "rejected":
      return "rejected";
    case "deployed":
      return "deployed";
    case "drafted":
    case "grading":
    case "pending_human":
      return "proposed";
    default:
      return "superseded";
  }
}

function deriveSeoTargetSlug(patch: SeoReviewPatch): string {
  if (patch.property_slug?.trim()) {
    return patch.property_slug.trim();
  }

  const pagePath = patch.page_path.trim();
  if (!pagePath) {
    return patch.id;
  }

  const segments = pagePath.split("/").filter(Boolean);
  return segments.at(-1) ?? patch.id;
}

function buildSeoApprovedPayload(patch: SeoReviewPatch): Record<string, unknown> {
  if (patch.final_payload && Object.keys(patch.final_payload).length > 0) {
    return patch.final_payload;
  }

  return {
    title: patch.title ?? "",
    meta_description: patch.meta_description ?? "",
    og_title: patch.og_title,
    og_description: patch.og_description,
    h1_suggestion: patch.h1_suggestion,
    jsonld: patch.jsonld_payload ?? {},
    canonical_url: patch.canonical_url,
    alt_tags: patch.alt_tags ?? {},
  };
}

function mapSeoReviewPatchToQueueItem(patch: SeoReviewPatch): SeoPatchQueueItem {
  const targetSlug = deriveSeoTargetSlug(patch);
  const scoreOverall =
    typeof patch.godhead_score === "number"
      ? (patch.godhead_score <= 1 ? patch.godhead_score * 100 : patch.godhead_score)
      : null;

  return {
    id: patch.id,
    target_type: "property",
    target_slug: targetSlug,
    property_id: patch.property_id ?? null,
    status: mapSeoReviewPatchStatus(patch.status),
    target_keyword: "",
    campaign: "canonical-seopatch",
    rubric_version: patch.rubric_id ?? "",
    source_hash: patch.id,
    proposed_title: patch.title ?? "",
    proposed_meta_description: patch.meta_description ?? "",
    proposed_h1: patch.h1_suggestion ?? "",
    proposed_intro: "",
    proposed_faq: [],
    proposed_json_ld: patch.jsonld_payload ?? {},
    fact_snapshot: {
      property_slug: patch.property_slug,
      property_name: patch.property_name,
      page_path: patch.page_path,
      canonical_url: patch.canonical_url,
      deploy_status: patch.deploy_status,
    },
    score_overall: scoreOverall,
    score_breakdown: {},
    proposed_by: patch.swarm_model ?? "unknown",
    proposal_run_id: patch.deploy_task_id,
    reviewed_by: patch.reviewed_by,
    review_note: null,
    approved_payload: buildSeoApprovedPayload(patch),
    approved_at: patch.reviewed_at,
    deployed_at: patch.deployed_at,
    created_at: patch.created_at ?? null,
    updated_at: patch.updated_at ?? null,
  };
}

function matchesSeoPatchQueueFilters(
  item: SeoPatchQueueItem,
  filters: ReturnType<typeof normalizeSeoPatchFilters>,
): boolean {
  if (filters.status !== "all" && item.status !== filters.status) {
    return false;
  }
  if (filters.target_type && item.target_type !== filters.target_type) {
    return false;
  }
  if (filters.target_slug && item.target_slug !== filters.target_slug) {
    return false;
  }
  if (filters.property_id && item.property_id !== filters.property_id) {
    return false;
  }
  if (filters.campaign && item.campaign !== filters.campaign) {
    return false;
  }
  return true;
}

async function runSeoPatchBulkAction(
  action: "approve" | "reject",
  ids: string[],
  note?: string,
): Promise<SeoPatchBulkReviewResult> {
  const trimmedNote = note?.trim();
  const payload = trimmedNote ? { note: trimmedNote } : {};

  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        const response = await api.post<SeoReviewPatch>(
          `/api/seo/queue/${id}/${action}`,
          payload,
        );
        return { ok: true as const, item: mapSeoReviewPatchToQueueItem(response) };
      } catch (error) {
        return {
          ok: false as const,
          id,
          message: error instanceof Error ? error.message : "Unknown error",
        };
      }
    }),
  );

  return {
    succeeded: results.flatMap((result) => (result.ok ? [result.item] : [])),
    failed: results.flatMap((result) =>
      result.ok ? [] : [{ id: result.id, message: result.message }],
    ),
  };
}

// ---------------------------------------------------------------------------
// SEO Patch Queue (HITL)
// ---------------------------------------------------------------------------
export function useSeoPatchQueue(params?: SeoPatchQueueFilters) {
  const normalized = normalizeSeoPatchFilters(params);
  return useQuery<SeoPatchQueueResponse>({
    queryKey: ["seo-patches", "queue", normalized],
    queryFn: async () => {
      const response = await api.get<{
        items: SeoReviewPatch[];
        total: number;
        offset: number;
        limit: number;
      }>("/api/seo/queue", {
        status: "all",
        limit: 200,
        offset: 0,
      });

      const filtered = response.items
        .map(mapSeoReviewPatchToQueueItem)
        .filter((item) => matchesSeoPatchQueueFilters(item, normalized));

      return {
        items: filtered.slice(
          normalized.offset,
          normalized.offset + normalized.limit,
        ),
        total: filtered.length,
        offset: normalized.offset,
        limit: normalized.limit,
      };
    },
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
}

export function useBulkApproveSeoPatches() {
  const qc = useQueryClient();
  return useMutation<
    SeoPatchBulkReviewResult,
    Error,
    { ids: string[]; note?: string }
  >({
    mutationFn: ({ ids, note }) => runSeoPatchBulkAction("approve", ids, note),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["seo-patches"] });
      if (result.failed.length > 0 && result.succeeded.length > 0) {
        toast.error(
          `Approved ${result.succeeded.length} patch${result.succeeded.length === 1 ? "" : "es"}; ${result.failed.length} failed.`,
        );
        return;
      }
      if (result.failed.length > 0) {
        toast.error("SEO approval failed");
        return;
      }
      toast.success(
        `Approved ${result.succeeded.length} SEO patch${result.succeeded.length === 1 ? "" : "es"}`,
      );
    },
    onError: (err) => toast.error(err.message || "Failed to approve SEO patches"),
  });
}

export function useBulkRejectSeoPatches() {
  const qc = useQueryClient();
  return useMutation<
    SeoPatchBulkReviewResult,
    Error,
    { ids: string[]; note: string }
  >({
    mutationFn: ({ ids, note }) => runSeoPatchBulkAction("reject", ids, note),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["seo-patches"] });
      if (result.failed.length > 0 && result.succeeded.length > 0) {
        toast.error(
          `Rejected ${result.succeeded.length} patch${result.succeeded.length === 1 ? "" : "es"}; ${result.failed.length} failed.`,
        );
        return;
      }
      if (result.failed.length > 0) {
        toast.error("SEO rejection failed");
        return;
      }
      toast.success(
        `Rejected ${result.succeeded.length} SEO patch${result.succeeded.length === 1 ? "" : "es"}`,
      );
    },
    onError: (err) => toast.error(err.message || "Failed to reject SEO patches"),
  });
}

async function runSeoRedirectRemapBulkAction(
  action: "approve" | "reject",
  ids: string[],
  note?: string,
): Promise<SeoRedirectRemapBulkReviewResult> {
  const trimmedNote = note?.trim();
  const payload = trimmedNote ? { note: trimmedNote } : {};

  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        const response = await api.post<SeoRedirectRemapReviewResponse>(
          `/api/seo-remaps/${id}/${action}`,
          payload,
        );
        return { ok: true as const, item: response.item };
      } catch (error) {
        return {
          ok: false as const,
          id,
          message: error instanceof Error ? error.message : "Unknown error",
        };
      }
    }),
  );

  return {
    succeeded: results.flatMap((result) => (result.ok ? [result.item] : [])),
    failed: results.flatMap((result) =>
      result.ok ? [] : [{ id: result.id, message: result.message }],
    ),
  };
}

export function useSeoRedirectRemapQueue(params?: SeoRedirectRemapFilters) {
  const normalized = {
    status: params?.status ?? "promoted",
    campaign: params?.campaign,
    limit: params?.limit ?? 100,
    offset: params?.offset ?? 0,
  };
  return useQuery<SeoRedirectRemapQueueResponse>({
    queryKey: ["seo-remaps", "queue", normalized],
    queryFn: () => api.get("/api/seo-remaps/queue", normalized),
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
}

export function useBulkApproveSeoRedirectRemaps() {
  const qc = useQueryClient();
  return useMutation<
    SeoRedirectRemapBulkReviewResult,
    Error,
    { ids: string[]; note?: string }
  >({
    mutationFn: ({ ids, note }) => runSeoRedirectRemapBulkAction("approve", ids, note),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["seo-remaps"] });
      if (result.failed.length > 0 && result.succeeded.length > 0) {
        toast.error(
          `Approved ${result.succeeded.length} remap${result.succeeded.length === 1 ? "" : "s"}; ${result.failed.length} failed.`,
        );
        return;
      }
      if (result.failed.length > 0) {
        toast.error("Redirect remap approval failed");
        return;
      }
      toast.success(
        `Approved ${result.succeeded.length} redirect remap${result.succeeded.length === 1 ? "" : "s"}`,
      );
    },
    onError: (err) => toast.error(err.message || "Failed to approve redirect remaps"),
  });
}

export function useBulkRejectSeoRedirectRemaps() {
  const qc = useQueryClient();
  return useMutation<
    SeoRedirectRemapBulkReviewResult,
    Error,
    { ids: string[]; note: string }
  >({
    mutationFn: ({ ids, note }) => runSeoRedirectRemapBulkAction("reject", ids, note),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["seo-remaps"] });
      if (result.failed.length > 0 && result.succeeded.length > 0) {
        toast.error(
          `Rejected ${result.succeeded.length} remap${result.succeeded.length === 1 ? "" : "s"}; ${result.failed.length} failed.`,
        );
        return;
      }
      if (result.failed.length > 0) {
        toast.error("Redirect remap rejection failed");
        return;
      }
      toast.success(
        `Rejected ${result.succeeded.length} redirect remap${result.succeeded.length === 1 ? "" : "s"}`,
      );
    },
    onError: (err) => toast.error(err.message || "Failed to reject redirect remaps"),
  });
}

// ---------------------------------------------------------------------------
// Message Templates
// ---------------------------------------------------------------------------
export function useMessageTemplates() {
  return useQuery<MessageTemplate[]>({
    queryKey: ["message-templates"],
    queryFn: () => api.get("/api/agent/templates"),
  });
}

// ---------------------------------------------------------------------------
// Housekeeping
// ---------------------------------------------------------------------------
export function useHousekeepingToday() {
  return useQuery({
    queryKey: ["housekeeping-today"],
    queryFn: () => api.get("/api/housekeeping/today"),
  });
}

export function useHousekeepingWeek() {
  return useQuery({
    queryKey: ["housekeeping-week"],
    queryFn: () => api.get("/api/housekeeping/week"),
  });
}

// ---------------------------------------------------------------------------
// Owner Portal
// ---------------------------------------------------------------------------
export function useOwnerDashboard(ownerId: string) {
  return useQuery({
    queryKey: ["owner-dashboard", ownerId],
    queryFn: () => api.get(`/api/owner/dashboard/${ownerId}`),
    enabled: !!ownerId,
  });
}

export function useOwnerStatements(ownerId: string) {
  return useQuery({
    queryKey: ["owner-statements", ownerId],
    queryFn: () => api.get(`/api/owner/statements/${ownerId}`),
    enabled: !!ownerId,
  });
}

export function useOwnerReservations(ownerId: string) {
  return useQuery({
    queryKey: ["owner-reservations", ownerId],
    queryFn: () => api.get(`/api/owner/reservations/${ownerId}`),
    enabled: !!ownerId,
  });
}

export function useOwnerBalances(ownerId: string) {
  return useQuery({
    queryKey: ["owner-balances", ownerId],
    queryFn: () => api.get(`/api/owner/balances/${ownerId}`),
    enabled: !!ownerId,
  });
}

export function useIronDomeActivity(propertyId: string) {
  return useQuery({
    queryKey: ["iron-dome-activity", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/iron-dome/activity`),
    enabled: !!propertyId,
  });
}

export function useLegacyStatements(propertyId: string) {
  return useQuery<{ statements: Array<{ id: string; month: string; period_start: string; period_end: string; source: string; download_url: string }> }>({
    queryKey: ["legacy-statements", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/statements/legacy`),
    enabled: !!propertyId,
  });
}

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------
export function useStreamlineStatus() {
  return useQuery({
    queryKey: ["streamline-status"],
    queryFn: () => api.get("/api/integrations/streamline/status"),
  });
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
export function useGlobalSearch(q: string) {
  return useQuery({
    queryKey: ["search", q],
    queryFn: () => api.get("/api/search/", { q }),
    enabled: q.length >= 2,
  });
}

// ---------------------------------------------------------------------------
// Channel Manager
// ---------------------------------------------------------------------------
export function useChannelStatus() {
  return useQuery({
    queryKey: ["channel-status"],
    queryFn: () => api.get("/api/channel-manager/status"),
  });
}

// ---------------------------------------------------------------------------
// Guestbook
// ---------------------------------------------------------------------------
export function useGuestbooks() {
  return useQuery({
    queryKey: ["guestbooks"],
    queryFn: () => api.get("/api/guestbook/"),
  });
}

export function useGuestbook(id: string) {
  return useQuery({
    queryKey: ["guestbook", id],
    queryFn: () => api.get(`/api/guestbook/${id}`),
    enabled: !!id,
  });
}

export function useExtras() {
  return useQuery({
    queryKey: ["extras"],
    queryFn: () => api.get("/api/guestbook/extras"),
  });
}

// ---------------------------------------------------------------------------
// Damage Claims
// ---------------------------------------------------------------------------
export function useDamageClaims(params?: Record<string, string | number | boolean | undefined>) {
  return useQuery({
    queryKey: ["damage-claims", params],
    queryFn: () => api.get("/api/damage-claims/", params),
  });
}

export function useDamageClaimStats() {
  return useQuery({
    queryKey: ["damage-claim-stats"],
    queryFn: () => api.get("/api/damage-claims/stats"),
  });
}

export function useDamageClaim(id: string) {
  return useQuery({
    queryKey: ["damage-claims", id],
    queryFn: () => api.get(`/api/damage-claims/${id}`),
    enabled: !!id,
  });
}

export function useCreateDamageClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      reservation_id: string;
      property_id: string;
      guest_id: string;
      damage_description: string;
      damage_areas?: string[];
      estimated_cost?: number;
      inspection_notes?: string;
    }) => api.post("/api/damage-claims/", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["damage-claims"] });
      qc.invalidateQueries({ queryKey: ["damage-claim-stats"] });
      toast.success("Damage claim created");
    },
    onError: () => toast.error("Failed to create damage claim"),
  });
}

export function useUpdateDamageClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      api.patch(`/api/damage-claims/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["damage-claims"] });
      toast.success("Damage claim updated");
    },
    onError: () => toast.error("Failed to update damage claim"),
  });
}

export function useGenerateLegalDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (claimId: string) =>
      api.post(`/api/damage-claims/${claimId}/generate-legal-draft`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["damage-claims"] });
      toast.success("Legal draft generated");
    },
    onError: () => toast.error("Failed to generate legal draft"),
  });
}

export function useApproveDamageClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (claimId: string) =>
      api.post(`/api/damage-claims/${claimId}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["damage-claims"] });
      toast.success("Claim approved");
    },
    onError: () => toast.error("Failed to approve claim"),
  });
}

export function useSendDamageClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, via }: { id: string; via: string }) =>
      api.post(`/api/damage-claims/${id}/send`, { via }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["damage-claims"] });
      toast.success("Claim response sent to guest");
    },
    onError: () => toast.error("Failed to send claim"),
  });
}

export function useReservationOptions() {
  return useQuery({
    queryKey: ["reservation-options"],
    queryFn: () => api.get("/api/damage-claims/reservation-options"),
  });
}

export function useChargeDamageClaim() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, amount, note }: { id: string; amount: number; note?: string }) =>
      api.post<{ charged: boolean; stripe_charge_id?: string; amount_charged?: number; moto_fallback?: boolean; message?: string }>(
        `/api/damage-claims/${id}/charge`,
        { amount, note },
      ),
    onSuccess: (data) => {
      if (data.charged) {
        qc.invalidateQueries({ queryKey: ["damage-claims"] });
        toast.success(`Guest charged $${data.amount_charged?.toFixed(2)} — Stripe ID: ${data.stripe_charge_id}`);
      } else if (data.moto_fallback) {
        toast.warning(data.message || "No saved payment method — use MOTO terminal");
      }
    },
    onError: (err: Error) => toast.error(`Charge failed: ${err.message}`),
  });
}

// ---------------------------------------------------------------------------
// Housekeeping (Enhanced)
// ---------------------------------------------------------------------------
export function useScheduleTurnover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reservationId: string) =>
      api.post(`/api/housekeeping/schedule/${reservationId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["housekeeping-today"] });
      qc.invalidateQueries({ queryKey: ["housekeeping-week"] });
      toast.success("Turnover scheduled");
    },
    onError: () => toast.error("Failed to schedule turnover"),
  });
}

export function useAssignCleaner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, cleanerName }: { taskId: string; cleanerName: string }) =>
      api.post(`/api/housekeeping/${taskId}/assign`, { cleaner_name: cleanerName }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["housekeeping-today"] });
      toast.success("Cleaner assigned");
    },
    onError: () => toast.error("Failed to assign cleaner"),
  });
}

export function useCompleteTurnover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, notes, photosCount }: { taskId: string; notes?: string; photosCount?: number }) =>
      api.post(`/api/housekeeping/${taskId}/complete`, { notes, photos_count: photosCount }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["housekeeping-today"] });
      qc.invalidateQueries({ queryKey: ["housekeeping-week"] });
      toast.success("Turnover completed");
    },
    onError: () => toast.error("Failed to complete turnover"),
  });
}

export function useAutoScheduleHousekeeping() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/api/housekeeping/auto-schedule"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["housekeeping-today"] });
      qc.invalidateQueries({ queryKey: ["housekeeping-week"] });
      toast.success("Turnovers auto-scheduled");
    },
    onError: () => toast.error("Failed to auto-schedule"),
  });
}

export function useCleaningStatus(propertyId: string) {
  return useQuery({
    queryKey: ["cleaning-status", propertyId],
    queryFn: () => api.get(`/api/housekeeping/status/${propertyId}`),
    enabled: !!propertyId,
  });
}

export function useLinenRequirements(propertyId: string) {
  return useQuery({
    queryKey: ["linen-requirements", propertyId],
    queryFn: () => api.get(`/api/housekeeping/linen/${propertyId}`),
    enabled: !!propertyId,
  });
}

// ---------------------------------------------------------------------------
// Inspections (CF-01 GuardianOps bridge)
// ---------------------------------------------------------------------------
export function useInspectionHistory(params?: Record<string, string | number | boolean | undefined>) {
  return useQuery({
    queryKey: ["inspections", params],
    queryFn: () => api.get("/api/inspections/history", params),
  });
}

export function useInspectionSummary() {
  return useQuery({
    queryKey: ["inspection-summary"],
    queryFn: () => api.get("/api/inspections/summary"),
  });
}

export function useFailedInspections(params?: Record<string, string | number | boolean | undefined>) {
  return useQuery({
    queryKey: ["inspections-failed", params],
    queryFn: () => api.get("/api/inspections/failed-items", params),
  });
}

// ---------------------------------------------------------------------------
// Property Utilities & Services
// ---------------------------------------------------------------------------
export function usePropertyUtilities(propertyId?: string) {
  return useQuery<PropertyUtility[]>({
    queryKey: ["property-utilities", propertyId],
    queryFn: () => api.get(`/api/utilities/property/${propertyId}`),
    enabled: !!propertyId,
  });
}

export function useServiceTypes() {
  return useQuery<string[]>({
    queryKey: ["service-types"],
    queryFn: () => api.get("/api/utilities/types"),
    staleTime: 600_000,
  });
}

export function useCreateUtility() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => api.post("/api/utilities/", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["property-utilities"] });
      toast.success("Service account added");
    },
    onError: () => toast.error("Failed to add service account"),
  });
}

export function useUpdateUtility() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      api.patch(`/api/utilities/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["property-utilities"] });
      toast.success("Service account updated");
    },
    onError: () => toast.error("Failed to update service account"),
  });
}

export function useDeleteUtility() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/utilities/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["property-utilities"] });
      toast.success("Service account removed");
    },
    onError: () => toast.error("Failed to remove service account"),
  });
}

export function useRevealPassword(utilityId?: string) {
  return useQuery<{ password: string | null }>({
    queryKey: ["utility-password", utilityId],
    queryFn: () => api.get(`/api/utilities/${utilityId}/password`),
    enabled: false,
  });
}

export function useAddReading() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ utilityId, ...data }: { utilityId: string } & Record<string, unknown>) =>
      api.post(`/api/utilities/${utilityId}/readings`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["property-utilities"] });
      qc.invalidateQueries({ queryKey: ["utility-readings"] });
      qc.invalidateQueries({ queryKey: ["utility-cost-analytics"] });
      toast.success("Cost reading added");
    },
    onError: () => toast.error("Failed to add reading"),
  });
}

export function useUtilityReadings(utilityId?: string) {
  return useQuery<UtilityReading[]>({
    queryKey: ["utility-readings", utilityId],
    queryFn: () => api.get(`/api/utilities/${utilityId}/readings`),
    enabled: !!utilityId,
  });
}

export function useUtilityCostAnalytics(propertyId?: string, period?: string) {
  return useQuery<UtilityCostSummary>({
    queryKey: ["utility-cost-analytics", propertyId, period],
    queryFn: () => api.get(`/api/utilities/analytics/${propertyId}`, { period }),
    enabled: !!propertyId,
  });
}

// ---------------------------------------------------------------------------
// Staff Management
// ---------------------------------------------------------------------------
export function useStaffUsers() {
  return useQuery<StaffUserDetail[]>({
    queryKey: ["staff-users"],
    queryFn: () => api.get("/api/auth/users"),
  });
}

export function useRegisterUser() {
  const qc = useQueryClient();
  return useMutation<StaffUserDetail, Error, Record<string, unknown>>({
    mutationFn: (data) => api.post("/api/auth/register", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff-users"] });
      toast.success("User created successfully");
    },
    onError: (err) => {
      toast.error(err.message || "Failed to create user");
    },
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (userId) => api.delete(`/api/auth/users/${userId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff-users"] });
      toast.success("User deactivated");
    },
    onError: (err) => {
      toast.error(err.message || "Failed to deactivate user");
    },
  });
}

export function useResetUserPassword() {
  return useMutation<unknown, Error, { userId: string; new_password: string }>({
    mutationFn: ({ userId, new_password }) =>
      api.post(`/api/auth/users/${userId}/reset-password`, { new_password }),
    onSuccess: () => {
      toast.success("Password reset successfully");
    },
    onError: (err) => {
      toast.error(err.message || "Failed to reset password");
    },
  });
}

// ---------------------------------------------------------------------------
// Invitations
// ---------------------------------------------------------------------------
export function useInvites() {
  return useQuery<StaffInvite[]>({
    queryKey: ["staff-invites"],
    queryFn: () => api.get("/api/invites/"),
  });
}

export function useSendInvite() {
  const qc = useQueryClient();
  return useMutation<
    StaffInvite & { email_sent: boolean },
    Error,
    { email: string; first_name: string; last_name: string; role: string }
  >({
    mutationFn: (data) => api.post("/api/invites/", data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["staff-invites"] });
      if (data.email_sent) {
        toast.success(`Invitation sent to ${data.email}`);
      } else {
        toast.success("Invitation created (email delivery unavailable — share the link manually)");
      }
    },
    onError: (err) => toast.error(err.message || "Failed to send invitation"),
  });
}

export function useResendInvite() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (inviteId) => api.post(`/api/invites/${inviteId}/resend`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff-invites"] });
      toast.success("Invitation resent");
    },
    onError: (err) => toast.error(err.message || "Failed to resend"),
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (inviteId) => api.post(`/api/invites/${inviteId}/revoke`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff-invites"] });
      toast.success("Invitation revoked");
    },
    onError: (err) => toast.error(err.message || "Failed to revoke"),
  });
}

// ---------------------------------------------------------------------------
// VRS Rule Engine / Automations
// ---------------------------------------------------------------------------

export function useAutomationRules(activeOnly = false) {
  return useQuery<AutomationRule[]>({
    queryKey: ["automation-rules", activeOnly],
    queryFn: () =>
      api.get("/api/rules/", activeOnly ? { active_only: true } : undefined),
  });
}

export function useAutomationEvents(limit = 50) {
  return useQuery<AutomationEventEntry[]>({
    queryKey: ["automation-events", limit],
    queryFn: () => api.get("/api/rules/events", { limit }),
  });
}

export function useQueueStatus() {
  return useQuery<QueueStatus>({
    queryKey: ["automation-queue-status"],
    queryFn: () => api.get("/api/rules/queue-status"),
    refetchInterval: 30_000,
  });
}

export function useEmailTemplates() {
  return useQuery<EmailTemplateSummary[]>({
    queryKey: ["email-templates"],
    queryFn: () => api.get("/api/rules/email-templates"),
    staleTime: 60_000,
  });
}

export function useTemplateLibrary() {
  return useQuery<FullEmailTemplate[]>({
    queryKey: ["template-library"],
    queryFn: () => api.get("/api/templates"),
    staleTime: 60_000,
  });
}

export function useCreateRule() {
  const qc = useQueryClient();
  return useMutation<AutomationRule, Error, Record<string, unknown>>({
    mutationFn: (data) => api.post("/api/rules/", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["automation-rules"] });
      toast.success("Automation rule created");
    },
    onError: (err) => toast.error(err.message || "Failed to create rule"),
  });
}

export function useUpdateRule() {
  const qc = useQueryClient();
  return useMutation<
    AutomationRule,
    Error,
    { id: string; data: Record<string, unknown> }
  >({
    mutationFn: ({ id, data }) => api.put(`/api/rules/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["automation-rules"] });
      toast.success("Rule updated");
    },
    onError: (err) => toast.error(err.message || "Failed to update rule"),
  });
}

export function useDeleteRule() {
  const qc = useQueryClient();
  return useMutation<AutomationRule, Error, string>({
    mutationFn: (id) => api.delete(`/api/rules/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["automation-rules"] });
      toast.success("Rule deactivated");
    },
    onError: (err) => toast.error(err.message || "Failed to deactivate rule"),
  });
}

export function useTestRule() {
  return useMutation<
    { rule_id: string; rule_name: string; match: boolean },
    Error,
    { ruleId: string; payload: Record<string, unknown> }
  >({
    mutationFn: ({ ruleId, payload }) =>
      api.post(`/api/rules/${ruleId}/test`, payload),
    onSuccess: (data) => {
      if (data.match) {
        toast.success(`Rule "${data.rule_name}" would fire`);
      } else {
        toast.info(`Rule "${data.rule_name}" would NOT fire`);
      }
    },
    onError: (err) => toast.error(err.message || "Dry-run failed"),
  });
}

// ---------------------------------------------------------------------------
// System Health (bare-metal dashboard — 30s polling)
// ---------------------------------------------------------------------------
export function useSystemHealth() {
  return useQuery<SystemHealthResponse>({
    queryKey: ["system-health"],
    queryFn: () => api.get<SystemHealthResponse>("/api/system-health"),
    refetchInterval: false,
    retry: 2,
    staleTime: Infinity,
  });
}

export function useNemoCommandCenter() {
  return useQuery<NemoCommandCenterResponse>({
    queryKey: ["nemo-command-center"],
    queryFn: () => api.get<NemoCommandCenterResponse>("/api/trust-ledger/command-center"),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useCommandC2Root() {
  return useQuery<CommandC2RootResponse>({
    queryKey: ["command-c2", "root"],
    queryFn: () => api.get<CommandC2RootResponse>("/api/telemetry/"),
    refetchInterval: 30_000,
    retry: 1,
    staleTime: 10_000,
  });
}

export function useCommandC2Pulse() {
  return useQuery<CommandC2PulseResponse>({
    queryKey: ["command-c2", "pulse"],
    queryFn: () => api.get<CommandC2PulseResponse>("/api/telemetry/pulse"),
    refetchInterval: 20_000,
    retry: 1,
    staleTime: 8_000,
  });
}

export function useVerifyCommandC2() {
  const qc = useQueryClient();
  return useMutation<CommandC2VerificationResponse, Error, void>({
    mutationFn: () => api.get<CommandC2VerificationResponse>("/api/telemetry/verify"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["command-c2"] });
      toast.success("Sovereign link verified");
    },
    onError: (err) => {
      toast.error(err.message || "Sovereign link verification failed");
    },
  });
}

export function useRestartCommandC2Service() {
  const qc = useQueryClient();
  return useMutation<CommandC2ActionResponse, Error, { service: string }>({
    mutationFn: ({ service }) =>
      api.post<CommandC2ActionResponse>("/api/telemetry/action/restart", { service }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["command-c2"] });
      qc.invalidateQueries({ queryKey: ["system-health"] });
      toast.success(data.message || "Service restart executed");
    },
    onError: (err) => {
      toast.error(err.message || "Failed to restart service");
    },
  });
}

export function useSovereignPulse() {
  return useQuery<SovereignPulseResponse>({
    queryKey: ["sovereign-pulse"],
    queryFn: () => api.get<SovereignPulseResponse>("/api/telemetry/sovereign-pulse"),
    refetchInterval: 20_000,
    retry: 2,
    staleTime: 5_000,
  });
}

export function useFunnelHQ(query?: Record<string, string | number | boolean | undefined>) {
  return useQuery<FunnelHQResponse>({
    queryKey: ["funnel-hq", query ?? {}],
    queryFn: () => api.get<FunnelHQResponse>("/api/telemetry/funnel-hq", query),
    refetchInterval: 45_000,
    retry: 2,
    staleTime: 10_000,
  });
}

/** GET /api/intelligence/market-snapshot/latest — Gate D analytics payload (read-only). */
export function useMarketSnapshotLatest() {
  return useQuery<{
    snapshot_hash: string | null;
    generated_at?: string;
    summary?: Record<string, unknown>;
    error?: string;
    detail?: string;
  }>({
    queryKey: ["intelligence-market-snapshot-latest"],
    queryFn: () => api.get("/api/intelligence/market-snapshot/latest"),
    staleTime: 60_000,
    retry: 1,
  });
}

/** GET /api/intelligence/market-snapshot/shadow-board — Shadow Pricing Board queue. */
export function useMarketShadowBoard(limit = 50) {
  return useQuery<{ entries: Record<string, unknown>[]; total: number }>({
    queryKey: ["intelligence-market-shadow-board", limit],
    queryFn: () =>
      api.get("/api/intelligence/market-snapshot/shadow-board", { limit }),
    staleTime: 30_000,
  });
}

export function useHunterHealth() {
  return useQuery<{ status: string; service: string }>({
    queryKey: ["hunter-health"],
    queryFn: () => api.get("/api/hunter/health"),
    staleTime: 60_000,
    retry: 1,
  });
}

/** GET /api/hunter/queue — present when Reactivation Hunter API is mounted on the backend. */
export function useHunterQueue(status = "pending_review", limit = 50) {
  return useQuery<unknown[]>({
    queryKey: ["hunter-queue", status, limit],
    queryFn: () =>
      api.get("/api/hunter/queue", { status_filter: status, limit }),
    retry: false,
  });
}

export function useShadowSummary() {
  return useQuery<ShadowAuditSummaryResponse>({
    queryKey: ["shadow-summary"],
    queryFn: () => api.get("/api/openshell/audit/shadow-summary"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

export function useHistoricalRecoverySummary(hours = 24) {
  return useQuery<HistoricalRecoverySummaryResponse>({
    queryKey: ["historical-recovery-summary", hours],
    queryFn: () => api.get("/api/openshell/audit/historical-recovery-summary", { hours }),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useCheckoutParity() {
  return useQuery<CheckoutParityResponse>({
    queryKey: ["checkout-parity"],
    queryFn: () => api.get<CheckoutParityResponse>("/api/telemetry/checkout-parity"),
    refetchInterval: 10_000,
    retry: 2,
    staleTime: 5_000,
  });
}

export function useParityDashboard() {
  return useQuery<ParityDashboardResponse>({
    queryKey: ["parity-dashboard"],
    queryFn: () => api.get<ParityDashboardResponse>("/api/telemetry/parity-dashboard"),
    refetchInterval: 10_000,
    retry: 2,
    staleTime: 5_000,
  });
}

export function useTriggerSeoParityObservation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/api/telemetry/seo-parity/observe", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parity-dashboard"] });
      toast.success("SEMRush observation strike executed.");
    },
    onError: (err: Error) => {
      toast.error(err.message || "SEMRush observation strike failed");
    },
  });
}

export const useVrsDashboardStats = useDashboardStats;
export const useVrsProperties = useProperties;
export const useVrsReservations = useReservations;
export const useVrsArrivingToday = useArrivingToday;
export const useVrsDepartingToday = useDepartingToday;
export const useVrsGuests = useGuests;

export function useStreamlineQuoteProperties(forceRefresh = false) {
  return useQuery<StreamlineQuotePropertyCatalogResponse>({
    queryKey: ["streamline-quote-properties", forceRefresh],
    queryFn: () =>
      api.get(
        `/api/quotes/streamline/properties${forceRefresh ? "?force_refresh=true" : ""}`,
      ),
    staleTime: 300_000,
  });
}

export function useStreamlineMasterCalendar(
  propertyId: string,
  start: string,
  end: string,
  forceRefresh = false,
) {
  const params = new URLSearchParams({ start, end });
  if (forceRefresh) {
    params.set("force_refresh", "true");
  }

  return useQuery<StreamlineMasterCalendarResponse>({
    queryKey: ["streamline-master-calendar", propertyId, start, end, forceRefresh],
    queryFn: () =>
      api.get(`/api/quotes/streamline/calendar/${propertyId}?${params.toString()}`),
    enabled: Boolean(propertyId && start && end),
    refetchInterval: 60_000,
  });
}

export function useStreamlineDeterministicQuote() {
  return useMutation<
    StreamlineDeterministicQuoteResponse,
    Error,
    {
      property_id: string;
      check_in: string;
      check_out: string;
      adults: number;
      children?: number;
      pets?: number;
      selected_add_on_ids?: string[];
      force_refresh?: boolean;
    }
  >({
    mutationFn: (payload) => api.post("/api/quotes/streamline/quote", payload),
  });
}

export function useVrsAddOns(propertyId?: string) {
  const params = new URLSearchParams();
  if (propertyId) {
    params.set("property_id", propertyId);
  }

  return useQuery<VrsAddOn[]>({
    queryKey: ["vrs-add-ons", propertyId],
    queryFn: () =>
      api.get(`/api/quotes/add-ons${params.toString() ? `?${params.toString()}` : ""}`),
    enabled: true,
    staleTime: 300_000,
  });
}

export function useRefreshStreamlineQuoteCache() {
  const qc = useQueryClient();
  return useMutation<
    StreamlineRefreshResponse,
    Error,
    {
      property_id: string;
      start_date: string;
      end_date: string;
    }
  >({
    mutationFn: (payload) => api.post("/api/quotes/streamline/refresh", payload),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: ["streamline-master-calendar", variables.property_id],
      });
      qc.invalidateQueries({ queryKey: ["streamline-quote-properties"] });
      toast.success("Streamline cache refreshed");
    },
    onError: (err) => toast.error(err.message || "Streamline cache refresh failed"),
  });
}

// ── Taylor Quote System ────────────────────────────────────────────────────────

export type TaylorPropertyOption = {
  property_id: string;
  property_name: string;
  slug: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  hero_image_url: string | null;
  base_rent: number;
  taxes: number;
  fees: number;
  total_amount: number;
  nights: number;
  pricing_source: string;
  booking_url: string;
};

export type TaylorQuoteRequestRecord = {
  id: string;
  status: "pending_approval" | "sent" | "expired";
  guest_email: string;
  check_in: string;
  check_out: string;
  nights: number;
  adults: number;
  children: number;
  pets: number;
  available_property_count: number;
  property_options: TaylorPropertyOption[];
  approved_by: string | null;
  sent_at: string | null;
  created_at: string;
};

export function useTaylorPendingQuotes() {
  return useQuery<{ requests: TaylorQuoteRequestRecord[]; total: number }>({
    queryKey: ["taylor-quote-requests"],
    queryFn: () => api.get("/api/quotes/taylor/pending"),
    refetchInterval: 30_000,
  });
}

export function useCreateTaylorQuoteRequest() {
  const qc = useQueryClient();
  return useMutation<
    TaylorQuoteRequestRecord,
    Error,
    {
      guest_email: string;
      check_in: string;
      check_out: string;
      adults: number;
      children: number;
      pets: number;
    }
  >({
    mutationFn: (payload) => api.post("/api/quotes/taylor/request", payload),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["taylor-quote-requests"] });
      const count = data.available_property_count ?? data.property_options?.length ?? 0;
      if (count > 0) {
        toast.success(`Quote created — ${count} available cabin${count !== 1 ? "s" : ""} found`);
      } else {
        toast.warning("No available cabins found for those dates");
      }
    },
    onError: (err) => toast.error(err.message || "Failed to create quote request"),
  });
}

export function useApproveTaylorQuote() {
  const qc = useQueryClient();
  return useMutation<
    { status: string; guest_email: string; property_count: number },
    Error,
    { requestId: string }
  >({
    mutationFn: ({ requestId }) =>
      api.post(`/api/quotes/taylor/${requestId}/approve`, {}),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["taylor-quote-requests"] });
      toast.success(`Quote sent to ${data.guest_email} (${data.property_count} cabin${data.property_count !== 1 ? "s" : ""})`);
    },
    onError: (err) => toast.error(err.message || "Failed to send quote"),
  });
}

export function useVrsMessageStats() {
  return useQuery({
    queryKey: ["vrs", "message-stats"],
    queryFn: () => api.get<VrsMessageStats>("/api/messages/stats"),
  });
}

export function useVrsHunterTargets(enabled = true) {
  return useQuery<VrsHunterTarget[]>({
    queryKey: ["vrs", "hunter-targets"],
    queryFn: () => api.get<VrsHunterTarget[]>("/api/vrs/hunter/targets"),
    enabled,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}

export function useDispatchHunterTarget() {
  const qc = useQueryClient();
  return useMutation<
    VrsHunterDispatchResponse,
    Error,
    { guestId: string; fullName: string; targetScore: number }
  >({
    mutationFn: ({ guestId, fullName, targetScore }) =>
      api.hunter.dispatch<VrsHunterDispatchResponse>({
        guest_id: guestId,
        full_name: fullName,
        target_score: targetScore,
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["vrs", "hunter-queue"] });
      qc.invalidateQueries({ queryKey: ["vrs", "hunter-queue-stats"] });
      toast.success(data.message || "Hunter dispatch queued");
    },
    onError: (err) => toast.error(err.message || "Failed to dispatch AI agent"),
  });
}

export function useSyncVrsLedger(limit = 25) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<VrsConflictQueueResponse>(`/api/vrs/sync?limit=${limit}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vrs", "conflict-queue"] });
      toast.success("Ledger synced");
    },
    onError: (err: Error) => toast.error(err.message || "Ledger sync failed"),
  });
}

export function useVrsConflictQueue(limit = 25) {
  return useQuery<VrsConflictQueueResponse>({
    queryKey: ["vrs", "conflict-queue", limit],
    queryFn: () => api.get("/api/vrs/queue", { limit, held_only: true }),
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
}

export function useVrsAdjudicationDetail(id: string | undefined) {
  return useQuery<VrsAdjudicationDetail>({
    queryKey: ["vrs", "adjudication", id],
    queryFn: () => api.get(`/api/vrs/adjudications/${id}`),
    enabled: !!id,
    staleTime: 5_000,
  });
}

export function useOverrideVrsDispatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
      consensusConviction,
      minimumConviction = 0,
    }: {
      id: string;
      body?: string;
      consensusConviction?: number;
      minimumConviction?: number;
    }) =>
      api.post(`/api/vrs/adjudications/${id}/override-dispatch`, {
        body,
        consensus_conviction: consensusConviction,
        minimum_conviction: minimumConviction,
      }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["vrs", "conflict-queue"] });
      qc.invalidateQueries({ queryKey: ["vrs", "adjudication", variables.id] });
      toast.success("Override dispatched");
    },
    onError: (err: Error) => toast.error(err.message || "Override dispatch failed"),
  });
}

export function useVrsReservationFull(id: string | undefined) {
  return useQuery<VrsReservationDetailResponse | Reservation>({
    queryKey: ["vrs", "reservation", id],
    queryFn: () => api.get(`/api/reservations/${id}`),
    enabled: !!id,
    staleTime: 0,
  });
}

// ---------------------------------------------------------------------------
// Owner Calendar & Yield Loss Engine
// ---------------------------------------------------------------------------

interface YieldLossEstimate {
  property_id: string;
  property_name: string;
  requested_nights: number;
  projected_adr: number;
  gross_revenue_loss: number;
  cleaning_fee: number;
  tax_estimate: number;
  total_estimated_loss: number;
  demand_alert: boolean;
  peak_nights: number;
  warning_message: string;
  nightly_breakdown: Array<{
    date: string;
    rate: number;
    source: string;
    is_peak: boolean;
  }>;
}

interface CalendarDay {
  status: "available" | "booked" | "blocked";
  nightly_rate: number;
  is_peak: boolean;
  reservation_id?: string;
  confirmation_code?: string;
  block_id?: string;
  block_type?: string;
  source?: string;
}

interface OwnerCalendarData {
  property_id: string;
  property_name: string;
  start_date: string;
  end_date: string;
  days: Record<string, CalendarDay>;
  reservations: Array<{
    id: string;
    confirmation_code: string;
    check_in_date: string;
    check_out_date: string;
    status: string;
    total_amount: number;
  }>;
  blocks: Array<{
    id: string;
    start_date: string;
    end_date: string;
    block_type: string;
    source: string;
  }>;
}

interface OwnerBlock {
  id: string;
  start_date: string;
  end_date: string;
  block_type: string;
  source: string;
  created_at: string | null;
}

export function useOwnerCalendar(propertyId: string) {
  return useQuery<OwnerCalendarData>({
    queryKey: ["owner-calendar", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/calendar`),
    enabled: !!propertyId,
    refetchInterval: 60_000,
  });
}

export function useOwnerBlocks(propertyId: string) {
  return useQuery<{ blocks: OwnerBlock[] }>({
    queryKey: ["owner-blocks", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/blocks`),
    enabled: !!propertyId,
  });
}

export function useCalculateYieldLoss(propertyId: string) {
  return useMutation<YieldLossEstimate, Error, { start_date: string; end_date: string }>({
    mutationFn: (dates) =>
      api.post(`/api/owner/${propertyId}/blocks/calculate-yield-loss`, dates),
  });
}

export function useCreateOwnerBlock(propertyId: string) {
  const qc = useQueryClient();
  return useMutation<
    { status: string; property_id: string; start_date: string; end_date: string; nights: number },
    Error,
    { start_date: string; end_date: string; reason?: string }
  >({
    mutationFn: (payload) => api.post(`/api/owner/${propertyId}/blocks`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["owner-calendar", propertyId] });
      qc.invalidateQueries({ queryKey: ["owner-blocks", propertyId] });
      toast.success("Owner hold created");
    },
    onError: (err) => toast.error(err.message || "Failed to create owner hold"),
  });
}

export function useDeleteOwnerBlock(propertyId: string) {
  const qc = useQueryClient();
  return useMutation<{ status: string; block_id: string }, Error, string>({
    mutationFn: (blockId) => api.delete(`/api/owner/${propertyId}/blocks/${blockId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["owner-calendar", propertyId] });
      qc.invalidateQueries({ queryKey: ["owner-blocks", propertyId] });
      toast.success("Owner hold removed");
    },
    onError: (err) => toast.error(err.message || "Failed to remove owner hold"),
  });
}


// ============================================================================
// CAPEX APPROVAL GATE
// ============================================================================

interface CapexStagingItem {
  id: number;
  property_id: string;
  vendor: string;
  amount: number;
  total_owner_charge: number;
  description: string;
  journal_lines: Array<{ code: string; type: string; amount: number }>;
  audit_trail: string[];
  created_at: string | null;
}

export function useCapexPending(propertyId: string) {
  return useQuery<{ pending: CapexStagingItem[] }>({
    queryKey: ["capex-pending", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/capex/pending`),
    enabled: !!propertyId,
    refetchInterval: 30_000,
  });
}

export function useApproveCapex(propertyId: string) {
  const qc = useQueryClient();
  return useMutation<
    { status: string; staging_id: number; journal_entry_id: number; vendor: string; amount: number },
    Error,
    number
  >({
    mutationFn: (stagingId) =>
      api.post(`/api/owner/${propertyId}/capex/${stagingId}/approve`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["capex-pending", propertyId] });
      qc.invalidateQueries({ queryKey: ["iron-dome-activity", propertyId] });
      toast.success("CapEx approved and committed to ledger");
    },
    onError: (err) => toast.error(err.message || "Failed to approve CapEx"),
  });
}

export function useRejectCapex(propertyId: string) {
  const qc = useQueryClient();
  return useMutation<
    { status: string; staging_id: number; vendor: string; amount: number; reason: string },
    Error,
    { stagingId: number; reason?: string }
  >({
    mutationFn: ({ stagingId, reason }) =>
      api.post(
        `/api/owner/${propertyId}/capex/${stagingId}/reject?reason=${encodeURIComponent(reason || "Owner declined")}`,
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["capex-pending", propertyId] });
      toast.success("CapEx rejected");
    },
    onError: (err) => toast.error(err.message || "Failed to reject CapEx"),
  });
}

// ---------------------------------------------------------------------------
// ROI Simulator (Wealth Multiplier)
// ---------------------------------------------------------------------------

export function useRoiSimulator(propertyId: string) {
  return useQuery({
    queryKey: ["roi-simulator", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/roi-simulator`),
    enabled: !!propertyId,
  });
}

// ---------------------------------------------------------------------------
// IoT Digital Twin (Asset Health)
// ---------------------------------------------------------------------------

export function usePropertyIoT(propertyId: string) {
  return useQuery({
    queryKey: ["property-iot", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/iot/status`),
    enabled: !!propertyId,
    refetchInterval: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Continuous Liquidity (Payouts)
// ---------------------------------------------------------------------------

export function usePayoutAccount(propertyId: string) {
  return useQuery({
    queryKey: ["payout-account", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/payouts/account-status`),
    enabled: !!propertyId,
  });
}

export function usePayoutHistory(propertyId: string) {
  return useQuery({
    queryKey: ["payout-history", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/payouts`),
    enabled: !!propertyId,
    refetchInterval: 30_000,
  });
}

export function useSetupPayouts(propertyId: string) {
  const qc = useQueryClient();
  return useMutation<
    { status: string; onboarding_url?: string; message: string },
    Error,
    { owner_email: string }
  >({
    mutationFn: (data) =>
      api.post(`/api/owner/${propertyId}/payouts/setup`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payout-account", propertyId] });
      toast.success("Payout account setup initiated");
    },
    onError: (err) => toast.error(err.message || "Failed to setup payouts"),
  });
}

// ---------------------------------------------------------------------------
// Fortress Prime — God Mode Dashboard
// ---------------------------------------------------------------------------

export function usePrimeSnapshot() {
  return useQuery({
    queryKey: ["prime-snapshot"],
    queryFn: () => api.get("/api/admin/prime/snapshot"),
    refetchInterval: 30_000,
  });
}

export function useAuthorizeUpgrade(propertyId: string) {
  const qc = useQueryClient();
  return useMutation<
    { status: string; capex_id: number; project_name: string; message: string },
    Error,
    { project_name: string; estimated_cost: number; projected_adr_lift: number }
  >({
    mutationFn: (data) =>
      api.post(`/api/owner/${propertyId}/capex/authorize-upgrade`, data),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["capex-pending", propertyId] });
      qc.invalidateQueries({ queryKey: ["roi-simulator", propertyId] });
      qc.invalidateQueries({ queryKey: ["iron-dome-activity", propertyId] });
      toast.success(res.message || "Upgrade authorized — CROG Development dispatched");
    },
    onError: (err) => toast.error(err.message || "Failed to authorize upgrade"),
  });
}

// ---------------------------------------------------------------------------
// Admin Operations Glass — Fleet Management
// ---------------------------------------------------------------------------

export interface AsyncJobArchivePreviewItem {
  id: string;
  job_name: string;
  status: string;
  finished_at: string | null;
  error_text: string | null;
}

export interface AsyncJobArchivePrunePayload {
  older_than_minutes?: number;
  limit?: number;
  statuses?: string[] | null;
  apply?: boolean;
  output_path?: string | null;
}

export interface AsyncJobArchivePruneResult {
  matched_rows: number;
  statuses: string[];
  older_than_minutes: number;
  cutoff_utc: string;
  apply: boolean;
  preview: AsyncJobArchivePreviewItem[];
  preview_truncated: number;
  archived_rows: number;
  archive_path: string | null;
}

/** Manager/super-admin: dry-run or apply archive+prune for async_job_runs ledger. */
export function useAsyncJobArchivePrune() {
  return useMutation<
    AsyncJobArchivePruneResult,
    Error,
    AsyncJobArchivePrunePayload
  >({
    mutationFn: (payload) =>
      api.post<AsyncJobArchivePruneResult>(
        "/api/system/ops/async-jobs/archive-prune",
        {
          older_than_minutes: payload.older_than_minutes ?? 60,
          limit: payload.limit ?? 500,
          statuses: payload.statuses ?? null,
          apply: payload.apply ?? false,
          output_path: payload.output_path ?? null,
        },
      ),
    onSuccess: (data) => {
      if (data.apply) {
        if (data.archived_rows > 0) {
          toast.success(
            `Archived ${data.archived_rows} ledger row(s)${data.archive_path ? ` → ${data.archive_path}` : ""}`,
          );
        } else {
          toast.success("Apply completed — no rows matched");
        }
      } else {
        toast.success(`Dry run: ${data.matched_rows} row(s) matched`);
      }
    },
    onError: (err) =>
      toast.error(err.message || "Async job archive prune failed"),
  });
}

export interface AdminInsightItem {
  id: string;
  title: string;
  summary: string;
  metrics: Record<string, unknown>;
}

export interface AdminInsightsResponse {
  items: AdminInsightItem[];
  count: number;
  requested_limit: number;
  source_table_present: boolean;
  live_data_supported: boolean;
  status: string;
  message: string;
}

export function useAdminInsights(limit = 4) {
  return useQuery<AdminInsightsResponse>({
    queryKey: ["admin", "insights", limit],
    queryFn: () => api.get("/api/admin/insights", { limit }),
    staleTime: 60_000,
  });
}

export interface ChannexSyncResult {
  property_id: string;
  slug: string;
  property_name: string;
  action: string;
  channex_listing_id: string | null;
  match_strategy: string | null;
  error: string | null;
}

export interface ChannexSyncInventoryRequest {
  dry_run: boolean;
  limit?: number;
  property_ids?: string[];
}

export interface ChannexSyncInventoryResponse {
  status: string;
  dry_run: boolean;
  scanned_count: number;
  created_count: number;
  mapped_count: number;
  failed_count: number;
  results: ChannexSyncResult[];
}

export interface ChannexHealthPropertyStatus {
  property_id: string;
  streamline_property_id: string;
  slug: string;
  property_name: string;
  channex_listing_id: string | null;
  shell_present: boolean;
  preferred_room_type_present: boolean;
  preferred_rate_plan_present: boolean;
  room_type_count: number;
  rate_plan_count: number;
  duplicate_rate_plan_count: number;
  ari_availability_present: boolean;
  ari_restrictions_present: boolean;
  healthy: boolean;
}

export interface ChannexHealthResponse {
  property_count: number;
  healthy_count: number;
  shell_ready_count: number;
  catalog_ready_count: number;
  ari_ready_count: number;
  duplicate_rate_plan_count: number;
  properties: ChannexHealthPropertyStatus[];
}

export interface ChannexHistoryItem {
  id: string;
  action: string;
  outcome: string;
  actor_email: string | null;
  created_at: string;
  request_id: string | null;
  property_count: number | null;
  remediated_count: number | null;
  failed_count: number | null;
  ari_window_days: number | null;
  results: Array<{
    property_id?: string;
    slug?: string;
    property_name?: string;
    shell_action?: string;
    catalog_action?: string;
    ari_action?: string;
    error?: string | null;
  }>;
}

export interface ChannexHistoryResponse {
  count: number;
  recent_success_count: number;
  recent_partial_failure_count: number;
  recent_remediated_property_count: number;
  recent_failed_property_count: number;
  last_run_at: string | null;
  last_success_at: string | null;
  items: ChannexHistoryItem[];
}

export interface ChannexRemediationResult {
  property_id: string;
  slug: string;
  property_name: string;
  channex_listing_id: string | null;
  shell_action: string;
  catalog_action: string;
  ari_action: string;
  room_type_id: string | null;
  rate_plan_id: string | null;
  error: string | null;
}

export interface ChannexRemediationRequest {
  property_ids?: string[];
  ari_window_days: number;
}

export interface ChannexRemediationResponse {
  status: string;
  property_count: number;
  remediated_count: number;
  failed_count: number;
  results: ChannexRemediationResult[];
}

export function useChannexSyncInventory() {
  const qc = useQueryClient();
  return useMutation<
    ChannexSyncInventoryResponse,
    Error,
    ChannexSyncInventoryRequest
  >({
    mutationFn: (payload) => api.post("/api/admin/channex/sync-inventory", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "channex", "health"] });
      qc.invalidateQueries({ queryKey: ["admin", "channex", "history"] });
      toast.success("Channex inventory sync completed");
    },
    onError: (err) => toast.error(err.message || "Failed to sync Channex inventory"),
  });
}

export function useChannexHealth() {
  return useQuery<ChannexHealthResponse>({
    queryKey: ["admin", "channex", "health"],
    queryFn: () => api.get("/api/admin/channex/health"),
    refetchInterval: 60_000,
  });
}

export function useChannexHistory(limit = 20) {
  return useQuery<ChannexHistoryResponse>({
    queryKey: ["admin", "channex", "history", limit],
    queryFn: () => api.get("/api/admin/channex/history", { limit }),
    refetchInterval: 60_000,
  });
}

export function useChannexRemediation() {
  const qc = useQueryClient();
  return useMutation<
    ChannexRemediationResponse,
    Error,
    ChannexRemediationRequest
  >({
    mutationFn: (payload) => api.post("/api/admin/channex/remediate", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "channex", "health"] });
      qc.invalidateQueries({ queryKey: ["admin", "channex", "history"] });
      toast.success("Channex remediation completed");
    },
    onError: (err) => toast.error(err.message || "Failed to remediate Channex fleet"),
  });
}

export interface FleetProperty {
  property_id: string;
  name: string;
  owner_name: string;
  owner_email: string | null;
  owner_pct: number | null;
  pm_pct: number | null;
  split_effective_date: string | null;
  markup_pct: number;
  trust_owner_funds: number;
  trust_operating_funds: number;
  trust_escrow: number;
  trust_security_deps: number;
  health: "healthy" | "warning" | "overdraft";
  pending_capex_count: number;
  pending_capex_total: number;
  mtd_pm_revenue: number;
  mtd_reservations: number;
}

export interface FleetStatusResponse {
  fleet: FleetProperty[];
  global_totals: {
    total_owner_funds: number;
    total_operating_funds: number;
    total_pm_revenue_mtd: number;
    properties_in_overdraft: number;
    pending_capex_items: number;
  };
}

export function useFleetStatus() {
  return useQuery<FleetStatusResponse>({
    queryKey: ["admin", "fleet-status"],
    queryFn: () => api.get("/api/admin/fleet-status"),
    refetchInterval: 30_000,
  });
}

export function useUpdateSplit() {
  const qc = useQueryClient();
  return useMutation<
    { status: string; property_id: string; owner_pct: number; pm_pct: number },
    Error,
    { propertyId: string; ownerPct: number; pmPct: number }
  >({
    mutationFn: ({ propertyId, ownerPct, pmPct }) =>
      api.post(`/api/admin/splits/${propertyId}`, {
        owner_pct: ownerPct,
        pm_pct: pmPct,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "fleet-status"] });
      toast.success("Commission split updated");
    },
    onError: (err) => toast.error(err.message || "Failed to update split"),
  });
}

export function useUpdateMarkup() {
  const qc = useQueryClient();
  return useMutation<
    { status: string; property_id: string; markup_pct: number },
    Error,
    { propertyId: string; markupPct: number; expenseCategory?: string }
  >({
    mutationFn: ({ propertyId, markupPct, expenseCategory }) =>
      api.post(`/api/admin/markups/${propertyId}`, {
        markup_pct: markupPct,
        expense_category: expenseCategory ?? "ALL",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "fleet-status"] });
      toast.success("CapEx markup updated");
    },
    onError: (err) => toast.error(err.message || "Failed to update markup"),
  });
}

// ── CapEx Exception Management ──────────────────────────────────────────

export interface PendingCapexItem {
  id: number;
  property_id: string;
  vendor: string;
  amount: number;
  total_owner_charge: number;
  description: string | null;
  audit_trail: Record<string, unknown> | null;
  created_at: string | null;
}

export interface PendingCapexResponse {
  items: PendingCapexItem[];
  count: number;
}

export interface CapitalCallResult {
  status: string;
  staging_id: number;
  payment_link_url: string;
  email_sent_to: string;
  email_delivered: boolean;
  total_owner_charge: number;
}

export function useAdminPendingCapex(propertyId: string | null) {
  return useQuery<PendingCapexResponse>({
    queryKey: ["admin", "capex", propertyId],
    queryFn: () => api.get(`/api/admin/capex/${propertyId}/pending`),
    enabled: !!propertyId,
    refetchInterval: 15_000,
  });
}

export function useAdminApproveCapex() {
  const qc = useQueryClient();
  return useMutation<
    { status: string; staging_id: number; journal_entry_id: number },
    Error,
    { stagingId: number }
  >({
    mutationFn: ({ stagingId }) =>
      api.post(`/api/admin/capex/${stagingId}/approve`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      toast.success("CapEx approved — journal lines committed to Iron Dome");
    },
    onError: (err) => toast.error(err.message || "Failed to approve CapEx"),
  });
}

export function useAdminRejectCapex() {
  const qc = useQueryClient();
  return useMutation<
    { status: string; staging_id: number; reason: string },
    Error,
    { stagingId: number; reason: string }
  >({
    mutationFn: ({ stagingId, reason }) =>
      api.post(`/api/admin/capex/${stagingId}/reject`, { reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      toast.success("CapEx rejected");
    },
    onError: (err) => toast.error(err.message || "Failed to reject CapEx"),
  });
}

export function useDispatchCapitalCall() {
  const qc = useQueryClient();
  return useMutation<CapitalCallResult, Error, { stagingId: number }>({
    mutationFn: ({ stagingId }) =>
      api.post(`/api/admin/capex/${stagingId}/dispatch-capital-call`, {}),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      toast.success(`Capital call dispatched to ${data.email_sent_to}`);
    },
    onError: (err) =>
      toast.error(err.message || "Failed to dispatch capital call"),
  });
}

// ---------------------------------------------------------------------------
// Owner Onboarding
// ---------------------------------------------------------------------------

export interface OnboardOwnerPayload {
  owner_name: string;
  email: string;
  phone?: string;
  sl_owner_id: string;
  property_ids: string[];
  owner_pct: number;
  pm_pct: number;
  markup_pct: number;
  contract_nas_path?: string;
}

export interface OnboardOwnerResponse {
  status: string;
  owner_id: string;
  owner_name: string;
  properties_seeded: string[];
  splits: { owner_pct: number; pm_pct: number };
  markup_pct: number;
  trust_accounts_created: number;
  sub_ledger_accounts: string[];
  contract_ingested: boolean;
  magic_link_url: string;
}

export function useOnboardOwner() {
  const qc = useQueryClient();
  return useMutation<OnboardOwnerResponse, Error, OnboardOwnerPayload>({
    mutationFn: (payload) => api.post("/api/admin/onboard-owner", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "fleet-status"] });
      toast.success("Owner onboarded successfully");
    },
    onError: (err) =>
      toast.error(err.message || "Failed to onboard owner"),
  });
}

// ---------------------------------------------------------------------------
// Owner Marketing Syndicate — Direct Booking Growth Engine
// ---------------------------------------------------------------------------

export interface MarketingPreferences {
  property_id: string;
  marketing_pct: number;
  enabled: boolean;
  updated_at: string | null;
  updated_by: string | null;
  escrow_balance: number;
}

export function useMarketingPreferences(propertyId: string | undefined) {
  return useQuery<MarketingPreferences>({
    queryKey: ["owner", "marketing-preferences", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/marketing/preferences`),
    enabled: !!propertyId,
  });
}

export function useUpdateMarketingPreferences(propertyId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<
    { status: string; property_id: string; marketing_pct: number; enabled: boolean },
    Error,
    { marketing_pct: number; enabled: boolean }
  >({
    mutationFn: (payload) =>
      api.post(`/api/owner/${propertyId}/marketing/preferences`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["owner", "marketing-preferences", propertyId] });
      toast.success("Marketing allocation updated");
    },
    onError: (err) =>
      toast.error(err.message || "Failed to update marketing preferences"),
  });
}

export interface AttributionPeriod {
  id: number;
  period_start: string;
  period_end: string;
  ad_spend: number;
  impressions: number;
  clicks: number;
  direct_bookings: number;
  gross_revenue: number;
  roas: number;
  campaign_notes: string | null;
  entered_by: string;
  created_at: string;
}

export interface AttributionData {
  property_id: string;
  periods: AttributionPeriod[];
  totals: {
    ad_spend: number;
    impressions: number;
    clicks: number;
    direct_bookings: number;
    gross_revenue: number;
    roas: number;
  };
}

export function useMarketingAttribution(propertyId: string | undefined) {
  return useQuery<AttributionData>({
    queryKey: ["owner", "marketing-attribution", propertyId],
    queryFn: () => api.get(`/api/owner/${propertyId}/marketing/attribution`),
    enabled: !!propertyId,
  });
}

export interface AdminMarketingBudgets {
  fleet_totals: {
    total_escrow: number;
    total_ad_spend: number;
    properties_enrolled: number;
    properties_total: number;
  };
  properties: Array<{
    property_id: string;
    property_name: string | null;
    marketing_pct: number;
    enabled: boolean;
    escrow_balance: number;
    latest_attribution: {
      period_start: string | null;
      period_end: string | null;
      ad_spend: number;
      impressions: number;
      clicks: number;
      direct_bookings: number;
      gross_revenue: number;
      roas: number;
    } | null;
  }>;
}

export function useAdminMarketingBudgets() {
  return useQuery<AdminMarketingBudgets>({
    queryKey: ["admin", "marketing-budgets"],
    queryFn: () => api.get("/api/admin/marketing-budgets"),
  });
}

// ---------------------------------------------------------------------------
// Management Contracts
// ---------------------------------------------------------------------------
export interface ManagementContract {
  id: string;
  property_id: string | null;
  agreement_type: string;
  status: string;
  created_at: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signer_name: string | null;
  pdf_url: string | null;
}

export interface ManagementContractsResponse {
  contracts: ManagementContract[];
  total: number;
}

export interface GenerateContractPayload {
  owner_id: string;
  property_id: string;
  term_years?: number;
  effective_date?: string;
}

export interface GenerateContractResponse {
  agreement_id: string;
  pdf_path: string;
  nas_path: string | null;
  variables_used: Record<string, string>;
  status: string;
}

export interface SendContractPayload {
  recipient_email?: string;
  expires_days?: number;
}

export interface SendContractResponse {
  status: string;
  agreement_id: string;
  recipient: string;
  signing_url: string;
  expires_at: string;
}

export function useManagementContracts(status?: string) {
  return useQuery<ManagementContractsResponse>({
    queryKey: ["admin", "contracts", status],
    queryFn: () =>
      api.get("/api/admin/contracts/", status ? { status } : undefined),
    refetchInterval: 15_000,
  });
}

export function useGenerateContract() {
  const qc = useQueryClient();
  return useMutation<GenerateContractResponse, Error, GenerateContractPayload>({
    mutationFn: (payload) => api.post("/api/admin/contracts/generate", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "contracts"] });
      toast.success("Management agreement generated");
    },
    onError: (err) =>
      toast.error(err.message || "Failed to generate contract"),
  });
}

export function useSendContract() {
  const qc = useQueryClient();
  return useMutation<
    SendContractResponse,
    Error,
    { agreementId: string } & SendContractPayload
  >({
    mutationFn: ({ agreementId, ...payload }) =>
      api.post(`/api/admin/contracts/${agreementId}/send`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "contracts"] });
      toast.success("Signing link dispatched to owner");
    },
    onError: (err) => toast.error(err.message || "Failed to send contract"),
  });
}

export interface GenerateProspectusPayload {
  owner_id: string;
  property_id: string;
  term_years?: number;
  effective_date?: string;
}

export interface GenerateProspectusResponse {
  prospectus_id: string;
  pdf_path: string;
  nas_path: string | null;
  status: string;
  pro_forma_summary: {
    annual_gross: number;
    annual_net_to_owner: number;
    adr_used: number;
    occupancy_used: number;
  };
}

export function useGenerateProspectus() {
  const qc = useQueryClient();
  return useMutation<GenerateProspectusResponse, Error, GenerateProspectusPayload>({
    mutationFn: (payload) =>
      api.post("/api/admin/contracts/prospectus", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "contracts"] });
      toast.success("Prospectus generated with Pro Forma projections");
    },
    onError: (err) =>
      toast.error(err.message || "Failed to generate prospectus"),
  });
}

// ─── Dispute Exception Desk ──────────────────────────────────────────────────

export interface DisputeStats {
  total_active: number;
  total_disputed_amount: number;
  win_count: number;
  loss_count: number;
  win_rate_pct: number;
  funds_recovered_ytd: number;
  by_reason_code: Record<string, { count: number; amount: number }>;
  by_status: Record<string, number>;
}

export interface DisputeListItem {
  id: string;
  dispute_id: string;
  dispute_amount: number;
  dispute_reason: string;
  dispute_status: string;
  evidence_status: string;
  iot_events_count: number;
  has_evidence_pdf: boolean;
  submitted_to_stripe_at: string | null;
  created_at: string | null;
  response_deadline: string | null;
  days_remaining: number | null;
  confirmation_code: string | null;
  check_in_date: string | null;
  check_out_date: string | null;
  guest_name: string;
  guest_email: string | null;
  property_name: string;
}

export interface DisputeListResponse {
  data: DisputeListItem[];
  pagination: {
    page: number;
    per_page: number;
    total: number;
    total_pages: number;
  };
}

export interface UploadEvidenceResponse {
  status: string;
  dispute_id: string;
  filename: string;
  size_bytes: number;
  recompile_triggered: boolean;
}

export function useDisputeStats() {
  return useQuery<DisputeStats>({
    queryKey: ["admin", "disputes", "stats"],
    queryFn: () => api.get("/api/admin/disputes/stats"),
    refetchInterval: 30_000,
  });
}

export function useDisputes(status?: string) {
  return useQuery<DisputeListResponse>({
    queryKey: ["admin", "disputes", "list", status],
    queryFn: () =>
      api.get("/api/admin/disputes/", status ? { status } : undefined),
    refetchInterval: 30_000,
  });
}

export function useUploadDisputeEvidence() {
  const qc = useQueryClient();
  return useMutation<
    UploadEvidenceResponse,
    Error,
    { disputeId: string; file: File }
  >({
    mutationFn: async ({ disputeId, file }) => {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch(
        `/api/admin/disputes/${disputeId}/upload-evidence`,
        { method: "POST", body: formData, credentials: "include" }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Upload failed (${resp.status})`);
      }
      return resp.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "disputes"] });
      toast.success("Evidence uploaded — re-compiling defense packet");
    },
    onError: (err) =>
      toast.error(err.message || "Failed to upload evidence"),
  });
}


// ---------------------------------------------------------------------------
// System Telemetry (Godhead + DEFCON + Vault partitions)
// ---------------------------------------------------------------------------
export interface SystemTelemetry {
  defcon_mode: string;
  vault_gamma: {
    total_vectors: number;
    partitions: Record<string, number>;
  };
  vault_omega: {
    training_rows: number;
  };
  ingestion: {
    processed: number;
    errors: number;
    queue_depth: number;
  };
  streamline_bridge?: {
    latest_event?: {
      timestamp?: string;
      event_type?: string;
      source?: string;
      failure_class?: string;
      severity?: string;
      details?: Record<string, unknown>;
    } | null;
    failures_last_24h?: number;
    retries_last_24h?: number;
  };
  legacy_modules?: Record<
    string,
    {
      path?: string;
      status?: "up" | "down";
      http_status?: number | null;
      latency_ms?: number | null;
    }
  >;
  threat_reports: number;
  timestamp: string;
}

export function useSystemTelemetry() {
  return useQuery<SystemTelemetry>({
    queryKey: ["system-telemetry"],
    queryFn: async () => {
      const res = await fetch("/api/system/telemetry", { credentials: "include" });
      if (!res.ok) throw new Error(`Telemetry fetch failed (${res.status})`);
      return res.json();
    },
    refetchInterval: 5_000,
  });
}

export interface ModuleMaturityProbe {
  path: string;
  status: "up" | "down";
  http_status: number | null;
  latency_ms: number | null;
  reason:
    | "auth_required"
    | "rate_limited"
    | "not_found"
    | "upstream_5xx"
    | "client_error"
    | "timeout"
    | "network_failure"
    | null;
}

export interface ModuleMaturityEntry {
  id: string;
  label: string;
  legacy_path: string;
  native_path: string | null;
  data_probe_path: string | null;
  legacy: ModuleMaturityProbe;
  native: ModuleMaturityProbe | null;
  data_probe: ModuleMaturityProbe | null;
  maturity: "legacy_only" | "route_only" | "data_live";
  maturity_reason:
    | "auth_required"
    | "rate_limited"
    | "not_found"
    | "upstream_5xx"
    | "client_error"
    | "timeout"
    | "network_failure"
    | null;
}

export interface ModuleMaturityResponse {
  summary: {
    total_modules: number;
    legacy_routes_up: number;
    native_routes_ready: number;
    native_data_live: number;
  };
  modules: ModuleMaturityEntry[];
  timestamp: string;
}

export function useModuleMaturity() {
  return useQuery<ModuleMaturityResponse>({
    queryKey: ["module-maturity"],
    queryFn: async () => {
      const res = await fetch("/api/system/module-maturity", { credentials: "include" });
      if (!res.ok) throw new Error(`Module maturity fetch failed (${res.status})`);
      return res.json();
    },
    refetchInterval: 10_000,
  });
}


// ---------------------------------------------------------------------------
// DEFCON Mode Switch (mutation)
// ---------------------------------------------------------------------------
export function useSetDefcon() {
  const qc = useQueryClient();
  return useMutation<
    { status: string; mode: string; output: string },
    Error,
    { mode: string; override_authorization: boolean }
  >({
    mutationFn: async ({ mode, override_authorization }) => {
      const res = await fetch("/api/system/defcon", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ mode, override_authorization }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || `DEFCON switch failed (${res.status})`);
      }
      return res.json();
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["system-telemetry"] });
      if (data.status === "advisory") {
        toast.message("DEFCON request logged (advisory only)", {
          description: data.output.slice(0, 220),
        });
      } else {
        toast.success("DEFCON mode switched");
      }
    },
    onError: (err) => toast.error(err.message || "DEFCON switch failed"),
  });
}


// ---------------------------------------------------------------------------
// Financial Approvals — NeMo Triage
// ---------------------------------------------------------------------------

export interface ApprovalReservationContext {
  confirmation_code: string | null;
  guest_name: string | null;
  guest_email: string | null;
  check_in: string | null;
  check_out: string | null;
  total_amount_cents: number | null;
  booking_source: string | null;
}

export interface PendingApproval {
  id: string;
  reservation_id: string;
  status: string;
  discrepancy_type: string;
  local_total_cents: number;
  streamline_total_cents: number;
  delta_cents: number;
  context_payload: Record<string, unknown>;
  resolution_strategy: string | null;
  stripe_invoice_id: string | null;
  created_at: string;
  resolved_at: string | null;
  reservation: ApprovalReservationContext | null;
}

export interface ExecuteApprovalResponse {
  id: string;
  status: string;
  resolution_strategy: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  delta_cents: number;
  stripe_invoice_id: string | null;
}

export function usePendingApprovals() {
  return useQuery<PendingApproval[]>({
    queryKey: ["financial-approvals", "pending"],
    queryFn: () => api.get("/api/v1/financial-approvals/pending"),
    refetchInterval: 30_000,
  });
}

export function useExecuteApproval() {
  const qc = useQueryClient();
  return useMutation<
    ExecuteApprovalResponse,
    Error,
    { approvalId: string; strategy: "absorb" | "invoice" }
  >({
    mutationFn: ({ approvalId, strategy }) =>
      api.post(`/api/v1/financial-approvals/${approvalId}/execute`, { strategy }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["financial-approvals"] });
      toast.success(
        variables.strategy === "invoice"
          ? "Stripe invoice sent to guest"
          : "Variance absorbed into ledger",
      );
    },
    onError: (err) => toast.error(err.message || "Approval execution failed"),
  });
}

// ---------------------------------------------------------------------------
// Admin Payouts
// ---------------------------------------------------------------------------

export interface PayoutSummaryRow {
  property_id: string;
  owner_name: string;
  owner_email: string | null;
  account_status: string;
  stripe_account_id: string | null;
  payout_schedule: string;
  payout_day_of_week: number | null;
  payout_day_of_month: number | null;
  last_payout_at: string | null;
  next_scheduled_payout: string | null;
  minimum_payout_threshold: number;
  outstanding_amount: number | null;
  last_transfer_id: string | null;
  last_transfer_status: string | null;
}

export function useAdminPendingPayouts() {
  return useQuery<PayoutSummaryRow[]>({
    queryKey: ["admin-pending-payouts"],
    queryFn: () => api.get("/api/admin/payouts/pending"),
    refetchInterval: 60_000,
  });
}

export function useSendOwnerPayout() {
  const qc = useQueryClient();
  return useMutation<
    { triggered: boolean; payout_ledger_id: number; owner_amount: number },
    Error,
    { propertyId: string }
  >({
    mutationFn: ({ propertyId }) =>
      api.post(`/api/admin/payouts/${propertyId}/send`),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin-pending-payouts"] });
      toast.success(`Payout initiated — $${data.owner_amount?.toFixed(2)} queued (ledger #${data.payout_ledger_id})`);
    },
    onError: (err) => toast.error(`Payout failed: ${err.message}`),
  });
}

export function useUpdatePayoutSchedule() {
  const qc = useQueryClient();
  return useMutation<
    { updated: boolean },
    Error,
    {
      propertyId: string;
      payout_schedule: string;
      payout_day_of_week?: number | null;
      payout_day_of_month?: number | null;
      minimum_payout_threshold?: number | null;
    }
  >({
    mutationFn: ({ propertyId, ...body }) =>
      api.patch(`/api/admin/payouts/${propertyId}/schedule`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-pending-payouts"] });
      toast.success("Payout schedule updated");
    },
    onError: (err) => toast.error(`Schedule update failed: ${err.message}`),
  });
}

export function useTriggerPayoutSweep() {
  const qc = useQueryClient();
  return useMutation<{ processed: number; total_amount: number; errors: string[] }, Error>({
    mutationFn: () => api.post("/api/admin/payouts/sweep"),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin-pending-payouts"] });
      toast.success(`Sweep complete — ${data.processed} payout(s) processed, $${data.total_amount?.toFixed(2)} total`);
    },
    onError: (err) => toast.error(`Sweep failed: ${err.message}`),
  });
}

// ── Phase G.2: Owner Statement Workflow hooks ─────────────────────────────────
import type {
  OwnerBalancePeriod,
  OwnerBalancePeriodDetail,
  StatementListResponse,
  StatementListFilters,
  GenerateStatementsRequest,
  GenerateStatementsResult,
  OwnerCharge,
  ChargeListResponse,
  ChargeListFilters,
  CreateOwnerChargeRequest,
  UpdateOwnerChargeRequest,
} from "./types";

// Statement list — GET /api/admin/payouts/statements
export function useAdminStatements(filters: StatementListFilters = {}) {
  return useQuery<StatementListResponse>({
    queryKey: ["admin-statements", filters],
    queryFn: () =>
      api.get("/api/admin/payouts/statements", {
        ...(filters.status !== undefined && { status: filters.status }),
        ...(filters.period_start !== undefined && { period_start: filters.period_start }),
        ...(filters.period_end !== undefined && { period_end: filters.period_end }),
        ...(filters.owner_payout_account_id !== undefined && {
          owner_payout_account_id: filters.owner_payout_account_id,
        }),
        ...(filters.limit !== undefined && { limit: filters.limit }),
        ...(filters.offset !== undefined && { offset: filters.offset }),
      }),
    refetchInterval: false,
  });
}

// Statement detail — GET /api/admin/payouts/statements/{id}
export function useAdminStatement(periodId: number | null) {
  return useQuery<OwnerBalancePeriodDetail>({
    queryKey: ["admin-statement", periodId],
    queryFn: () => api.get(`/api/admin/payouts/statements/${periodId}`),
    enabled: !!periodId,
  });
}

// Generate statements — POST /api/admin/payouts/statements/generate
export function useGenerateStatements() {
  const qc = useQueryClient();
  return useMutation<GenerateStatementsResult, Error, GenerateStatementsRequest>({
    mutationFn: (body) => api.post("/api/admin/payouts/statements/generate", body),
    onSuccess: (data) => {
      if (!data.dry_run) {
        qc.invalidateQueries({ queryKey: ["admin-statements"] });
        toast.success(
          `Generated ${data.total_drafts_created} statement draft(s) for ${data.period_start} → ${data.period_end}`
        );
      }
    },
    onError: (err) => toast.error(`Generation failed: ${err.message}`),
  });
}

// Approve — POST /api/admin/payouts/statements/{id}/approve
export function useApproveStatement() {
  const qc = useQueryClient();
  return useMutation<OwnerBalancePeriod, Error, { periodId: number }>({
    mutationFn: ({ periodId }) => api.post(`/api/admin/payouts/statements/${periodId}/approve`),
    onSuccess: (_data, { periodId }) => {
      qc.invalidateQueries({ queryKey: ["admin-statements"] });
      qc.invalidateQueries({ queryKey: ["admin-statement", periodId] });
      toast.success("Statement approved");
    },
    onError: (err) => toast.error(`Approve failed: ${err.message}`),
  });
}

// Void — POST /api/admin/payouts/statements/{id}/void
export function useVoidStatement() {
  const qc = useQueryClient();
  return useMutation<OwnerBalancePeriod, Error, { periodId: number; reason: string }>({
    mutationFn: ({ periodId, reason }) =>
      api.post(`/api/admin/payouts/statements/${periodId}/void`, { reason }),
    onSuccess: (_data, { periodId }) => {
      qc.invalidateQueries({ queryKey: ["admin-statements"] });
      qc.invalidateQueries({ queryKey: ["admin-statement", periodId] });
      toast.success("Statement voided");
    },
    onError: (err) => toast.error(`Void failed: ${err.message}`),
  });
}

// Mark paid — POST /api/admin/payouts/statements/{id}/mark-paid
export function useMarkStatementPaid() {
  const qc = useQueryClient();
  return useMutation<
    OwnerBalancePeriod,
    Error,
    { periodId: number; payment_reference: string }
  >({
    mutationFn: ({ periodId, payment_reference }) =>
      api.post(`/api/admin/payouts/statements/${periodId}/mark-paid`, { payment_reference }),
    onSuccess: (_data, { periodId }) => {
      qc.invalidateQueries({ queryKey: ["admin-statements"] });
      qc.invalidateQueries({ queryKey: ["admin-statement", periodId] });
      toast.success("Statement marked as paid");
    },
    onError: (err) => toast.error(`Mark paid failed: ${err.message}`),
  });
}

// Pay owner — POST /api/admin/payouts/statements/{id}/pay (I.5)
export function usePayOwner() {
  const qc = useQueryClient();
  return useMutation<OwnerBalancePeriod & { stripe_transfer_id?: string; paid_amount?: string }, Error, { periodId: number }>({
    mutationFn: ({ periodId }) =>
      api.post(`/api/admin/payouts/statements/${periodId}/pay`),
    onSuccess: (_data, { periodId }) => {
      qc.invalidateQueries({ queryKey: ["admin-statements"] });
      qc.invalidateQueries({ queryKey: ["admin-statement", periodId] });
      // Toast handled by caller (needs amount context)
    },
    onError: (err) => toast.error(`Payment failed: ${err.message}`),
  });
}

// Mark emailed — POST /api/admin/payouts/statements/{id}/mark-emailed
export function useMarkStatementEmailed() {
  const qc = useQueryClient();
  return useMutation<OwnerBalancePeriod, Error, { periodId: number }>({
    mutationFn: ({ periodId }) =>
      api.post(`/api/admin/payouts/statements/${periodId}/mark-emailed`),
    onSuccess: (_data, { periodId }) => {
      qc.invalidateQueries({ queryKey: ["admin-statements"] });
      qc.invalidateQueries({ queryKey: ["admin-statement", periodId] });
      toast.success("Statement marked as emailed");
    },
    onError: (err) => toast.error(`Mark emailed failed: ${err.message}`),
  });
}

// Send test email — POST /api/admin/payouts/statements/{id}/send-test
export function useSendTestStatement() {
  return useMutation<
    { success: boolean; sent_to: string; message: string },
    Error,
    { periodId: number; override_email: string; note?: string }
  >({
    mutationFn: ({ periodId, override_email, note }) =>
      api.post(`/api/admin/payouts/statements/${periodId}/send-test`, {
        override_email,
        ...(note ? { note } : {}),
      }),
    onSuccess: (data) => toast.success(`Test email sent to ${data.sent_to}`),
    onError: (err) => toast.error(`Test send failed: ${err.message}`),
  });
}

// ── Owner Charges hooks ───────────────────────────────────────────────────────

// List charges — GET /api/admin/payouts/charges
export function useAdminCharges(filters: ChargeListFilters = {}) {
  return useQuery<ChargeListResponse>({
    queryKey: ["admin-charges", filters],
    queryFn: () =>
      api.get("/api/admin/payouts/charges", {
        ...(filters.owner_payout_account_id !== undefined && {
          owner_payout_account_id: filters.owner_payout_account_id,
        }),
        ...(filters.period_start !== undefined && { period_start: filters.period_start }),
        ...(filters.period_end !== undefined && { period_end: filters.period_end }),
        ...(filters.include_voided !== undefined && {
          include_voided: filters.include_voided,
        }),
        ...(filters.limit !== undefined && { limit: filters.limit }),
      }),
    enabled: filters.owner_payout_account_id !== undefined || Object.keys(filters).length === 0,
  });
}

// Single charge — GET /api/admin/payouts/charges/{id}
export function useAdminCharge(chargeId: number | null) {
  return useQuery<OwnerCharge>({
    queryKey: ["admin-charge", chargeId],
    queryFn: () => api.get(`/api/admin/payouts/charges/${chargeId}`),
    enabled: !!chargeId,
  });
}

// Create charge — POST /api/admin/payouts/charges
// I.1b: when send_notification=true the response includes notification_sent + notification_error.
// Callers that need the notification result should use the return value of mutateAsync().
export function useCreateOwnerCharge() {
  const qc = useQueryClient();
  return useMutation<OwnerCharge, Error, CreateOwnerChargeRequest>({
    mutationFn: (body) => api.post("/api/admin/payouts/charges", body),
    onSuccess: (_data) => {
      qc.invalidateQueries({ queryKey: ["admin-charges"] });
      qc.invalidateQueries({ queryKey: ["admin-statements"] });
      // When send_notification was used (I.1b), caller handles the toast via mutateAsync result.
      // For plain save (no notification), fire the default toast here.
      if (_data.notification_sent === undefined) {
        toast.success("Charge created");
      }
    },
    onError: (err) => toast.error(`Create charge failed: ${err.message}`),
  });
}

// Update charge — PATCH /api/admin/payouts/charges/{id}
export function useUpdateOwnerCharge() {
  const qc = useQueryClient();
  return useMutation<OwnerCharge, Error, { chargeId: number } & UpdateOwnerChargeRequest>({
    mutationFn: ({ chargeId, ...body }) =>
      api.patch(`/api/admin/payouts/charges/${chargeId}`, body),
    onSuccess: (_data, { chargeId }) => {
      qc.invalidateQueries({ queryKey: ["admin-charges"] });
      qc.invalidateQueries({ queryKey: ["admin-charge", chargeId] });
      toast.success("Charge updated");
    },
    onError: (err) => toast.error(`Update charge failed: ${err.message}`),
  });
}

// Void charge — POST /api/admin/payouts/charges/{id}/void
export function useVoidOwnerCharge() {
  const qc = useQueryClient();
  return useMutation<OwnerCharge, Error, { chargeId: number; void_reason: string }>({
    mutationFn: ({ chargeId, void_reason }) =>
      api.post(`/api/admin/payouts/charges/${chargeId}/void`, { void_reason }),
    onSuccess: (_data, { chargeId }) => {
      qc.invalidateQueries({ queryKey: ["admin-charges"] });
      qc.invalidateQueries({ queryKey: ["admin-charge", chargeId] });
      toast.success("Charge voided");
    },
    onError: (err) => toast.error(`Void charge failed: ${err.message}`),
  });
}

// ── Vendors hook ─────────────────────────────────────────────────────────────

export interface Vendor {
  id: string;
  name: string;
  trade: string | null;
  phone: string | null;
  email: string | null;
  active: boolean;
  hourly_rate: number | null;
}

export interface VendorListResponse {
  vendors: Vendor[];
  total: number;
}

// List active vendors — GET /api/vendors?active_only=true
export function useVendors(activeOnly = true) {
  return useQuery<VendorListResponse>({
    queryKey: ["vendors", activeOnly],
    queryFn: () => api.get("/api/vendors", { active_only: activeOnly }),
    staleTime: 300_000, // vendors rarely change; 5-min cache
  });
}

// ── Owner Payout Accounts (OPA) list hook ─────────────────────────────────────

export interface AdminOPA {
  id: number;
  owner_name: string | null;
  owner_email: string | null;
  property_id: string;
  property_name: string | null;
  commission_rate: string | null;
  streamline_owner_id: number | null;
  stripe_account_id: string | null;
  account_status: string;
}

export interface AdminOPAListResponse {
  accounts: AdminOPA[];
  total: number;
}

// List all owner payout accounts — GET /api/admin/payouts/accounts
export function useAdminOPAs() {
  return useQuery<AdminOPAListResponse>({
    queryKey: ["admin-opas"],
    queryFn: () => api.get("/api/admin/payouts/accounts"),
    staleTime: 60_000,
  });
}
