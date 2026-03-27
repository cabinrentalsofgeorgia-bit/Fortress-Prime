"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";

export type CouncilConnectionState =
  | "idle"
  | "starting"
  | "connecting"
  | "open"
  | "reconnecting"
  | "done"
  | "stopped"
  | "error";

export interface CouncilOpinion {
  persona: string;
  seat: number;
  slug: string;
  signal: string;
  conviction: number;
  reasoning: string;
  defense_arguments: string[];
  risk_factors: string[];
  recommended_actions: string[];
  timestamp: string;
  model_used?: string;
  elapsed_seconds?: number;
}

export interface CouncilConsensus {
  consensus_signal: string;
  consensus_conviction: number;
  net_score: number;
  net_score_adjusted: number;
  defense_count: number;
  weak_count: number;
  neutral_count: number;
  error_count: number;
  total_voters: number;
  agreement_rate: number;
  signal_breakdown: Record<string, number>;
  top_defense_arguments: string[];
  top_risk_factors: string[];
  top_recommended_actions: string[];
}

export interface CouncilDonePayload extends CouncilConsensus {
  type: "done";
  status: string;
  session_id: string;
  job_id: string;
  case_type?: string;
  case_brief?: string;
  timestamp?: string;
  elapsed_seconds?: number;
  opinions: CouncilOpinion[];
  final_json_ld?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  event_id?: string;
  sha256_signature?: string;
  vault_error?: string;
}

export interface CouncilStreamEvent {
  id: string | null;
  type: string;
  payload: Record<string, unknown>;
  receivedAt: number;
}

interface CouncilContextFrozen {
  vector_count: number;
  chunk_count: number;
  collection?: string;
}

interface CouncilVaulted {
  event_id: string;
  sha256_signature: string;
  vector_count?: number;
  execution_time_ms?: number;
}

interface CouncilStartResponse {
  status: string;
  case_slug: string;
  job_id: string;
  stream_url: string;
  status_url: string;
}

interface CouncilStartRequest {
  url: string;
  body?: Record<string, unknown>;
}

interface CouncilStreamOptions {
  buildStartRequest?: (caseSlug: string) => CouncilStartRequest;
}

interface AsyncJobStatusResponse {
  id: string;
  status: string;
  result: Record<string, unknown>;
  error?: string | null;
}

interface PersistedCouncilSession {
  jobId: string;
  caseSlug: string;
  lastEventId: string | null;
}

interface CouncilStreamState {
  jobId: string | null;
  sessionId: string | null;
  lastEventId: string | null;
  connectionState: CouncilConnectionState;
  isStreaming: boolean;
  error: string | null;
  events: CouncilStreamEvent[];
  opinions: CouncilOpinion[];
  consensus: CouncilConsensus | null;
  finalResult: CouncilDonePayload | null;
  contextFrozen: CouncilContextFrozen | null;
  vaulted: CouncilVaulted | null;
}

const MAX_EVENTS = 200;
const SESSION_STORAGE_PREFIX = "council-stream:";

const INITIAL_STATE: CouncilStreamState = {
  jobId: null,
  sessionId: null,
  lastEventId: null,
  connectionState: "idle",
  isStreaming: false,
  error: null,
  events: [],
  opinions: [],
  consensus: null,
  finalResult: null,
  contextFrozen: null,
  vaulted: null,
};

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function sessionStorageKey(caseSlug: string): string {
  return `${SESSION_STORAGE_PREFIX}${caseSlug}`;
}

function readPersistedSession(caseSlug: string): PersistedCouncilSession | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.sessionStorage.getItem(sessionStorageKey(caseSlug));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedCouncilSession;
    if (!parsed?.jobId || parsed.caseSlug !== caseSlug) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writePersistedSession(
  caseSlug: string,
  data: PersistedCouncilSession | null,
): void {
  if (!isBrowser()) return;
  const key = sessionStorageKey(caseSlug);
  if (!data) {
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, JSON.stringify(data));
}

