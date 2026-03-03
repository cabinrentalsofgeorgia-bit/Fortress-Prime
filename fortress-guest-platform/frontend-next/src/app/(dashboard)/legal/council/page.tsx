"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getToken } from "@/lib/api";
import { Search, Loader2, FileText, Download, Terminal, Send, Bot, User, Briefcase, X, Mail, CheckCircle2, ChevronDown, RefreshCw, Shield, Scale, ExternalLink, ThumbsUp, ThumbsDown, Hash, Clock, GitCompareArrows, ShieldCheck, ShieldAlert, ArrowUpRight, ArrowDownRight, Minus, Upload, Lock } from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────

interface PersonaOpinion {
  persona: string;
  seat: number;
  slug: string;
  signal: string;
  conviction: number;
  reasoning: string;
  defense_arguments: string[];
  risk_factors: string[];
  recommended_actions: string[];
  model_used: string;
  elapsed_seconds: number;
}

interface ConsensusResult {
  consensus_signal: string;
  consensus_conviction: number;
  net_score: number;
  net_score_adjusted: number;
  defense_count: number;
  weak_count: number;
  neutral_count: number;
  total_voters: number;
  agreement_rate: number;
  signal_breakdown: Record<string, number>;
  top_defense_arguments: string[];
  top_risk_factors: string[];
  top_recommended_actions: string[];
  elapsed_seconds: number;
  opinions: PersonaOpinion[];
}

type ActivePersona = { seat: number; name: string; slug: string; status: "analyzing" | "done" };

// ── Signal styling ───────────────────────────────────────────────────

const SIGNAL_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  STRONG_DEFENSE: { bg: "bg-emerald-500/20", text: "text-emerald-400", label: "STRONG DEFENSE" },
  DEFENSE: { bg: "bg-green-500/15", text: "text-green-400", label: "DEFENSE" },
  NEUTRAL: { bg: "bg-yellow-500/15", text: "text-yellow-400", label: "NEUTRAL" },
  WEAK: { bg: "bg-orange-500/15", text: "text-orange-400", label: "WEAK" },
  VULNERABLE: { bg: "bg-red-500/20", text: "text-red-400", label: "VULNERABLE" },
};

const SEAT_ICONS = [
  "", // seat 0 unused
  "\u2696\uFE0F",  // 1 Senior Litigator
  "\uD83D\uDCDD",  // 2 Contract Auditor
  "\uD83D\uDCDA",  // 3 Statutory Scholar
  "\uD83D\uDD0D",  // 4 E-Discovery
  "\uD83D\uDE08",  // 5 Devil's Advocate
  "\uD83D\uDEE1\uFE0F",  // 6 Compliance Officer
  "\uD83C\uDFD4\uFE0F",  // 7 Local Counsel
  "\uD83D\uDCCA",  // 8 Risk Assessor
  "\uD83D\uDC51",  // 9 Chief Justice
];

const ACTIVE_CASE_SLUG = "fish-trap-suv2026000013";

async function fetchPersistedState(
  authToken: string | null,
): Promise<{
  active_brief: string | null;
  active_consensus: ConsensusResult | null;
}> {
  const headers: Record<string, string> = {};
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(`/api/legal/cases/${ACTIVE_CASE_SLUG}/state`, { headers });
  if (!res.ok) return { active_brief: null, active_consensus: null };
  return res.json();
}

async function persistState(
  patch: { active_brief?: string; active_consensus?: Record<string, unknown> },
  authToken: string | null,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  await fetch(`/api/legal/cases/${ACTIVE_CASE_SLUG}/state`, {
    method: "PATCH",
    headers,
    body: JSON.stringify(patch),
  }).catch((err) => console.error("[WAR ROOM] Failed to persist state:", err));
}

// ── Default case brief ───────────────────────────────────────────────

const DEFAULT_BRIEF = `CASE: Generali Global Assistance, Inc. v. Cabin Rentals of Georgia, LLC
COURT: Fannin County Superior Court, Appalachian Judicial Circuit, Georgia
CASE NUMBER: SUV2026000013
JUDGE: J. David Stuart

PLAINTIFF: Generali Global Assistance, Inc. (foreign insurance company)
DEFENDANT: Cabin Rentals of Georgia, LLC d/b/a CROG ("CROG")

CLAIMS: Breach of Contract ($7,500 unpaid travel insurance commissions) and Account Stated.
COLLECTION AGENT: RTS Financial Services (pre-suit demand letters)

KEY ISSUES:
1. PRIVITY OF CONTRACT: The commission agreement was signed by "Colleen Blackman" — NOT by any authorized officer or agent of CROG LLC. Blackman's authority to bind CROG is disputed.
2. STATUTE OF LIMITATIONS: O.C.G.A. § 9-3-25 provides a 4-year statute of limitations for written contracts. The commission agreement and earliest unpaid invoices may predate this window.
3. ACCOUNT STATED: Generali alleges CROG received invoices and failed to object, creating an Account Stated. However, 2021 correspondence between Joan Cassidy and Gary Knight may show CROG disputed the commissions.
4. INVOICE DISCREPANCIES: The $7,500 total claimed does not clearly reconcile with the commission records available.
5. FDCPA COMPLIANCE: RTS Financial's collection letters may contain violations of the Fair Debt Collection Practices Act.

ANSWER DEADLINE: March 17, 2026 (extended via Motion for Extension filed February 15, 2026)

TASK: Analyze this case through your specialized legal lens and provide your defense assessment.`;

// ── Component ────────────────────────────────────────────────────────

const GENERALI_ENTITIES = [
  "Generali",
  "CSA Travel Protection",
  "Joan Cassidy",
  "RTS Financial",
  "Colleen Blackman",
  "travel insurance commission",
];

export default function LegalCouncilPage() {
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [isRunning, setIsRunning] = useState(false);
  const [activePersonas, setActivePersonas] = useState<ActivePersona[]>([]);
  const [opinions, setOpinions] = useState<PersonaOpinion[]>([]);
  const [consensus, setConsensus] = useState<ConsensusResult | null>(null);
  const [selectedOpinion, setSelectedOpinion] = useState<PersonaOpinion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [hydrating, setHydrating] = useState(true);
  const [enginesOpen, setEnginesOpen] = useState(false);

  // ── Verifiable Intelligence Engine (Deliberation Ledger) ───────────
  interface LedgerEvent {
    event_id: string;
    timestamp: string;
    trigger_type: string;
    consensus_signal: string;
    consensus_conviction: number;
    execution_time_ms: number;
    vector_count: number;
    opinion_count: number;
    sha256_signature: string;
  }

  interface SeatDelta {
    seat: number;
    persona: string;
    model_used: string;
    old_signal: string;
    new_signal: string;
    flipped: boolean;
    old_conviction: number;
    new_conviction: number;
    conviction_delta: number;
  }

  interface DeltaResult {
    context_delta: {
      added_vectors: number;
      removed_vectors: number;
      shared_vectors: number;
      added_evidence: { vector_id: string; chunk_preview: string }[];
      removed_vector_ids: string[];
    };
    seat_deltas: SeatDelta[];
    flipped_count: number;
    consensus_shift: {
      old_signal: string;
      new_signal: string;
      signal_changed: boolean;
      old_conviction: number;
      new_conviction: number;
      conviction_delta: number;
    };
  }

  const [ledgerHistory, setLedgerHistory] = useState<LedgerEvent[]>([]);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [ledgerDelta, setLedgerDelta] = useState<DeltaResult | null>(null);
  const [ledgerVerify, setLedgerVerify] = useState<Record<string, "checking" | "secure" | "tampered" | "error">>({});
  const [lastVaultedId, setLastVaultedId] = useState<string | null>(null);

  const fetchLedgerHistory = useCallback(async () => {
    setLedgerLoading(true);
    try {
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(`/api/legal/council/history/${ACTIVE_CASE_SLUG}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setLedgerHistory(data.data ?? []);
      }
    } catch {
      // non-critical
    } finally {
      setLedgerLoading(false);
    }
  }, []);

  const verifyEvent = useCallback(async (eventId: string) => {
    setLedgerVerify((prev) => ({ ...prev, [eventId]: "checking" }));
    try {
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(`/api/legal/council/event/${eventId}/verify`, { headers });
      if (res.ok) {
        const data = await res.json();
        setLedgerVerify((prev) => ({
          ...prev,
          [eventId]: data.verified ? "secure" : "tampered",
        }));
      } else {
        setLedgerVerify((prev) => ({ ...prev, [eventId]: "error" }));
      }
    } catch {
      setLedgerVerify((prev) => ({ ...prev, [eventId]: "error" }));
    }
  }, []);

  const loadDelta = useCallback(async (eventA: string, eventB: string) => {
    try {
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(
        `/api/legal/council/history/${ACTIVE_CASE_SLUG}/delta?event_a=${eventA}&event_b=${eventB}`,
        { headers },
      );
      if (res.ok) {
        const data = await res.json();
        setLedgerDelta(data);
      }
    } catch {
      // non-critical
    }
  }, []);

  // ── Agentic Zero-Touch Ingest ─────────────────────────────────────
  type IngestStatus = "idle" | "hashing" | "uploading" | "success" | "error";

  interface IngestResult {
    case_slug: string;
    nas_path: string;
    sha256_signature: string;
    evidence_id: number;
    extracted_entities: { type: string; tracking_number: string };
  }

  const [ingestStatus, setIngestStatus] = useState<IngestStatus>("idle");
  const [ingestResult, setIngestResult] = useState<IngestResult | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const ingestFileRef = useRef<HTMLInputElement>(null);

  const computeClientHash = useCallback(async (file: File): Promise<string> => {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
  }, []);

  const processIngest = useCallback(async (file: File) => {
    setIngestStatus("hashing");
    setIngestResult(null);
    setIngestError(null);

    try {
      const clientHash = await computeClientHash(file);

      setIngestStatus("uploading");
      const formData = new FormData();
      formData.append("file", file);
      formData.append("client_hash", clientHash);

      const token = getToken();
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/council/ingest/sota", {
        method: "POST",
        headers,
        body: formData,
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "Upload failed");
        setIngestError(`Ingest rejected (${res.status}): ${errText.slice(0, 200)}`);
        setIngestStatus("error");
        return;
      }

      const data = await res.json();
      setIngestResult(data);
      setIngestStatus("success");
      fetchLedgerHistory();

      setTimeout(() => {
        setIngestStatus("idle");
        setIngestResult(null);
      }, 8000);
    } catch (err) {
      setIngestError(err instanceof Error ? err.message : "Ingest failed");
      setIngestStatus("error");
    }
  }, [computeClientHash, fetchLedgerHistory]);

  interface CasePrecedent {
    id: number;
    case_slug: string;
    citation: string;
    url: string;
    relevance_score: number;
    justification: string;
    extracted_at: string;
  }

  const [precedents, setPrecedents] = useState<CasePrecedent[]>([]);
  const [precedentsLoading, setPrecedentsLoading] = useState(false);

  const fetchPrecedents = useCallback(async () => {
    setPrecedentsLoading(true);
    try {
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(
        `/api/legal/counsel/dispatch/precedents/${ACTIVE_CASE_SLUG}`,
        { headers },
      );
      if (res.ok) {
        const data = await res.json();
        setPrecedents(data.precedents ?? []);
      }
    } catch {
      // non-critical — silently fail
    } finally {
      setPrecedentsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchPersistedState(getToken()).then((state) => {
      if (cancelled) return;
      if (state.active_brief) setBrief(state.active_brief);
      if (state.active_consensus) setConsensus(state.active_consensus);
      setHydrating(false);
    }).catch(() => {
      if (!cancelled) setHydrating(false);
    });
    fetchPrecedents();
    fetchLedgerHistory();
    return () => { cancelled = true; };
  }, [fetchPrecedents, fetchLedgerHistory]);

  const [discoveryRunning, setDiscoveryRunning] = useState(false);
  const [discoveryStats, setDiscoveryStats] = useState<{
    total_hits: number;
    elapsed_seconds: number;
    source_stats: Record<string, number>;
  } | null>(null);

  const runEDiscovery = useCallback(async () => {
    setDiscoveryRunning(true);
    setDiscoveryStats(null);
    setError(null);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/discovery/extract", {
        method: "POST",
        headers,
        body: JSON.stringify({ entities: GENERALI_ENTITIES, max_per_table: 200 }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "Unknown error");
        setError(`E-Discovery failed (${res.status}): ${errText.slice(0, 200)}`);
        return;
      }

      const data = await res.json();
      setDiscoveryStats({
        total_hits: data.total_hits,
        elapsed_seconds: data.elapsed_seconds,
        source_stats: data.source_stats,
      });

      if (data.brief_injection) {
        setBrief((prev) => {
          const updated = prev + "\n" + data.brief_injection;
          persistState({ active_brief: updated }, getToken());
          return updated;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "E-Discovery request failed");
    } finally {
      setDiscoveryRunning(false);
    }
  }, []);

  const [docGenRunning, setDocGenRunning] = useState(false);

  const generatePleading = useCallback(async () => {
    if (!consensus) return;
    setDocGenRunning(true);
    setError(null);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/document/draft", {
        method: "POST",
        headers,
        body: JSON.stringify({ case_brief: brief, consensus }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "Unknown error");
        setError(`DocGen failed (${res.status}): ${errText.slice(0, 200)}`);
        return;
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download =
        res.headers.get("content-disposition")?.match(/filename="(.+?)"/)?.[1] ??
        "Answer_and_Defenses.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document generation failed");
    } finally {
      setDocGenRunning(false);
    }
  }, [brief, consensus]);

  /* ── Strategy Terminal State ─────────────────────────────────────── */

  interface ChatMessage {
    role: "user" | "assistant";
    content: string;
  }

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatStreaming, setChatStreaming] = useState(false);
  const [chatModel, setChatModel] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  /* ── Outside Counsel Dispatch State ──────────────────────────────── */

  interface HuntAttorney {
    attorney_name: string;
    firm: string;
    email: string;
    phone: string;
    jurisdiction_match: boolean;
    specialty_match: boolean;
    reason: string;
  }

  type CounselPhase = "hunt-config" | "hunting" | "hunt-results" | "drafting" | "draft-ready" | "sent";

  const [counselModalOpen, setCounselModalOpen] = useState(false);
  const [counselPhase, setCounselPhase] = useState<CounselPhase>("hunt-config");
  const [counselJurisdiction, setCounselJurisdiction] = useState("");
  const [counselSpecialty, setCounselSpecialty] = useState("");
  const [huntAttorneys, setHuntAttorneys] = useState<HuntAttorney[]>([]);
  const [huntQueries, setHuntQueries] = useState<string[]>([]);
  const [huntSources, setHuntSources] = useState(0);
  const [huntModel, setHuntModel] = useState("");
  const [counselDraftLoading, setCounselDraftLoading] = useState(false);
  const [counselSubject, setCounselSubject] = useState("");
  const [counselBody, setCounselBody] = useState("");
  const [counselEmails, setCounselEmails] = useState("");
  const [counselModel, setCounselModel] = useState("");
  const [counselSent, setCounselSent] = useState(false);

  const _inferCaseParams = useCallback((caseText: string) => {
    let jur = "Georgia";
    let spec = "Breach of Contract Defense";

    const jurPatterns = [
      /(?:court|jurisdiction)[:\s]*([A-Z][a-zA-Z\s,]+(?:Court|Circuit|District|County))/i,
      /(?:Superior Court|Circuit Court|District Court|Federal Court)[,\s]+(?:of\s+)?([A-Za-z\s]+)/i,
      /\b(Georgia|Florida|Texas|California|New York|Delaware|Alabama|Tennessee|North Carolina|South Carolina)\b/i,
    ];
    for (const pat of jurPatterns) {
      const m = caseText.match(pat);
      if (m) { jur = m[1]?.trim() || m[0]?.trim() || jur; break; }
    }

    const specPatterns = [
      /(?:CLAIMS?|cause of action)[:\s]*([^\n.]+)/i,
      /(?:breach of contract|negligence|fraud|employment|insurance|personal injury|real estate|landlord.tenant|debt collection|FDCPA|warranty)/i,
    ];
    for (const pat of specPatterns) {
      const m = caseText.match(pat);
      if (m) { spec = m[1]?.trim() || m[0]?.trim() || spec; break; }
    }

    return { jurisdiction: jur, specialty: spec };
  }, []);

  const openCounselModal = useCallback(() => {
    const inferred = _inferCaseParams(brief);
    setCounselJurisdiction(inferred.jurisdiction);
    setCounselSpecialty(inferred.specialty);
    setCounselPhase("hunt-config");
    setHuntAttorneys([]);
    setHuntQueries([]);
    setHuntSources(0);
    setHuntModel("");
    setCounselSubject("");
    setCounselBody("");
    setCounselEmails("");
    setCounselModel("");
    setCounselSent(false);
    setCounselModalOpen(true);
  }, [brief, _inferCaseParams]);

  const commenceHunt = useCallback(async () => {
    setCounselPhase("hunting");
    setHuntAttorneys([]);
    setError(null);

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/counsel/dispatch/hunt", {
        method: "POST",
        headers,
        body: JSON.stringify({
          case_brief: brief,
          jurisdiction: counselJurisdiction,
          specialty: counselSpecialty,
        }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "Unknown error");
        setError(`Hunt failed (${res.status}): ${errText.slice(0, 300)}`);
        setCounselPhase("hunt-config");
        return;
      }

      const data = await res.json();
      setHuntAttorneys(data.attorneys ?? []);
      setHuntQueries(data.search_queries ?? []);
      setHuntSources(data.sources_searched ?? 0);
      setHuntModel(data.model_used ?? "");

      if (Array.isArray(data.precedents) && data.precedents.length > 0) {
        setPrecedents((prev) => {
          const existingCitations = new Set(prev.map((p) => p.citation));
          const newOnes = data.precedents.filter(
            (p: CasePrecedent) => !existingCitations.has(p.citation),
          );
          return [...prev, ...newOnes];
        });
      }

      const emailList = (data.attorneys ?? [])
        .map((a: HuntAttorney) => a.email)
        .filter((e: string) => e && !e.toLowerCase().includes("not found"))
        .join(", ");
      setCounselEmails(emailList);
      setCounselPhase("hunt-results");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hunt request failed");
      setCounselPhase("hunt-config");
    }
  }, [brief, counselJurisdiction, counselSpecialty]);

  const generateDraftFromHunt = useCallback(async () => {
    setCounselPhase("drafting");
    setCounselDraftLoading(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/counsel/dispatch/draft", {
        method: "POST",
        headers,
        body: JSON.stringify({ case_brief: brief, consensus: consensus ?? undefined }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "Unknown error");
        setCounselBody(`[Draft generation failed (${res.status}): ${errText.slice(0, 300)}]`);
        setCounselPhase("draft-ready");
        return;
      }

      const data = await res.json();
      setCounselSubject(data.subject ?? "");
      setCounselBody(data.body ?? "");
      setCounselModel(data.model_used ?? "");
      setCounselPhase("draft-ready");
    } catch (err) {
      setCounselBody(
        `[Error: ${err instanceof Error ? err.message : "Failed to generate draft"}]`,
      );
      setCounselPhase("draft-ready");
    } finally {
      setCounselDraftLoading(false);
    }
  }, [brief, consensus]);

  const dispatchCounsel = useCallback(() => {
    const emails = counselEmails
      .split(",")
      .map((e) => e.trim())
      .filter(Boolean);
    console.log("[COUNSEL DISPATCH] Payload ready for send:", {
      to: emails,
      subject: counselSubject,
      body: counselBody,
    });
    setCounselPhase("sent");
    setCounselSent(true);
  }, [counselEmails, counselSubject, counselBody]);

  /* ── Episodic Memory Feedback State & Handler ──────────────────── */
  const [feedbackSent, setFeedbackSent] = useState<Record<string, "thumbs_up" | "thumbs_down">>({});
  const [feedbackLoading, setFeedbackLoading] = useState<string | null>(null);

  const submitFeedback = useCallback(
    async (
      itemType: "attorney" | "precedent",
      itemName: string,
      sentiment: "thumbs_up" | "thumbs_down",
      notes: string = "",
    ) => {
      const feedbackKey = `${itemType}:${itemName}`;
      if (feedbackSent[feedbackKey]) return;

      setFeedbackLoading(feedbackKey);
      try {
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        const token = getToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const body = {
          case_slug: ACTIVE_CASE_SLUG,
          item_type: itemType,
          item_name: itemName,
          sentiment,
          jurisdiction: counselJurisdiction,
          specialty: counselSpecialty,
          feedback_notes:
            notes ||
            (sentiment === "thumbs_down"
              ? `CEO rejected ${itemType}: ${itemName}`
              : `CEO approved ${itemType}: ${itemName}`),
        };

        const res = await fetch("/api/legal/counsel/dispatch/feedback", {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        });

        if (res.ok) {
          setFeedbackSent((prev) => ({ ...prev, [feedbackKey]: sentiment }));
        } else {
          console.error(`[FEEDBACK] Failed (${res.status}):`, await res.text().catch(() => ""));
        }
      } catch (err) {
        console.error("[FEEDBACK] Error:", err);
      } finally {
        setFeedbackLoading(null);
      }
    },
    [feedbackSent, counselJurisdiction, counselSpecialty],
  );

  const sendStrategyMessage = useCallback(async () => {
    const msg = chatInput.trim();
    if (!msg || chatStreaming) return;

    const userMsg: ChatMessage = { role: "user", content: msg };
    setChatMessages((prev) => [...prev, userMsg]);
    setChatInput("");
    setChatStreaming(true);
    setChatModel(null);

    const assistantMsg: ChatMessage = { role: "assistant", content: "" };
    setChatMessages((prev) => [...prev, assistantMsg]);

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/strategy/chat", {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: msg,
          case_brief: brief,
          consensus: consensus ?? undefined,
          history: chatMessages.slice(-20).map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => "Unknown error");
        setChatMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            role: "assistant",
            content: `Error (${res.status}): ${errText.slice(0, 200)}`,
          };
          return updated;
        });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === "[DONE]") continue;

          try {
            const evt = JSON.parse(payload);
            if (evt.type === "token") {
              setChatMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + evt.content,
                  };
                }
                return updated;
              });
            } else if (evt.type === "model") {
              setChatModel(evt.model);
            } else if (evt.type === "error") {
              setChatMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + `\n\n[Error: ${evt.message}]`,
                  };
                }
                return updated;
              });
            }
          } catch {
            // skip malformed SSE events
          }
        }
      }
    } catch (err) {
      setChatMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant") {
          updated[updated.length - 1] = {
            ...last,
            content: `Connection failed: ${err instanceof Error ? err.message : "Unknown error"}`,
          };
        }
        return updated;
      });
    } finally {
      setChatStreaming(false);
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    }
  }, [chatInput, chatStreaming, brief, consensus, chatMessages]);

  const startDeliberation = useCallback(async () => {
    setIsRunning(true);
    setActivePersonas([]);
    setOpinions([]);
    setSelectedOpinion(null);
    setError(null);
    setEnginesOpen(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/api/legal/council/stream", {
        method: "POST",
        headers,
        body: JSON.stringify({
          case_brief: brief,
          context: "",
          case_slug: ACTIVE_CASE_SLUG,
          case_number: "SUV2026000013",
          trigger_type: consensus ? "RE_DELIBERATE" : "MANUAL_RUN",
        }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => "Unknown error");
        setError(`Backend returned ${res.status}: ${errText.slice(0, 200)}`);
        setIsRunning(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            handleEvent(event);
          } catch {
            // skip malformed
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsRunning(false);
      abortRef.current = null;
    }
  }, [brief]);

  const handleEvent = useCallback((event: Record<string, unknown>) => {
    const type = event.type as string;

    if (type === "persona_start") {
      setActivePersonas((prev) => [
        ...prev.filter((p) => p.seat !== (event.seat as number)),
        { seat: event.seat as number, name: event.name as string, slug: event.slug as string, status: "analyzing" },
      ]);
    }

    if (type === "persona_complete") {
      const op = event.opinion as PersonaOpinion;
      setOpinions((prev) => {
        const filtered = prev.filter((o) => o.seat !== op.seat);
        return [...filtered, op].sort((a, b) => a.seat - b.seat);
      });
      setActivePersonas((prev) =>
        prev.map((p) => (p.seat === op.seat ? { ...p, status: "done" as const } : p))
      );
    }

    if (type === "consensus") {
      const consensusData = event as unknown as ConsensusResult;
      setConsensus(consensusData);
      persistState(
        { active_consensus: consensusData as unknown as Record<string, unknown> },
        getToken(),
      );
    }

    if (type === "vaulted") {
      setLastVaultedId(event.event_id as string);
      fetchLedgerHistory();
    }

    if (type === "error") {
      setError(event.message as string);
    }
  }, [fetchLedgerHistory]);

  const stopDeliberation = useCallback(() => {
    abortRef.current?.abort();
    setIsRunning(false);
  }, []);

  const signalStyle = consensus
    ? SIGNAL_STYLES[consensus.consensus_signal] ?? SIGNAL_STYLES.NEUTRAL
    : null;

  if (hydrating) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-emerald-400" />
          <span className="text-sm text-muted-foreground">Loading War Room state...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ═══ HEADER ═══ */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Legal Strategy Command Center</h1>
          <p className="text-muted-foreground">
            Generali v. CROG &mdash; Fannin County Superior Court &mdash; SUV2026000013
          </p>
        </div>
        {consensus && (
          <div className={`flex items-center gap-2 rounded-full px-4 py-2 ${signalStyle?.bg}`}>
            <Shield className={`h-4 w-4 ${signalStyle?.text}`} />
            <span className={`text-sm font-bold ${signalStyle?.text}`}>
              {signalStyle?.label}
            </span>
            <span className="text-xs text-muted-foreground">
              {Math.round((consensus.consensus_conviction ?? 0) * 100)}%
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
      )}

      {/* ═══ ACTION TOOLS (always visible when consensus exists) ═══ */}
      {consensus && (
        <>
          {/* Consensus Summary + Quick Actions Row */}
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-400">
                Council Consensus
              </h2>
              {consensus.elapsed_seconds != null && (
                <span className="text-xs text-muted-foreground">
                  {consensus.total_voters} voters &middot; {consensus.elapsed_seconds}s
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div>
                <div className="text-xs text-muted-foreground">Signal</div>
                <div className={`text-lg font-bold ${signalStyle?.text ?? "text-foreground"}`}>
                  {signalStyle?.label ?? consensus.consensus_signal}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Conviction</div>
                <div className="text-lg font-bold">
                  {Math.round((consensus.consensus_conviction ?? 0) * 100)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Agreement</div>
                <div className="text-lg font-bold">
                  {Math.round((consensus.agreement_rate ?? 0) * 100)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Defense / Weak</div>
                <div className="text-lg font-bold">
                  <span className="text-emerald-400">{consensus.defense_count ?? 0}</span>
                  {" / "}
                  <span className="text-red-400">{consensus.weak_count ?? 0}</span>
                </div>
              </div>
            </div>

            {consensus.signal_breakdown && (
              <div className="mt-4">
                <div className="flex h-3 w-full overflow-hidden rounded-full">
                  {Object.entries(consensus.signal_breakdown).map(([signal, count]) => {
                    if (!count) return null;
                    const pct = (count / (consensus.total_voters || 1)) * 100;
                    const colors: Record<string, string> = {
                      STRONG_DEFENSE: "bg-emerald-500",
                      DEFENSE: "bg-green-500",
                      NEUTRAL: "bg-yellow-500",
                      WEAK: "bg-orange-500",
                      VULNERABLE: "bg-red-500",
                    };
                    return (
                      <div
                        key={signal}
                        className={colors[signal] ?? "bg-gray-500"}
                        style={{ width: `${pct}%` }}
                        title={`${signal}: ${count}`}
                      />
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Quick Action Buttons Row */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-amber-500/30 bg-gradient-to-r from-amber-500/5 via-yellow-500/5 to-amber-500/5 p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/20">
                    <FileText className="h-5 w-5 text-amber-400" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-amber-300">Court Pleading</div>
                    <div className="text-xs text-muted-foreground">
                      Answer &amp; Defenses (.docx)
                    </div>
                  </div>
                </div>
                <Button
                  onClick={generatePleading}
                  disabled={docGenRunning}
                  className="bg-gradient-to-r from-amber-600 to-yellow-600 hover:from-amber-500 hover:to-yellow-500 text-black font-bold shadow-lg shadow-amber-500/20"
                >
                  {docGenRunning ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-violet-500/30 bg-gradient-to-r from-violet-500/5 via-purple-500/5 to-violet-500/5 p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/20">
                    <Briefcase className="h-5 w-5 text-violet-400" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-violet-300">Outside Counsel</div>
                    <div className="text-xs text-muted-foreground">
                      RFP dispatch to attorneys
                    </div>
                  </div>
                </div>
                <Button
                  onClick={openCounselModal}
                  className="bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 text-white font-bold shadow-lg shadow-violet-500/20"
                >
                  <Mail className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ═══ STRATEGY WAR ROOM (always visible when consensus exists) ═══ */}
      {consensus && (
        <div className="rounded-xl border border-emerald-500/20 bg-gradient-to-b from-emerald-500/5 to-transparent">
          <div className="flex items-center gap-3 border-b border-emerald-500/20 px-5 py-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20">
              <Terminal className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="flex-1">
              <div className="text-sm font-bold text-emerald-300">Strategy War Room</div>
              <div className="text-[11px] text-muted-foreground">
                Interactive litigation strategy terminal
                {chatModel && (
                  <span className="ml-2 text-emerald-500/70">&middot; {chatModel}</span>
                )}
              </div>
            </div>
            {chatMessages.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-muted-foreground hover:text-destructive"
                onClick={() => { setChatMessages([]); setChatModel(null); }}
              >
                Clear
              </Button>
            )}
          </div>

          <div className="max-h-[420px] overflow-y-auto px-5 py-3 space-y-3">
            {chatMessages.length === 0 && (
              <div className="py-8 text-center text-xs text-muted-foreground/60">
                Ask procedural questions, formulate counterclaims, or paste emails for analysis.
                The E-Discovery context and Council consensus are automatically injected.
              </div>
            )}
            {chatMessages.map((m, i) => (
              <div
                key={i}
                className={`flex gap-2.5 ${m.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {m.role === "assistant" && (
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20">
                    <Bot className="h-3.5 w-3.5 text-emerald-400" />
                  </div>
                )}
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === "user"
                      ? "bg-primary/10 text-primary-foreground"
                      : "bg-muted/50 text-foreground"
                  }`}
                >
                  {m.content || (chatStreaming && i === chatMessages.length - 1 ? (
                    <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Analyzing...
                    </span>
                  ) : null)}
                </div>
                {m.role === "user" && (
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/20">
                    <User className="h-3.5 w-3.5 text-primary" />
                  </div>
                )}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          <div className="border-t border-emerald-500/20 px-5 py-3">
            <div className="flex gap-2">
              <Textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendStrategyMessage();
                  }
                }}
                placeholder="Ask the Lead Strategist... (Shift+Enter for newline)"
                rows={2}
                className="flex-1 resize-none font-mono text-xs"
                disabled={chatStreaming}
              />
              <Button
                onClick={sendStrategyMessage}
                disabled={chatStreaming || !chatInput.trim()}
                className="self-end bg-emerald-600 hover:bg-emerald-500 text-white"
                size="sm"
              >
                {chatStreaming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ═══ SUPPORTING CASE LAW (Discovered Precedents) ═══ */}
      {precedents.length > 0 && (
        <div className="rounded-xl border border-cyan-500/20 bg-gradient-to-b from-cyan-500/5 to-transparent">
          <div className="flex items-center gap-3 border-b border-cyan-500/20 px-5 py-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/20">
              <Scale className="h-4 w-4 text-cyan-400" />
            </div>
            <div className="flex-1">
              <div className="text-sm font-bold text-cyan-300">
                Supporting Case Law (Discovered)
              </div>
              <div className="text-[11px] text-muted-foreground">
                {precedents.length} precedent{precedents.length !== 1 ? "s" : ""} with 80%+ relevance &mdash; ready for attorney use
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchPrecedents}
              disabled={precedentsLoading}
              className="text-xs text-cyan-400 hover:text-cyan-300"
            >
              {precedentsLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>

          <div className="divide-y divide-cyan-500/10">
            {precedents.map((p) => (
              <div key={p.id ?? p.citation} className="px-5 py-4 hover:bg-cyan-500/[0.03] transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5 mb-1.5">
                      <span className="text-sm font-semibold text-white">
                        {p.citation || "Unknown Citation"}
                      </span>
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        p.relevance_score >= 95
                          ? "bg-emerald-500/20 text-emerald-400"
                          : p.relevance_score >= 90
                            ? "bg-green-500/15 text-green-400"
                            : "bg-cyan-500/15 text-cyan-400"
                      }`}>
                        {p.relevance_score}% RELEVANT
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {p.justification || "No justification provided."}
                    </p>
                    {p.extracted_at && (
                      <div className="mt-1.5 text-[10px] text-muted-foreground/50">
                        Discovered {new Date(p.extracted_at).toLocaleDateString("en-US", {
                          month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
                        })}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5 mt-0.5">
                    {(() => {
                      const key = `precedent:${p.citation}`;
                      const sent = feedbackSent[key];
                      const loading = feedbackLoading === key;
                      if (sent) {
                        return sent === "thumbs_up" ? (
                          <ThumbsUp className="h-4 w-4 text-emerald-400" />
                        ) : (
                          <ThumbsDown className="h-4 w-4 text-red-400" />
                        );
                      }
                      return (
                        <>
                          <button
                            disabled={loading}
                            onClick={() => submitFeedback("precedent", p.citation, "thumbs_up")}
                            className="flex h-8 w-8 items-center justify-center rounded-lg border border-emerald-500/20 text-muted-foreground hover:bg-emerald-500/10 hover:text-emerald-400 transition-colors disabled:opacity-30"
                            title="Approve precedent"
                          >
                            <ThumbsUp className="h-3.5 w-3.5" />
                          </button>
                          <button
                            disabled={loading}
                            onClick={() => {
                              const notes = prompt("Feedback notes:");
                              if (notes !== null) submitFeedback("precedent", p.citation, "thumbs_down", notes);
                            }}
                            className="flex h-8 w-8 items-center justify-center rounded-lg border border-red-500/20 text-muted-foreground hover:bg-red-500/10 hover:text-red-400 transition-colors disabled:opacity-30"
                            title="Reject precedent"
                          >
                            <ThumbsDown className="h-3.5 w-3.5" />
                          </button>
                        </>
                      );
                    })()}
                    {p.url && (
                      <a
                        href={p.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-500/20 text-cyan-400 hover:bg-cyan-500/10 hover:text-cyan-300 transition-colors"
                        title="View source"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ CONSENSUS DETAILS (collapsible deep-dive) ═══ */}
      {consensus && (
        (consensus.top_defense_arguments?.length > 0 ||
         consensus.top_risk_factors?.length > 0 ||
         consensus.top_recommended_actions?.length > 0) && (
          <div className="rounded-xl border border-border/50 bg-card/50">
            <button
              onClick={() => setSelectedOpinion(selectedOpinion ? null : (consensus.opinions?.[0] ?? null))}
              className="w-full"
            >
              <div className="flex items-center justify-between px-5 py-3 text-left">
                <span className="text-sm font-semibold text-muted-foreground">
                  Consensus Details &amp; Arguments
                </span>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${selectedOpinion ? "rotate-180" : ""}`} />
              </div>
            </button>
            {selectedOpinion && (
              <div className="space-y-4 border-t border-border/30 px-5 py-4">
                {consensus.top_defense_arguments?.length > 0 && (
                  <div>
                    <div className="mb-2 text-sm font-semibold text-emerald-400">Top Defense Arguments</div>
                    <ul className="space-y-1">
                      {consensus.top_defense_arguments.slice(0, 5).map((arg, i) => (
                        <li key={i} className="text-sm text-muted-foreground">&bull; {arg}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {consensus.top_risk_factors?.length > 0 && (
                  <div>
                    <div className="mb-2 text-sm font-semibold text-red-400">Risk Factors</div>
                    <ul className="space-y-1">
                      {consensus.top_risk_factors.slice(0, 5).map((risk, i) => (
                        <li key={i} className="text-sm text-muted-foreground">&bull; {risk}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {consensus.top_recommended_actions?.length > 0 && (
                  <div>
                    <div className="mb-2 text-sm font-semibold text-blue-400">Recommended Actions</div>
                    <ul className="space-y-1">
                      {consensus.top_recommended_actions.slice(0, 5).map((action, i) => (
                        <li key={i} className="text-sm text-muted-foreground">&bull; {action}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      )}

      {/* ═══ UPDATE CASE FILE (collapsible engines panel) ═══ */}
      <div className="rounded-xl border border-border/50 bg-card/30">
        <button
          onClick={() => setEnginesOpen(!enginesOpen)}
          className="flex w-full items-center justify-between px-5 py-4 text-left"
        >
          <div className="flex items-center gap-3">
            <RefreshCw className={`h-4 w-4 text-cyan-400 ${isRunning ? "animate-spin" : ""}`} />
            <div>
              <div className="text-sm font-semibold">
                {consensus ? "Update Case File" : "Initialize Case Analysis"}
              </div>
              <div className="text-xs text-muted-foreground">
                {consensus
                  ? "Re-run E-Discovery or Council deliberation when new evidence is received"
                  : "Run E-Discovery and convene the Council of 9 to begin analysis"}
              </div>
            </div>
          </div>
          <ChevronDown className={`h-5 w-5 text-muted-foreground transition-transform duration-200 ${enginesOpen || !consensus ? "rotate-180" : ""}`} />
        </button>

        {(enginesOpen || !consensus) && (
          <div className="space-y-4 border-t border-border/30 px-5 pb-5 pt-4">
            {/* Case Brief */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-2 flex items-center justify-between">
                <label className="text-sm font-medium text-muted-foreground">Case Brief</label>
                <div className="flex items-center gap-3">
                  {discoveryStats && (
                    <span className="text-xs text-emerald-400">
                      {discoveryStats.total_hits} hits in {discoveryStats.elapsed_seconds}s
                      {discoveryStats.source_stats
                        ? ` (${Object.entries(discoveryStats.source_stats)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(", ")})`
                        : ""}
                    </span>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={runEDiscovery}
                    disabled={discoveryRunning || isRunning}
                    className="border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 hover:text-cyan-300"
                  >
                    {discoveryRunning ? (
                      <>
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        Extracting...
                      </>
                    ) : (
                      <>
                        <Search className="mr-1.5 h-3.5 w-3.5" />
                        E-Discovery Pull
                      </>
                    )}
                  </Button>
                </div>
              </div>
              <Textarea
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                rows={8}
                className="font-mono text-xs"
                disabled={isRunning}
              />
            </div>

            {/* Council Controls */}
            <div className="flex items-center justify-between">
              <div className="text-xs text-muted-foreground">
                {consensus
                  ? "Council data is persisted. Re-deliberation will replace the existing consensus."
                  : "No consensus on file. Convene the Council to generate an analysis."}
              </div>
              <div className="flex gap-2">
                {isRunning ? (
                  <Button variant="destructive" size="sm" onClick={stopDeliberation}>
                    Abort Deliberation
                  </Button>
                ) : (
                  <Button
                    onClick={startDeliberation}
                    disabled={brief.length < 10}
                    size="sm"
                    className="bg-emerald-600 hover:bg-emerald-700"
                  >
                    {consensus ? "Re-Deliberate" : "Convene the Council"}
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ═══ LEADERBOARD (visible during/after deliberation) ═══ */}
      {(activePersonas.length > 0 || opinions.length > 0) && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">Deliberation Leaderboard</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {Array.from({ length: 9 }, (_, i) => i + 1).map((seat) => {
              const opinion = opinions.find((o) => o.seat === seat);
              const active = activePersonas.find((p) => p.seat === seat);
              const style = opinion ? SIGNAL_STYLES[opinion.signal] ?? SIGNAL_STYLES.NEUTRAL : null;

              return (
                <button
                  key={seat}
                  onClick={() => opinion && setSelectedOpinion(
                    selectedOpinion?.seat === opinion.seat ? null : opinion,
                  )}
                  className={`rounded-lg border p-4 text-left transition-all ${
                    opinion
                      ? `border-border/50 ${style?.bg} cursor-pointer hover:border-border`
                      : active
                        ? "animate-pulse border-yellow-500/30 bg-yellow-500/5"
                        : "border-border/20 bg-card/50 opacity-50"
                  } ${selectedOpinion?.seat === seat ? "ring-2 ring-emerald-500" : ""}`}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-lg">{SEAT_ICONS[seat] ?? ""}</span>
                    <span className="text-xs text-muted-foreground">Seat {seat}</span>
                  </div>
                  <div className="text-sm font-semibold">
                    {opinion?.persona ?? active?.name ?? `Seat ${seat}`}
                  </div>
                  {opinion ? (
                    <div className="mt-2 flex items-center justify-between">
                      <span className={`text-xs font-bold ${style?.text}`}>{style?.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {Math.round(opinion.conviction * 100)}% conviction
                      </span>
                    </div>
                  ) : active ? (
                    <div className="mt-2 text-xs text-yellow-400">Analyzing...</div>
                  ) : null}
                  {opinion?.elapsed_seconds ? (
                    <div className="mt-1 text-xs text-muted-foreground">
                      {opinion.elapsed_seconds}s &middot; {opinion.model_used?.split("(")[0]?.trim()}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ═══ VERIFIABLE DELIBERATION LEDGER ═══ */}
      {ledgerHistory.length > 0 && (
        <div className="rounded-xl border border-indigo-500/20 bg-gradient-to-b from-indigo-500/5 to-transparent">
          <div className="flex items-center gap-3 border-b border-indigo-500/20 px-5 py-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/20">
              <Hash className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="flex-1">
              <div className="text-sm font-bold text-indigo-300">Verifiable Deliberation Ledger</div>
              <div className="text-[11px] text-muted-foreground">
                {ledgerHistory.length} cryptographically sealed event{ledgerHistory.length !== 1 ? "s" : ""}
                {lastVaultedId && (
                  <span className="ml-2 text-indigo-400">Latest vault: {lastVaultedId.slice(0, 8)}...</span>
                )}
              </div>
            </div>
            <button
              onClick={fetchLedgerHistory}
              disabled={ledgerLoading}
              className="rounded-lg p-2 text-indigo-400 hover:bg-indigo-500/10 transition-colors disabled:opacity-40"
            >
              <RefreshCw className={`h-4 w-4 ${ledgerLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          <div className="divide-y divide-indigo-500/10">
            {ledgerHistory.map((evt, idx) => {
              const sig = SIGNAL_STYLES[evt.consensus_signal] ?? SIGNAL_STYLES.NEUTRAL;
              const verifyState = ledgerVerify[evt.event_id];
              return (
                <div key={evt.event_id} className="px-5 py-4 hover:bg-indigo-500/[0.03] transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2.5 mb-1.5 flex-wrap">
                        <span className={`text-sm font-bold ${sig.text}`}>{sig.label}</span>
                        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold bg-indigo-500/15 text-indigo-300 uppercase tracking-wider">
                          {evt.trigger_type.replace(/_/g, " ")}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          {Math.round(evt.consensus_conviction * 100)}% conviction
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {new Date(evt.timestamp).toLocaleString("en-US", {
                            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                          })}
                        </span>
                        <span>{evt.vector_count ?? 0} vectors</span>
                        <span>{evt.opinion_count ?? 9} opinions</span>
                        {evt.execution_time_ms && (
                          <span>{(evt.execution_time_ms / 1000).toFixed(1)}s</span>
                        )}
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <code className="text-[10px] text-indigo-400/60 font-mono">
                          SHA-256: {evt.sha256_signature.slice(0, 20)}...
                        </code>
                        <button
                          onClick={() => verifyEvent(evt.event_id)}
                          className="inline-flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 transition-colors"
                        >
                          {verifyState === "secure" ? (
                            <><ShieldCheck className="h-3 w-3 text-emerald-400" /> Verified</>
                          ) : verifyState === "tampered" ? (
                            <><ShieldAlert className="h-3 w-3 text-red-400" /> TAMPERED</>
                          ) : verifyState === "checking" ? (
                            <><Loader2 className="h-3 w-3 animate-spin" /> Checking...</>
                          ) : (
                            <><Shield className="h-3 w-3" /> Verify</>
                          )}
                        </button>
                      </div>
                    </div>
                    {idx < ledgerHistory.length - 1 && (
                      <button
                        onClick={() => loadDelta(ledgerHistory[idx + 1].event_id, evt.event_id)}
                        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-indigo-500/30 bg-indigo-500/10 hover:bg-indigo-500/20 px-3 py-2 text-xs font-semibold text-indigo-300 transition-colors"
                      >
                        <GitCompareArrows className="h-3.5 w-3.5" />
                        Compare
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* ── Delta Analysis Panel ── */}
          {ledgerDelta && (
            <div className="border-t border-indigo-500/20 px-5 py-5">
              <div className="flex items-center justify-between mb-4">
                <h4 className="text-sm font-bold text-indigo-300 flex items-center gap-2">
                  <GitCompareArrows className="h-4 w-4" />
                  Consensus Delta Analysis
                </h4>
                <button
                  onClick={() => setLedgerDelta(null)}
                  className="text-xs text-muted-foreground hover:text-white transition-colors"
                >
                  Dismiss
                </button>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-3 mb-4">
                {/* Consensus Shift */}
                <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-4">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Consensus Shift</div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-bold ${(SIGNAL_STYLES[ledgerDelta.consensus_shift.old_signal] ?? SIGNAL_STYLES.NEUTRAL).text}`}>
                      {(SIGNAL_STYLES[ledgerDelta.consensus_shift.old_signal] ?? SIGNAL_STYLES.NEUTRAL).label}
                    </span>
                    <span className="text-muted-foreground">&#8594;</span>
                    <span className={`text-sm font-bold ${(SIGNAL_STYLES[ledgerDelta.consensus_shift.new_signal] ?? SIGNAL_STYLES.NEUTRAL).text}`}>
                      {(SIGNAL_STYLES[ledgerDelta.consensus_shift.new_signal] ?? SIGNAL_STYLES.NEUTRAL).label}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground flex items-center gap-1">
                    Conviction:
                    {ledgerDelta.consensus_shift.conviction_delta > 0 ? (
                      <span className="text-emerald-400 flex items-center gap-0.5">
                        <ArrowUpRight className="h-3 w-3" />
                        +{(ledgerDelta.consensus_shift.conviction_delta * 100).toFixed(1)}%
                      </span>
                    ) : ledgerDelta.consensus_shift.conviction_delta < 0 ? (
                      <span className="text-red-400 flex items-center gap-0.5">
                        <ArrowDownRight className="h-3 w-3" />
                        {(ledgerDelta.consensus_shift.conviction_delta * 100).toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-muted-foreground flex items-center gap-0.5">
                        <Minus className="h-3 w-3" /> No change
                      </span>
                    )}
                  </div>
                </div>

                {/* Seat Flips */}
                <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-4">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Seat Flips</div>
                  <div className="text-2xl font-bold text-indigo-300">{ledgerDelta.flipped_count}</div>
                  <div className="text-xs text-muted-foreground">of {ledgerDelta.seat_deltas.length} seats changed signal</div>
                </div>

                {/* Evidence Changes */}
                <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-4">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Evidence Context</div>
                  <div className="flex items-center gap-3">
                    <span className="text-emerald-400 text-sm font-bold">+{ledgerDelta.context_delta.added_vectors}</span>
                    <span className="text-red-400 text-sm font-bold">-{ledgerDelta.context_delta.removed_vectors}</span>
                    <span className="text-muted-foreground text-sm">{ledgerDelta.context_delta.shared_vectors} shared</span>
                  </div>
                </div>
              </div>

              {/* Flipped Seats Detail */}
              {ledgerDelta.seat_deltas.filter((s) => s.flipped).length > 0 && (
                <div className="rounded-lg border border-indigo-500/10 bg-indigo-500/[0.02] p-4 mb-4">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">Flipped Seats</div>
                  <div className="space-y-2">
                    {ledgerDelta.seat_deltas.filter((s) => s.flipped).map((sd) => {
                      const oldStyle = SIGNAL_STYLES[sd.old_signal] ?? SIGNAL_STYLES.NEUTRAL;
                      const newStyle = SIGNAL_STYLES[sd.new_signal] ?? SIGNAL_STYLES.NEUTRAL;
                      return (
                        <div key={sd.seat} className="flex items-center gap-3 text-sm">
                          <span className="text-muted-foreground w-28 shrink-0">
                            {SEAT_ICONS[sd.seat] ?? ""} Seat {sd.seat}
                          </span>
                          <span className={`font-semibold ${oldStyle.text}`}>{oldStyle.label}</span>
                          <span className="text-muted-foreground">&#8594;</span>
                          <span className={`font-semibold ${newStyle.text}`}>{newStyle.label}</span>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {sd.conviction_delta > 0 ? "+" : ""}{(sd.conviction_delta * 100).toFixed(1)}% conviction
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* New Evidence Attribution */}
              {ledgerDelta.context_delta.added_evidence.length > 0 && (
                <div className="rounded-lg border border-emerald-500/10 bg-emerald-500/[0.02] p-4">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">New Evidence Injected</div>
                  <div className="space-y-2">
                    {ledgerDelta.context_delta.added_evidence.map((ev) => (
                      <div key={ev.vector_id} className="text-xs">
                        <code className="text-emerald-400 font-mono">{ev.vector_id}</code>
                        <p className="mt-0.5 text-muted-foreground leading-relaxed">{ev.chunk_preview}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ═══ AGENTIC ZERO-TOUCH INGEST ═══ */}
      <div className="rounded-xl border border-teal-500/20 bg-gradient-to-b from-teal-500/5 to-transparent">
        <div className="flex items-center gap-3 border-b border-teal-500/20 px-5 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-500/20">
            <Upload className="h-4 w-4 text-teal-400" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-bold text-teal-300">Agentic Zero-Touch Ingest</div>
            <div className="text-[11px] text-muted-foreground">
              Client-side SHA-256 hashing with server verification
              {ingestStatus === "success" && (
                <span className="ml-2 text-emerald-400 font-semibold">CRYPTOGRAPHIC LOCK SECURED</span>
              )}
            </div>
          </div>
        </div>

        <div className="px-5 py-4">
          <div
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (e.dataTransfer.files?.[0]) processIngest(e.dataTransfer.files[0]);
            }}
            onClick={() => ingestFileRef.current?.click()}
            className={`rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
              ingestStatus === "success"
                ? "border-emerald-500/40 bg-emerald-500/5"
                : ingestStatus === "error"
                  ? "border-red-500/40 bg-red-500/5"
                  : "border-teal-500/20 bg-teal-500/[0.02] hover:border-teal-500/40 hover:bg-teal-500/5"
            }`}
          >
            <input
              ref={ingestFileRef}
              type="file"
              className="hidden"
              onChange={(e) => { if (e.target.files?.[0]) processIngest(e.target.files[0]); e.target.value = ""; }}
            />

            {ingestStatus === "idle" && (
              <div className="flex flex-col items-center gap-2">
                <Upload className="h-6 w-6 text-teal-400/50" />
                <p className="text-sm text-muted-foreground">
                  Drag and drop evidence files here
                </p>
                <p className="text-[10px] text-muted-foreground/50">
                  SHA-256 hashed on your machine before upload — chain of custody enforced
                </p>
              </div>
            )}

            {ingestStatus === "hashing" && (
              <div className="flex items-center justify-center gap-2">
                <Lock className="h-4 w-4 text-amber-400 animate-pulse" />
                <span className="text-sm text-amber-400 animate-pulse">Computing edge SHA-256 hash...</span>
              </div>
            )}

            {ingestStatus === "uploading" && (
              <div className="flex items-center justify-center gap-2">
                <Loader2 className="h-4 w-4 text-teal-400 animate-spin" />
                <span className="text-sm text-teal-400">Verifying cryptography and routing to NAS...</span>
              </div>
            )}

            {ingestStatus === "success" && ingestResult && (
              <div className="text-left space-y-1.5">
                <div className="flex items-center gap-2 text-sm font-semibold text-emerald-400">
                  <ShieldCheck className="h-4 w-4" />
                  Auto-Routed to: {ingestResult.case_slug}
                </div>
                <div className="text-[11px] text-muted-foreground font-mono truncate">
                  NAS: {ingestResult.nas_path}
                </div>
                <div className="text-[11px] text-muted-foreground font-mono">
                  SHA-256: {ingestResult.sha256_signature.slice(0, 24)}...
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Classification: {ingestResult.extracted_entities.type}
                </div>
              </div>
            )}

            {ingestStatus === "error" && (
              <div className="flex flex-col items-center gap-2">
                <ShieldAlert className="h-5 w-5 text-red-400" />
                <p className="text-sm text-red-400">{ingestError ?? "Ingest rejected — chain of custody failure"}</p>
                <button
                  onClick={(e) => { e.stopPropagation(); setIngestStatus("idle"); setIngestError(null); }}
                  className="text-xs text-muted-foreground hover:text-white transition-colors"
                >
                  Try again
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ═══ SELECTED OPINION DETAIL ═══ */}
      {selectedOpinion?.reasoning && (
        <div className="rounded-lg border border-border bg-card p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold">
                {SEAT_ICONS[selectedOpinion.seat]} {selectedOpinion.persona}
              </h3>
              <span className="text-xs text-muted-foreground">
                Seat {selectedOpinion.seat} &middot; {selectedOpinion.model_used} &middot;{" "}
                {selectedOpinion.elapsed_seconds}s
              </span>
            </div>
            <div
              className={`rounded-full px-3 py-1 text-sm font-bold ${
                SIGNAL_STYLES[selectedOpinion.signal]?.bg ?? ""
              } ${SIGNAL_STYLES[selectedOpinion.signal]?.text ?? ""}`}
            >
              {SIGNAL_STYLES[selectedOpinion.signal]?.label ?? selectedOpinion.signal}
              {" "}
              ({Math.round(selectedOpinion.conviction * 100)}%)
            </div>
          </div>

          <div className="mb-4">
            <div className="mb-1 text-sm font-semibold">Analysis</div>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
              {selectedOpinion.reasoning}
            </p>
          </div>

          {selectedOpinion.defense_arguments?.length > 0 && (
            <div className="mb-4">
              <div className="mb-1 text-sm font-semibold text-emerald-400">Defense Arguments</div>
              <ul className="space-y-1">
                {selectedOpinion.defense_arguments.map((arg, i) => (
                  <li key={i} className="text-sm text-muted-foreground">&bull; {arg}</li>
                ))}
              </ul>
            </div>
          )}

          {selectedOpinion.risk_factors?.length > 0 && (
            <div className="mb-4">
              <div className="mb-1 text-sm font-semibold text-red-400">Risk Factors</div>
              <ul className="space-y-1">
                {selectedOpinion.risk_factors.map((risk, i) => (
                  <li key={i} className="text-sm text-muted-foreground">&bull; {risk}</li>
                ))}
              </ul>
            </div>
          )}

          {selectedOpinion.recommended_actions?.length > 0 && (
            <div>
              <div className="mb-1 text-sm font-semibold text-blue-400">Recommended Actions</div>
              <ul className="space-y-1">
                {selectedOpinion.recommended_actions.map((action, i) => (
                  <li key={i} className="text-sm text-muted-foreground">&bull; {action}</li>
                ))}
              </ul>
            </div>
          )}

          <Button
            variant="ghost"
            size="sm"
            className="mt-4"
            onClick={() => setSelectedOpinion(null)}
          >
            Close Detail
          </Button>
        </div>
      )}

      {/* ═══ FIRST-RUN PROMPT (no consensus yet, engines not open) ═══ */}
      {!consensus && !enginesOpen && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/50 py-16">
          <Shield className="mb-4 h-12 w-12 text-muted-foreground/30" />
          <div className="text-lg font-semibold text-muted-foreground">No Analysis On File</div>
          <div className="mt-1 text-sm text-muted-foreground/60">
            Open the panel above to run E-Discovery and convene the Council of 9.
          </div>
        </div>
      )}

      {/* ═══ OUTSIDE COUNSEL MODAL (Multi-Phase Headhunter) ═══ */}
      {counselModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="relative mx-4 flex max-h-[90vh] w-full max-w-4xl flex-col rounded-2xl border border-violet-500/30 bg-[#0a0a0a] shadow-2xl shadow-violet-500/10">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-violet-500/20 px-6 py-4">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/20">
                  <Briefcase className="h-4 w-4 text-violet-400" />
                </div>
                <div>
                  <div className="text-sm font-bold text-violet-300">
                    Outside Counsel — Legal Headhunter
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {counselPhase === "hunt-config" && "Configure search parameters"}
                    {counselPhase === "hunting" && "Searching dockets & legal journalism..."}
                    {counselPhase === "hunt-results" && `${huntAttorneys.length} attorneys found via ${huntModel}`}
                    {counselPhase === "drafting" && "Generating RFP draft..."}
                    {counselPhase === "draft-ready" && `Draft ready — ${counselModel}`}
                    {counselPhase === "sent" && "Dispatch staged"}
                  </div>
                </div>
              </div>
              <button
                onClick={() => setCounselModalOpen(false)}
                className="rounded-lg p-2 text-muted-foreground hover:bg-white/5 hover:text-white transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
              {/* ── Phase: Hunt Config ── */}
              {counselPhase === "hunt-config" && (
                <>
                  <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4">
                    <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-violet-400">
                      Search Parameters (AI-assessed defaults — editable)
                    </div>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                          Jurisdiction
                        </label>
                        <input
                          type="text"
                          value={counselJurisdiction}
                          onChange={(e) => setCounselJurisdiction(e.target.value)}
                          placeholder="e.g., Georgia, Florida Federal Court"
                          className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                        />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                          Required Specialty
                        </label>
                        <input
                          type="text"
                          value={counselSpecialty}
                          onChange={(e) => setCounselSpecialty(e.target.value)}
                          placeholder="e.g., Breach of Contract Defense"
                          className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                        />
                      </div>
                    </div>
                  </div>
                  <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
                    <div className="mb-2 text-xs font-semibold text-muted-foreground">Search Targets</div>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      <div className="flex items-center gap-2 rounded-md bg-blue-500/10 px-3 py-2">
                        <Search className="h-3.5 w-3.5 text-blue-400" />
                        <span className="text-xs text-blue-300">Dockets &amp; Caselaw</span>
                        <span className="ml-auto text-[10px] text-muted-foreground">justia.com &bull; caselaw.findlaw.com</span>
                      </div>
                      <div className="flex items-center gap-2 rounded-md bg-amber-500/10 px-3 py-2">
                        <FileText className="h-3.5 w-3.5 text-amber-400" />
                        <span className="text-xs text-amber-300">Legal Journalism</span>
                        <span className="ml-auto text-[10px] text-muted-foreground">law.com &bull; law360 &bull; reuters/legal</span>
                      </div>
                    </div>
                  </div>
                </>
              )}

              {/* ── Phase: Hunting (spinner) ── */}
              {counselPhase === "hunting" && (
                <div className="flex flex-col items-center justify-center gap-4 py-16">
                  <div className="relative">
                    <Loader2 className="h-12 w-12 animate-spin text-violet-400" />
                    <Search className="absolute left-1/2 top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 text-violet-300" />
                  </div>
                  <div className="text-sm font-medium text-violet-300">Hunting across dockets &amp; legal news...</div>
                  <div className="max-w-sm text-center text-xs text-muted-foreground">
                    Generating search queries, scraping court records and legal journalism, then evaluating attorney track records.
                  </div>
                </div>
              )}

              {/* ── Phase: Hunt Results ── */}
              {counselPhase === "hunt-results" && (
                <>
                  {huntQueries.length > 0 && (
                    <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Search Queries Used ({huntSources} sources)
                      </div>
                      <div className="space-y-1">
                        {huntQueries.map((q, i) => (
                          <div key={i} className="text-xs text-muted-foreground font-mono truncate">
                            {i + 1}. {q}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {huntAttorneys.length === 0 ? (
                    <div className="flex flex-col items-center justify-center gap-3 py-12">
                      <Search className="h-10 w-10 text-muted-foreground/30" />
                      <div className="text-sm text-muted-foreground">No attorneys found. Try broadening jurisdiction or specialty.</div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setCounselPhase("hunt-config")}
                        className="border-violet-500/30 text-violet-400"
                      >
                        Modify Search
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                        {huntAttorneys.length} Attorney{huntAttorneys.length !== 1 ? "s" : ""} Identified
                      </div>
                      <div className="overflow-x-auto rounded-lg border border-white/10">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-white/10 bg-white/[0.03] text-xs text-muted-foreground">
                              <th className="px-4 py-2.5 text-left font-semibold">Attorney</th>
                              <th className="px-4 py-2.5 text-left font-semibold">Firm</th>
                              <th className="px-4 py-2.5 text-left font-semibold">Contact</th>
                              <th className="px-4 py-2.5 text-left font-semibold">Match</th>
                              <th className="px-4 py-2.5 text-left font-semibold">Reason</th>
                              <th className="px-4 py-2.5 text-center font-semibold">Feedback</th>
                            </tr>
                          </thead>
                          <tbody>
                            {huntAttorneys.map((att, i) => (
                              <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02]">
                                <td className="px-4 py-3 font-medium text-white">{att.attorney_name || "—"}</td>
                                <td className="px-4 py-3 text-muted-foreground">{att.firm || "—"}</td>
                                <td className="px-4 py-3">
                                  <div className="text-xs text-violet-300">{att.email || "—"}</div>
                                  {att.phone && !att.phone.toLowerCase().includes("not found") && (
                                    <div className="text-xs text-muted-foreground">{att.phone}</div>
                                  )}
                                </td>
                                <td className="px-4 py-3">
                                  <div className="flex gap-1.5">
                                    {att.jurisdiction_match && (
                                      <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-bold text-emerald-400">JUR</span>
                                    )}
                                    {att.specialty_match && (
                                      <span className="rounded bg-blue-500/20 px-1.5 py-0.5 text-[10px] font-bold text-blue-400">SPEC</span>
                                    )}
                                  </div>
                                </td>
                                <td className="px-4 py-3 text-xs text-muted-foreground max-w-[300px]">{att.reason || "—"}</td>
                                <td className="px-4 py-3">
                                  {(() => {
                                    const key = `attorney:${att.attorney_name}`;
                                    const sent = feedbackSent[key];
                                    const loading = feedbackLoading === key;
                                    if (sent) {
                                      return (
                                        <div className="flex justify-center">
                                          {sent === "thumbs_up" ? (
                                            <ThumbsUp className="h-4 w-4 text-emerald-400" />
                                          ) : (
                                            <ThumbsDown className="h-4 w-4 text-red-400" />
                                          )}
                                        </div>
                                      );
                                    }
                                    return (
                                      <div className="flex justify-center gap-1.5">
                                        <button
                                          disabled={loading}
                                          onClick={() => submitFeedback("attorney", att.attorney_name, "thumbs_up")}
                                          className="rounded p-1 transition-colors hover:bg-emerald-500/20 disabled:opacity-30"
                                          title="Approve this attorney"
                                        >
                                          <ThumbsUp className="h-3.5 w-3.5 text-muted-foreground hover:text-emerald-400" />
                                        </button>
                                        <button
                                          disabled={loading}
                                          onClick={() => {
                                            const notes = prompt("Feedback notes (e.g., 'Firm is too big'):");
                                            if (notes !== null) submitFeedback("attorney", att.attorney_name, "thumbs_down", notes);
                                          }}
                                          className="rounded p-1 transition-colors hover:bg-red-500/20 disabled:opacity-30"
                                          title="Reject this attorney"
                                        >
                                          <ThumbsDown className="h-3.5 w-3.5 text-muted-foreground hover:text-red-400" />
                                        </button>
                                      </div>
                                    );
                                  })()}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {huntAttorneys.length > 0 && (
                    <div>
                      <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-violet-400">
                        Recipient Email(s) — auto-populated from results
                      </label>
                      <input
                        type="text"
                        value={counselEmails}
                        onChange={(e) => setCounselEmails(e.target.value)}
                        placeholder="attorney1@firm.com, attorney2@firm.com"
                        className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                      />
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        Comma-separated. Edit as needed before generating the RFP draft.
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* ── Phase: Drafting (spinner) ── */}
              {counselPhase === "drafting" && (
                <div className="flex flex-col items-center justify-center gap-3 py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-violet-400" />
                  <div className="text-sm text-muted-foreground">
                    Generating RFP draft via God Head...
                  </div>
                </div>
              )}

              {/* ── Phase: Draft Ready ── */}
              {counselPhase === "draft-ready" && (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-violet-400">
                      Subject
                    </label>
                    <input
                      type="text"
                      value={counselSubject}
                      onChange={(e) => setCounselSubject(e.target.value)}
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-violet-400">
                      Email Body
                    </label>
                    <textarea
                      value={counselBody}
                      onChange={(e) => setCounselBody(e.target.value)}
                      rows={16}
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-3 font-mono text-sm leading-relaxed text-white/90 placeholder-white/30 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-violet-400">
                      Recipient Email(s)
                    </label>
                    <input
                      type="text"
                      placeholder="attorney1@firm.com, attorney2@firm.com"
                      value={counselEmails}
                      onChange={(e) => setCounselEmails(e.target.value)}
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                    />
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      Comma-separated. Dispatch is currently in mock mode (console only).
                    </div>
                  </div>
                </>
              )}

              {/* ── Phase: Sent ── */}
              {counselPhase === "sent" && (
                <div className="flex flex-col items-center justify-center gap-3 py-16">
                  <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/20">
                    <CheckCircle2 className="h-8 w-8 text-emerald-400" />
                  </div>
                  <div className="text-lg font-bold text-emerald-300">
                    Dispatch Staged Successfully
                  </div>
                  <div className="max-w-md text-center text-sm text-muted-foreground">
                    Payload logged to console. Wire AWS SES or SendGrid in the next phase to
                    enable live dispatch.
                  </div>
                  <Button
                    onClick={() => setCounselModalOpen(false)}
                    variant="outline"
                    className="mt-4 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
                  >
                    Close
                  </Button>
                </div>
              )}
            </div>

            {/* ── Footer Actions ── */}
            {counselPhase === "hunt-config" && (
              <div className="flex items-center justify-end gap-3 border-t border-violet-500/20 px-6 py-4">
                <Button
                  variant="ghost"
                  onClick={() => setCounselModalOpen(false)}
                  className="text-muted-foreground"
                >
                  Cancel
                </Button>
                <Button
                  onClick={commenceHunt}
                  disabled={!counselJurisdiction.trim() || !counselSpecialty.trim()}
                  className="bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 text-white font-bold shadow-lg shadow-violet-500/20 disabled:opacity-40"
                >
                  <Search className="mr-2 h-4 w-4" />
                  Commence Hunt
                </Button>
              </div>
            )}

            {counselPhase === "hunt-results" && (
              <div className="flex items-center justify-between border-t border-violet-500/20 px-6 py-4">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setCounselPhase("hunt-config")}
                  className="text-muted-foreground"
                >
                  Modify Search
                </Button>
                <div className="flex gap-3">
                  <Button
                    variant="ghost"
                    onClick={() => setCounselModalOpen(false)}
                    className="text-muted-foreground"
                  >
                    Close
                  </Button>
                  {huntAttorneys.length > 0 && (
                    <Button
                      onClick={generateDraftFromHunt}
                      className="bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 text-white font-bold shadow-lg shadow-violet-500/20"
                    >
                      <Mail className="mr-2 h-4 w-4" />
                      Generate RFP Draft
                    </Button>
                  )}
                </div>
              </div>
            )}

            {counselPhase === "draft-ready" && (
              <div className="flex items-center justify-end gap-3 border-t border-violet-500/20 px-6 py-4">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setCounselPhase("hunt-results")}
                  className="text-muted-foreground"
                >
                  Back to Results
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => setCounselModalOpen(false)}
                  className="text-muted-foreground"
                >
                  Cancel
                </Button>
                <Button
                  onClick={dispatchCounsel}
                  disabled={!counselBody.trim() || !counselEmails.trim()}
                  className="bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 text-white font-bold shadow-lg shadow-violet-500/20 disabled:opacity-40"
                >
                  <Send className="mr-2 h-4 w-4" />
                  Send Dispatch
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