function coerceOpinion(value: unknown): CouncilOpinion | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return {
    persona: typeof record.persona === "string" ? record.persona : "Unknown Persona",
    seat: typeof record.seat === "number" ? record.seat : Number(record.seat ?? 0),
    slug: typeof record.slug === "string" ? record.slug : "",
    signal: typeof record.signal === "string" ? record.signal : "NEUTRAL",
    conviction:
      typeof record.conviction === "number"
        ? record.conviction
        : Number(record.conviction ?? 0),
    reasoning: typeof record.reasoning === "string" ? record.reasoning : "",
    defense_arguments: Array.isArray(record.defense_arguments)
      ? record.defense_arguments.map(String)
      : [],
    risk_factors: Array.isArray(record.risk_factors)
      ? record.risk_factors.map(String)
      : [],
    recommended_actions: Array.isArray(record.recommended_actions)
      ? record.recommended_actions.map(String)
      : [],
    timestamp: typeof record.timestamp === "string" ? record.timestamp : "",
    model_used: typeof record.model_used === "string" ? record.model_used : undefined,
    elapsed_seconds:
      typeof record.elapsed_seconds === "number"
        ? record.elapsed_seconds
        : Number(record.elapsed_seconds ?? 0),
  };
}

function upsertOpinion(
  opinions: CouncilOpinion[],
  opinion: CouncilOpinion,
): CouncilOpinion[] {
  const existingIndex = opinions.findIndex((entry) => entry.seat === opinion.seat);
  if (existingIndex === -1) {
    return [...opinions, opinion].toSorted((a, b) => a.seat - b.seat);
  }
  const next = [...opinions];
  next[existingIndex] = opinion;
  return next.toSorted((a, b) => a.seat - b.seat);
}

function coerceConsensus(value: unknown): CouncilConsensus | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return {
    consensus_signal:
      typeof record.consensus_signal === "string"
        ? record.consensus_signal
        : "UNKNOWN",
    consensus_conviction: Number(record.consensus_conviction ?? 0),
    net_score: Number(record.net_score ?? 0),
    net_score_adjusted: Number(record.net_score_adjusted ?? 0),
    defense_count: Number(record.defense_count ?? 0),
    weak_count: Number(record.weak_count ?? 0),
    neutral_count: Number(record.neutral_count ?? 0),
    error_count: Number(record.error_count ?? 0),
    total_voters: Number(record.total_voters ?? 0),
    agreement_rate: Number(record.agreement_rate ?? 0),
    signal_breakdown:
      record.signal_breakdown &&
      typeof record.signal_breakdown === "object" &&
      !Array.isArray(record.signal_breakdown)
        ? Object.fromEntries(
            Object.entries(record.signal_breakdown as Record<string, unknown>).map(
              ([key, item]) => [key, Number(item ?? 0)],
            ),
          )
        : {},
    top_defense_arguments: Array.isArray(record.top_defense_arguments)
      ? record.top_defense_arguments.map(String)
      : [],
    top_risk_factors: Array.isArray(record.top_risk_factors)
      ? record.top_risk_factors.map(String)
      : [],
    top_recommended_actions: Array.isArray(record.top_recommended_actions)
      ? record.top_recommended_actions.map(String)
      : [],
  };
}

function coerceDonePayload(value: Record<string, unknown>): CouncilDonePayload | null {
  const consensus = coerceConsensus(value);
  if (!consensus) return null;
  const finalJsonLd =
    value.final_json_ld &&
    typeof value.final_json_ld === "object" &&
    !Array.isArray(value.final_json_ld)
      ? (value.final_json_ld as Record<string, unknown>)
      : undefined;
  const metadata =
    value.metadata && typeof value.metadata === "object" && !Array.isArray(value.metadata)
      ? (value.metadata as Record<string, unknown>)
      : undefined;
  return {
    type: "done",
    ...consensus,
    status: typeof value.status === "string" ? value.status : "complete",
    session_id: typeof value.session_id === "string" ? value.session_id : "",
    job_id: typeof value.job_id === "string" ? value.job_id : "",
    case_type: typeof value.case_type === "string" ? value.case_type : undefined,
    case_brief: typeof value.case_brief === "string" ? value.case_brief : undefined,
    timestamp: typeof value.timestamp === "string" ? value.timestamp : undefined,
    elapsed_seconds: Number(value.elapsed_seconds ?? 0),
    opinions: Array.isArray(value.opinions)
      ? value.opinions.map(coerceOpinion).filter(Boolean) as CouncilOpinion[]
      : [],
    final_json_ld: finalJsonLd,
    metadata,
    event_id: typeof value.event_id === "string" ? value.event_id : undefined,
    sha256_signature:
      typeof value.sha256_signature === "string"
        ? value.sha256_signature
        : undefined,
    vault_error: typeof value.vault_error === "string" ? value.vault_error : undefined,
  };
}

function summarizeEvent(payload: Record<string, unknown>): string {
  const type = String(payload.type ?? "event");
  if (type === "persona_start") {
    return `Seat ${String(payload.seat ?? "?")} started ${String(payload.name ?? "persona")}`;
  }
  if (type === "persona_complete") {
    const opinion = coerceOpinion(payload.opinion);
    return opinion
      ? `Seat ${opinion.seat} ${opinion.persona}: ${opinion.signal} (${Math.round(
          opinion.conviction * 100,
        )}%)`
      : "Persona completed";
  }
  if (type === "consensus") {
    return `Consensus ${String(payload.consensus_signal ?? "UNKNOWN")} (${String(
      payload.consensus_conviction ?? "0",
    )})`;
  }
  if (type === "context_frozen") {
    return `Context frozen with ${String(payload.vector_count ?? 0)} vectors`;
  }
  if (type === "vaulted") {
    return `Vault sealed ${String(payload.event_id ?? "")}`;
  }
  if (type === "error") {
    return String(payload.message ?? "Council stream error");
  }
  if (type === "status") {
    return String(payload.message ?? "Status update");
  }
  return JSON.stringify(payload).slice(0, 200);
}

export function useCouncilStream(
  caseSlug: string,
  options: CouncilStreamOptions = {},
) {
  const { buildStartRequest } = options;
  const [state, setState] = useState<CouncilStreamState>(INITIAL_STATE);

  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectRef = useRef<(jobId: string, cursor?: string | null) => void>(() => {});
  const lastEventIdRef = useRef<string | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(false);

  const persistSession = useCallback(
    (jobId: string | null, lastEventId: string | null) => {
      if (!caseSlug) return;
      if (!jobId) {
        writePersistedSession(caseSlug, null);
        return;
      }
      writePersistedSession(caseSlug, {
        jobId,
        caseSlug,
        lastEventId,
      });
    },
    [caseSlug],
  );

  const cleanupConnection = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const resetState = useCallback(() => {
    cleanupConnection();
    shouldReconnectRef.current = false;
    reconnectAttemptsRef.current = 0;
    lastEventIdRef.current = null;
    jobIdRef.current = null;
    persistSession(null, null);
    setState(INITIAL_STATE);
  }, [cleanupConnection, persistSession]);

  const applyPayload = useCallback(
    (payload: Record<string, unknown>, eventId: string | null) => {
      const nextEvent: CouncilStreamEvent = {
        id: eventId,
        type: String(payload.type ?? "event"),
        payload,
        receivedAt: Date.now(),
      };

      setState((current) => {
        let next = {
          ...current,
          lastEventId: eventId ?? current.lastEventId,
          error: nextEvent.type === "error"
            ? String(payload.message ?? "Council stream error")
            : current.error,
          events: [...current.events, nextEvent].slice(-MAX_EVENTS),
        };

        if (nextEvent.type === "session_start") {
          next = {
            ...next,
            sessionId:
              typeof payload.session_id === "string"
                ? payload.session_id
                : current.sessionId,
            jobId:
              typeof payload.job_id === "string" ? payload.job_id : current.jobId,
            connectionState: "open",
            isStreaming: true,
          };
        }

        if (nextEvent.type === "context_frozen") {
          next = {
            ...next,
            contextFrozen: {
              vector_count: Number(payload.vector_count ?? 0),
              chunk_count: Number(payload.chunk_count ?? 0),
              collection:
                typeof payload.collection === "string"
                  ? payload.collection
                  : undefined,
            },
            connectionState: "open",
            isStreaming: true,
          };
        }

        if (nextEvent.type === "persona_complete") {
          const opinion = coerceOpinion(payload.opinion);
          if (opinion) {
            next = {
              ...next,
              opinions: upsertOpinion(next.opinions, opinion),
              connectionState: "open",
              isStreaming: true,
            };
          }
        }

        if (nextEvent.type === "consensus") {
          const consensus = coerceConsensus(payload);
          if (consensus) {
            next = {
              ...next,
              consensus,
              connectionState: "open",
              isStreaming: true,
            };
          }
        }

        if (nextEvent.type === "vaulted") {
          next = {
            ...next,
            vaulted: {
              event_id: String(payload.event_id ?? ""),
              sha256_signature: String(payload.sha256_signature ?? ""),
              vector_count: Number(payload.vector_count ?? 0),
              execution_time_ms: Number(payload.execution_time_ms ?? 0),
            },
          };
        }

        if (nextEvent.type === "done") {
          const finalResult = coerceDonePayload(payload);
          next = {
            ...next,
            finalResult,
            consensus: finalResult ?? next.consensus,
            opinions:
              finalResult?.opinions.length ? finalResult.opinions : next.opinions,
            connectionState: "done",
            isStreaming: false,
            error: null,
          };
        }

        if (nextEvent.type === "error") {
          next = {
            ...next,
            connectionState: "error",
            isStreaming: false,
          };
        }

        return next;
      });
    },
    [],
  );

  const connect = useCallback(
    (jobId: string, cursor?: string | null) => {
      if (!caseSlug) return;

      cleanupConnection();
      const search = new URLSearchParams();
      const effectiveCursor = cursor ?? lastEventIdRef.current;
      if (effectiveCursor) {
        search.set("cursor", effectiveCursor);
      }

      setState((current) => ({
        ...current,
        jobId,
        sessionId: current.sessionId ?? jobId,
        connectionState:
          reconnectAttemptsRef.current > 0 ? "reconnecting" : "connecting",
        isStreaming: true,
        error: null,
      }));

      const url = `/api/legal/council/${encodeURIComponent(jobId)}/stream${
        search.size ? `?${search.toString()}` : ""
      }`;
      const source = new EventSource(url, { withCredentials: true });
      sourceRef.current = source;

      source.onopen = () => {
        reconnectAttemptsRef.current = 0;
        setState((current) => ({
          ...current,
          connectionState: "open",
          isStreaming: true,
          error: null,
        }));
      };

      source.onmessage = (event) => {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        const eventId = event.lastEventId || null;
        if (eventId) {
          lastEventIdRef.current = eventId;
          persistSession(jobId, eventId);
        }
        applyPayload(payload, eventId);
        if (payload.type === "done" || payload.type === "error") {
          shouldReconnectRef.current = false;
          cleanupConnection();
          if (payload.type === "done") {
            persistSession(null, null);
          }
        }
      };

      source.onerror = async () => {
        cleanupConnection();
        if (!shouldReconnectRef.current) {
          return;
        }

        try {
          const job = await api.get<AsyncJobStatusResponse>(`/api/async/jobs/${jobId}`);
          if (job.status === "succeeded" && job.result) {
            const donePayload = {
              ...job.result,
              type: "done",
              job_id: typeof job.result.job_id === "string" ? job.result.job_id : jobId,
              session_id:
                typeof job.result.session_id === "string"
                  ? job.result.session_id
                  : jobId,
            } as Record<string, unknown>;
            applyPayload(donePayload, lastEventIdRef.current);
            shouldReconnectRef.current = false;
            persistSession(null, null);
            return;
          }
          if (job.status === "failed" || job.status === "cancelled") {
            applyPayload(
              {
                type: "error",
                job_id: jobId,
                session_id: jobId,
                message:
                  job.error || `Council job ended with status '${job.status}'`,
              },
              lastEventIdRef.current,
            );
            shouldReconnectRef.current = false;
            persistSession(null, null);
            return;
          }
        } catch {
          // Fall through to timed reconnect.
        }

        reconnectAttemptsRef.current += 1;
        const delay = Math.min(10_000, 1_500 * reconnectAttemptsRef.current);
        setState((current) => ({
          ...current,
          connectionState: "reconnecting",
          isStreaming: true,
          error: `Council stream interrupted. Reconnecting in ${Math.round(delay / 1000)}s...`,
        }));
        reconnectTimerRef.current = setTimeout(() => {
          connectRef.current(jobId, lastEventIdRef.current);
        }, delay);
      };
    },
    [applyPayload, caseSlug, cleanupConnection, persistSession],
  );

  const start = useCallback(async () => {
    if (!caseSlug.trim()) return null;
    cleanupConnection();
    shouldReconnectRef.current = true;
    reconnectAttemptsRef.current = 0;
    lastEventIdRef.current = null;
    jobIdRef.current = null;
    persistSession(null, null);

    setState({
      ...INITIAL_STATE,
      connectionState: "starting",
    });

    const requestConfig = buildStartRequest
      ? buildStartRequest(caseSlug)
      : { url: `/api/legal/cases/${caseSlug}/deliberate` };
    const response = await api.post<CouncilStartResponse>(
      requestConfig.url,
      requestConfig.body,
    );
    const jobId = response.job_id;
    jobIdRef.current = jobId;
    persistSession(jobId, null);
    setState((current) => ({
      ...current,
      jobId,
      sessionId: jobId,
      connectionState: "connecting",
      isStreaming: true,
      error: null,
    }));
    connect(jobId);
    return response;
  }, [buildStartRequest, caseSlug, cleanupConnection, connect, persistSession]);

  const stop = useCallback(() => {
    shouldReconnectRef.current = false;
    cleanupConnection();
    persistSession(null, null);
    setState((current) => ({
      ...current,
      isStreaming: false,
      connectionState: current.finalResult ? "done" : "stopped",
      error: current.error,
    }));
  }, [cleanupConnection, persistSession]);

  useEffect(() => {
    if (!caseSlug) return;
    const persisted = readPersistedSession(caseSlug);
    if (!persisted?.jobId) return;

    let cancelled = false;
    shouldReconnectRef.current = true;
    jobIdRef.current = persisted.jobId;
    lastEventIdRef.current = persisted.lastEventId;

    void api
      .get<AsyncJobStatusResponse>(`/api/async/jobs/${persisted.jobId}`)
      .then((job) => {
        if (cancelled) return;
        if (job.status === "succeeded" && job.result) {
          applyPayload(
            {
              ...job.result,
              type: "done",
              job_id:
                typeof job.result.job_id === "string"
                  ? job.result.job_id
                  : persisted.jobId,
              session_id:
                typeof job.result.session_id === "string"
                  ? job.result.session_id
                  : persisted.jobId,
            },
            persisted.lastEventId,
          );
          persistSession(null, null);
          shouldReconnectRef.current = false;
          return;
        }
        if (job.status === "failed" || job.status === "cancelled") {
          applyPayload(
            {
              type: "error",
              job_id: persisted.jobId,
              session_id: persisted.jobId,
              message:
                job.error || `Council job ended with status '${job.status}'`,
            },
            persisted.lastEventId,
          );
          persistSession(null, null);
          shouldReconnectRef.current = false;
          return;
        }
        connect(persisted.jobId, persisted.lastEventId);
      })
      .catch(() => {
        if (!cancelled) {
          connect(persisted.jobId, persisted.lastEventId);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [applyPayload, caseSlug, connect, persistSession]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    return () => {
      cleanupConnection();
    };
  }, [cleanupConnection]);

  const streamLines = useMemo(
    () =>
      state.events.map((event) => ({
        id: event.id ?? `${event.type}-${event.receivedAt}`,
        label: summarizeEvent(event.payload),
        type: event.type,
        at: event.receivedAt,
      })),
    [state.events],
  );

  return {
    ...state,
    hasActiveJob: Boolean(state.jobId),
    streamLines,
    start,
    stop,
    reset: resetState,
  };
}
