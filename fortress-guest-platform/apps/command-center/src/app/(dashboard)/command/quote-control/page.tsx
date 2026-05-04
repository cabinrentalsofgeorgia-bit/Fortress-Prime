"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CalendarCheck,
  CheckCircle2,
  ClipboardCheck,
  CreditCard,
  FlaskConical,
  History,
  Loader2,
  LockKeyhole,
  PauseCircle,
  RefreshCw,
  Send,
  ShieldCheck,
  Siren,
  StickyNote,
  Timer,
  UserCheck,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import {
  useQuoteBookingControlAction,
  useQuoteBookingControlTower,
  type QuoteBookingRecord,
  type QuoteBookingSafeguard,
} from "@/lib/hooks";
import { toast } from "sonner";

type KindFilter = "all" | QuoteBookingRecord["kind"];
type StopFilter = "all" | QuoteBookingRecord["stop_level"];
type SafeAction = "claim" | "mark_reviewed" | "escalate" | "dismiss" | "note";
type ActionTarget = {
  record: QuoteBookingRecord;
  action: SafeAction;
};
type CleanupAction = "expire_hold" | "cancel_proof";
type CleanupTarget = {
  record: QuoteBookingRecord;
  action: CleanupAction;
};
type ExceptionSeverity = "stop" | "attention" | "watch";
type ExceptionAction =
  | "approve_payment"
  | "send_confirmation"
  | "close_ops"
  | "expire_hold"
  | "cancel_proof"
  | "open_audit"
  | "inspect";
type ActivationExceptionItem = {
  id: string;
  record: QuoteBookingRecord;
  severity: ExceptionSeverity;
  label: string;
  detail: string;
  ageAt: string | null;
  primaryAction: ExceptionAction;
  secondaryAction?: ExceptionAction;
};

type ActivationTimelineEvent = {
  id: string;
  at: string | null;
  stage: string;
  label: string;
  action: string;
  outcome: string | null;
  actor_email: string | null;
  resource_kind: string | null;
  resource_item_id: string | null;
  detail: string | null;
  note: string | null;
  activation_state: string | null;
  payment_link_id: string | null;
  safeguards: string[];
  references: Record<string, string | string[]>;
  audit_hash: string | null;
};

type QuoteBookingSendResponse = {
  ok: boolean;
  quote_id: string;
  guest_email: string;
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingHoldResponse = {
  ok: boolean;
  quote_id: string;
  hold_id: string;
  expires_at: string;
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingReservationResponse = {
  ok: boolean;
  quote_id: string;
  hold_id: string;
  reservation_id: string;
  confirmation_code: string;
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingPaymentLinkResponse = {
  ok: boolean;
  reservation_id: string;
  confirmation_code: string;
  guest_email: string;
  payment_link_id: string;
  audit_id: string | null;
  audit_hash: string | null;
  stripe_mode: "test" | "live";
  message: string;
};

type QuoteBookingPaymentApprovalResponse = {
  ok: boolean;
  reservation_id: string;
  confirmation_code: string;
  status: string;
  paid_amount: number | null;
  balance_due: number | null;
  activation_state: string | null;
  guest_confirmation_draft_id: string | null;
  work_order_ids: string[];
  housekeeping_task_id: string | null;
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingConfirmationSendResponse = {
  ok: boolean;
  reservation_id: string;
  confirmation_code: string;
  activation_state: string;
  draft_status: string;
  sent_at: string | null;
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingOpsCloseResponse = {
  ok: boolean;
  reservation_id: string;
  confirmation_code: string;
  activation_state: string;
  ops_handoff_status: string;
  closed_at: string | null;
  completed_work_order_ids: string[];
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingCleanupResponse = {
  ok: boolean;
  kind: "hold" | "reservation";
  id: string;
  status: string;
  audit_id: string | null;
  audit_hash: string | null;
  message: string;
};

type QuoteBookingProofLaneResponse = {
  ok: boolean;
  quote: QuoteBookingRecord;
  audit_id: string | null;
  audit_hash: string | null;
  stripe_mode: "test";
  message: string;
};

const KIND_FILTERS: { id: KindFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "quote", label: "Quotes" },
  { id: "hold", label: "Holds" },
  { id: "reservation", label: "Reservations" },
  { id: "parity", label: "Parity" },
];

const STOP_FILTERS: { id: StopFilter; label: string }[] = [
  { id: "all", label: "All Gates" },
  { id: "stop", label: "Stops" },
  { id: "inspect", label: "Inspect" },
  { id: "clear", label: "Clear" },
];

const KIND_ICONS = {
  quote: ClipboardCheck,
  hold: Timer,
  reservation: CheckCircle2,
  parity: ShieldCheck,
} satisfies Record<QuoteBookingRecord["kind"], typeof ClipboardCheck>;

function formatMoney(value: number | null | undefined): string {
  if (value == null) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  return parsed.toLocaleDateString();
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatAge(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return formatTimestamp(value);
  const diffMs = Math.max(0, Date.now() - parsed.getTime());
  const diffMinutes = Math.floor(diffMs / 60_000);
  if (diffMinutes < 60) return `${Math.max(1, diffMinutes)}m`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 48) return `${diffHours}h`;
  return `${Math.floor(diffHours / 24)}d`;
}

function metric(summary: Record<string, number> | undefined, key: string): number {
  return summary?.[key] ?? 0;
}

function stopTone(level: QuoteBookingRecord["stop_level"]): string {
  switch (level) {
    case "clear":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "inspect":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "stop":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
  }
}

function metadataString(record: QuoteBookingRecord, key: string): string | null {
  const value = record.metadata?.[key];
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function metadataNumber(record: QuoteBookingRecord, key: string): number | null {
  const value = record.metadata?.[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function metadataStrings(record: QuoteBookingRecord, key: string): string[] {
  const value = record.metadata?.[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function auditReferences(value: unknown): Record<string, string | string[]> {
  const references: Record<string, string | string[]> = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return references;

  Object.entries(value as Record<string, unknown>).forEach(([key, refValue]) => {
    if (typeof refValue === "string" && refValue.trim()) {
      references[key] = refValue;
      return;
    }
    if (Array.isArray(refValue)) {
      const refs = refValue.filter(
        (ref): ref is string => typeof ref === "string" && ref.trim().length > 0,
      );
      if (refs.length > 0) references[key] = refs;
    }
  });

  return references;
}

function metadataTimeline(record: QuoteBookingRecord, key: string): ActivationTimelineEvent[] {
  const value = record.metadata?.[key];
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item, index) => ({
      id: typeof item.id === "string" && item.id.trim() ? item.id : `${key}-${index}`,
      at: typeof item.at === "string" && item.at.trim() ? item.at : null,
      stage: typeof item.stage === "string" && item.stage.trim() ? item.stage : "audit",
      label: typeof item.label === "string" && item.label.trim() ? item.label : "Audit Event",
      action: typeof item.action === "string" && item.action.trim() ? item.action : "audit_event",
      outcome: typeof item.outcome === "string" && item.outcome.trim() ? item.outcome : null,
      actor_email:
        typeof item.actor_email === "string" && item.actor_email.trim() ? item.actor_email : null,
      resource_kind:
        typeof item.resource_kind === "string" && item.resource_kind.trim() ? item.resource_kind : null,
      resource_item_id:
        typeof item.resource_item_id === "string" && item.resource_item_id.trim()
          ? item.resource_item_id
          : null,
      detail: typeof item.detail === "string" && item.detail.trim() ? item.detail : null,
      note: typeof item.note === "string" && item.note.trim() ? item.note : null,
      activation_state:
        typeof item.activation_state === "string" && item.activation_state.trim()
          ? item.activation_state
          : null,
      payment_link_id:
        typeof item.payment_link_id === "string" && item.payment_link_id.trim()
          ? item.payment_link_id
          : null,
      safeguards: Array.isArray(item.safeguards)
        ? item.safeguards.filter((safe): safe is string => typeof safe === "string" && safe.trim().length > 0)
        : [],
      references: auditReferences(item.references),
      audit_hash: typeof item.audit_hash === "string" && item.audit_hash.trim() ? item.audit_hash : null,
    }));
}

function canSendGuestQuote(record: QuoteBookingRecord): boolean {
  return (
    record.kind === "quote" &&
    metadataString(record, "readiness_state") === "ready" &&
    record.metadata?.guest_quote_sent !== true
  );
}

function canCreateLocalHold(record: QuoteBookingRecord): boolean {
  return (
    record.kind === "quote" &&
    metadataString(record, "readiness_state") === "ready" &&
    record.metadata?.guest_quote_sent === true
  );
}

function canConvertLocalReservation(record: QuoteBookingRecord): boolean {
  return record.kind === "quote" && metadataString(record, "readiness_state") === "local_hold_created";
}

function canSendPaymentLink(record: QuoteBookingRecord): boolean {
  const balanceDue = Number(record.metadata?.balance_due ?? record.total_amount ?? 0);
  return (
    record.kind === "reservation" &&
    record.status === "pending_payment" &&
    balanceDue > 0 &&
    record.metadata?.payment_link_sent !== true
  );
}

function canApprovePayment(record: QuoteBookingRecord): boolean {
  return (
    record.kind === "reservation" &&
    metadataString(record, "payment_reconciliation_state") === "stripe_paid_pending_staff_approval" &&
    record.metadata?.local_payment_posted !== true
  );
}

function canSendGuestConfirmation(record: QuoteBookingRecord): boolean {
  const activationState = metadataString(record, "activation_state");
  const draftStatus = metadataString(record, "guest_confirmation_draft_status");
  return (
    record.kind === "reservation" &&
    ["activated_pending_staff_confirmation_review", "ops_closed_pending_confirmation"].includes(activationState || "") &&
    ["pending_staff_review", "send_failed"].includes(draftStatus || "")
  );
}

function canCloseOpsHandoff(record: QuoteBookingRecord): boolean {
  const activationState = metadataString(record, "activation_state");
  return (
    record.kind === "reservation" &&
    ["activated_pending_staff_confirmation_review", "confirmation_sent_ops_open"].includes(activationState || "") &&
    metadataString(record, "ops_handoff_status") === "open"
  );
}

function canExpireLocalHold(record: QuoteBookingRecord): boolean {
  return record.kind === "hold" && record.metadata?.cleanup_eligible === true;
}

function canCancelProofReservation(record: QuoteBookingRecord): boolean {
  return record.kind === "reservation" && record.metadata?.cleanup_eligible === true;
}

function hasTimelineAction(record: QuoteBookingRecord, action: string): boolean {
  return metadataTimeline(record, "activation_timeline").some((event) => event.action === action);
}

function pushException(
  items: ActivationExceptionItem[],
  item: ActivationExceptionItem,
): void {
  if (items.some((existing) => existing.id === item.id)) return;
  items.push(item);
}

function buildActivationExceptions(records: QuoteBookingRecord[]): ActivationExceptionItem[] {
  const items: ActivationExceptionItem[] = [];

  records.forEach((record) => {
    if (record.kind === "hold" && canExpireLocalHold(record)) {
      pushException(items, {
        id: `hold-cleanup-${record.id}`,
        record,
        severity: "attention",
        label: "Expired Hold Cleanup",
        detail: metadataString(record, "cleanup_reason") || "Expired local hold can be cleared from availability.",
        ageAt: metadataString(record, "expires_at") || record.updated_at || record.created_at,
        primaryAction: "expire_hold",
        secondaryAction: "inspect",
      });
      return;
    }

    if (record.kind !== "reservation") return;

    const reconciliationState = metadataString(record, "payment_reconciliation_state");
    const activationState = metadataString(record, "activation_state");
    const draftStatus = metadataString(record, "guest_confirmation_draft_status");
    const opsStatus = metadataString(record, "ops_handoff_status");
    const timeline = metadataTimeline(record, "activation_timeline");

    if (canApprovePayment(record)) {
      pushException(items, {
        id: `payment-proof-${record.id}`,
        record,
        severity: "attention",
        label: "Payment Proof Approval",
        detail:
          metadataString(record, "payment_reconciliation_detail") ||
          "Stripe payment signal is waiting for staff approval before local posting.",
        ageAt: metadataString(record, "payment_reconciled_at") || record.updated_at || record.created_at,
        primaryAction: "approve_payment",
        secondaryAction: "open_audit",
      });
    }

    if (reconciliationState?.endsWith("_needs_staff_review")) {
      pushException(items, {
        id: `payment-stop-${record.id}`,
        record,
        severity: "stop",
        label: reconciliationLabel(reconciliationState) || "Payment Review Stop",
        detail:
          metadataString(record, "payment_reconciliation_detail") ||
          "Payment reconciliation needs staff inspection before activation can continue.",
        ageAt: metadataString(record, "payment_reconciled_at") || record.updated_at || record.created_at,
        primaryAction: "open_audit",
        secondaryAction: "inspect",
      });
    }

    if (draftStatus === "send_failed") {
      pushException(items, {
        id: `confirmation-failed-${record.id}`,
        record,
        severity: "stop",
        label: "Confirmation Send Failed",
        detail: "Guest confirmation send failed and needs staff retry or inspection.",
        ageAt: record.updated_at || record.created_at,
        primaryAction: "send_confirmation",
        secondaryAction: "open_audit",
      });
    } else if (canSendGuestConfirmation(record)) {
      pushException(items, {
        id: `confirmation-pending-${record.id}`,
        record,
        severity: "attention",
        label: "Confirmation Approval",
        detail: "Guest confirmation draft is waiting for staff approval and send.",
        ageAt: metadataString(record, "activation_created_at") || record.updated_at || record.created_at,
        primaryAction: "send_confirmation",
        secondaryAction: "open_audit",
      });
    }

    if (canCloseOpsHandoff(record)) {
      pushException(items, {
        id: `ops-open-${record.id}`,
        record,
        severity: activationState === "confirmation_sent_ops_open" ? "attention" : "watch",
        label: "Ops Handoff Open",
        detail: "Internal activation work orders still need closure; housekeeping remains separately scheduled.",
        ageAt: metadataString(record, "activation_created_at") || record.updated_at || record.created_at,
        primaryAction: "close_ops",
        secondaryAction: "open_audit",
      });
    }

    if (canCancelProofReservation(record)) {
      pushException(items, {
        id: `proof-cleanup-${record.id}`,
        record,
        severity: "attention",
        label: "Proof Reservation Cleanup",
        detail: metadataString(record, "cleanup_reason") || "Proof-lane reservation can be cancelled to release availability.",
        ageAt: record.updated_at || record.created_at,
        primaryAction: "cancel_proof",
        secondaryAction: "open_audit",
      });
    }

    if (activationState && timeline.length === 0) {
      pushException(items, {
        id: `missing-audit-${record.id}`,
        record,
        severity: "stop",
        label: "Missing Audit Evidence",
        detail: "Activation state exists but no activation timeline is available for staff review.",
        ageAt: record.updated_at || record.created_at,
        primaryAction: "open_audit",
        secondaryAction: "inspect",
      });
    }

    if (
      activationState === "completed" &&
      timeline.length > 0 &&
      (!hasTimelineAction(record, "send_guest_confirmation") || !hasTimelineAction(record, "close_ops_handoff"))
    ) {
      pushException(items, {
        id: `incomplete-audit-${record.id}`,
        record,
        severity: "stop",
        label: "Incomplete Completion Audit",
        detail: "Activation is marked complete but expected confirmation or ops audit evidence is missing.",
        ageAt: record.updated_at || record.created_at,
        primaryAction: "open_audit",
        secondaryAction: "inspect",
      });
    }

    if (opsStatus === "closed" && draftStatus !== "sent" && activationState === "ops_closed_pending_confirmation") {
      pushException(items, {
        id: `ops-closed-confirmation-pending-${record.id}`,
        record,
        severity: "attention",
        label: "Ops Closed, Confirmation Pending",
        detail: "Ops handoff is closed; the guest confirmation still needs staff send approval.",
        ageAt: metadataString(record, "ops_handoff_closed_at") || record.updated_at || record.created_at,
        primaryAction: "send_confirmation",
        secondaryAction: "open_audit",
      });
    }
  });

  const severityRank: Record<ExceptionSeverity, number> = { stop: 0, attention: 1, watch: 2 };
  return items.sort((left, right) => {
    const severityDelta = severityRank[left.severity] - severityRank[right.severity];
    if (severityDelta !== 0) return severityDelta;
    return new Date(left.ageAt || 0).getTime() - new Date(right.ageAt || 0).getTime();
  });
}

function cleanupLabel(action: CleanupAction): string {
  switch (action) {
    case "expire_hold":
      return "Expire Local Hold";
    case "cancel_proof":
      return "Cancel Proof Reservation";
  }
}

function reconciliationLabel(state: string | null): string | null {
  switch (state) {
    case "stripe_paid_pending_staff_approval":
      return "Stripe Paid";
    case "staff_approved_local_payment_posted":
      return "Payment Posted";
    case "amount_mismatch_needs_staff_review":
      return "Amount Review";
    case "payment_link_mismatch_needs_staff_review":
      return "Link Review";
    case "stripe_unpaid_needs_staff_review":
      return "Unpaid Review";
    case "unsafe_metadata_needs_staff_review":
      return "Metadata Review";
    default:
      return null;
  }
}

function activationLabel(state: string | null): string | null {
  switch (state) {
    case "activated_pending_staff_confirmation_review":
      return "Draft Review";
    case "confirmation_sent_ops_open":
      return "Confirm Sent";
    case "ops_closed_pending_confirmation":
      return "Ops Closed";
    case "completed":
      return "Activated";
    default:
      return state ? state.replace(/_/g, " ") : null;
  }
}

function readinessTone(state: string | null): string {
  switch (state) {
    case "ready":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "needs_staff_approval":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "local_hold_created":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "local_reservation_created":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "expired":
    case "blocked":
    case "parity_drift":
    case "parity_missing":
    case "missing_payment_handoff":
    case "hold_conflict":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    default:
      return "border-zinc-700 bg-zinc-950 text-zinc-300";
  }
}

function activationTone(state: string | null): string {
  switch (state) {
    case "activated_pending_staff_confirmation_review":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "confirmation_sent_ops_open":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "ops_closed_pending_confirmation":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "completed":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    default:
      return "border-zinc-700 bg-zinc-950 text-zinc-300";
  }
}

function timelineStageTone(stage: string): string {
  switch (stage) {
    case "quote":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "payment":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "activation":
      return "border-amber-500/30 bg-amber-500/10 text-amber-100";
    case "safeguard":
      return "border-rose-500/30 bg-rose-500/10 text-rose-100";
    case "cleanup":
      return "border-zinc-600 bg-zinc-800 text-zinc-200";
    default:
      return "border-zinc-700 bg-zinc-950 text-zinc-300";
  }
}

function exceptionSeverityTone(severity: ExceptionSeverity): string {
  switch (severity) {
    case "stop":
      return "border-rose-500/30 bg-rose-500/10 text-rose-100";
    case "attention":
      return "border-amber-500/30 bg-amber-500/10 text-amber-100";
    case "watch":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
  }
}

function exceptionActionLabel(action: ExceptionAction): string {
  switch (action) {
    case "approve_payment":
      return "Approve Pay";
    case "send_confirmation":
      return "Send Confirm";
    case "close_ops":
      return "Close Ops";
    case "expire_hold":
      return "Expire Hold";
    case "cancel_proof":
      return "Cancel Proof";
    case "open_audit":
      return "Open Audit";
    case "inspect":
      return "Inspect";
  }
}

function auditReferenceLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortAuditValue(value: string): string {
  if (value.length <= 24) return value;
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

function auditReferenceEntries(event: ActivationTimelineEvent): [string, string[]][] {
  return Object.entries(event.references).map(([key, value]) => [
    key,
    Array.isArray(value) ? value : [value],
  ]);
}

function reconciliationTone(state: string | null): string {
  switch (state) {
    case "stripe_paid_pending_staff_approval":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "staff_approved_local_payment_posted":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "amount_mismatch_needs_staff_review":
    case "payment_link_mismatch_needs_staff_review":
    case "stripe_unpaid_needs_staff_review":
    case "unsafe_metadata_needs_staff_review":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    default:
      return "border-zinc-700 bg-zinc-950 text-zinc-300";
  }
}

function safeguardTone(status: QuoteBookingSafeguard["status"]): string {
  switch (status) {
    case "clear":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "locked":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "attention":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  }
}

function kindLabel(kind: QuoteBookingRecord["kind"]): string {
  switch (kind) {
    case "quote":
      return "Quote";
    case "hold":
      return "Hold";
    case "reservation":
      return "Reservation";
    case "parity":
      return "Parity";
  }
}

function actionLabel(action: SafeAction): string {
  switch (action) {
    case "claim":
      return "Claim";
    case "mark_reviewed":
      return "Reviewed";
    case "escalate":
      return "Escalate";
    case "dismiss":
      return "Dismiss";
    case "note":
      return "Note";
  }
}

function SummaryMetric({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: number;
  detail: string;
  tone?: "default" | "warning" | "danger" | "success";
}) {
  const toneClass =
    tone === "danger"
      ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
      : tone === "warning"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
        : tone === "success"
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
          : "border-zinc-800 bg-zinc-900/70 text-zinc-100";

  return (
    <div className={`rounded-lg border px-4 py-4 ${toneClass}`}>
      <p className="text-xs uppercase text-current/70">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value.toLocaleString()}</p>
      <p className="mt-1 text-xs text-current/70">{detail}</p>
    </div>
  );
}

function SafeguardRow({ safeguard }: { safeguard: QuoteBookingSafeguard }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-4 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <LockKeyhole className="h-4 w-4 text-cyan-200" />
          <p className="font-medium text-zinc-50">{safeguard.label}</p>
          <Badge className={safeguardTone(safeguard.status)}>{safeguard.status}</Badge>
        </div>
        <p className="mt-2 text-sm text-zinc-400">{safeguard.detail}</p>
      </div>
      {safeguard.href ? (
        <Button
          asChild
          variant="outline"
          size="sm"
          className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
        >
          <Link href={safeguard.href}>
            Inspect
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      ) : null}
    </div>
  );
}

function ExceptionActionButton({
  item,
  action,
  onRun,
  primary = false,
}: {
  item: ActivationExceptionItem;
  action: ExceptionAction;
  onRun: (item: ActivationExceptionItem, action: ExceptionAction) => void;
  primary?: boolean;
}) {
  const Icon =
    action === "approve_payment"
      ? CreditCard
      : action === "send_confirmation"
        ? Send
        : action === "close_ops"
          ? CheckCircle2
          : action === "expire_hold"
            ? Timer
            : action === "cancel_proof"
              ? XCircle
              : action === "open_audit"
                ? History
                : ArrowRight;
  const className = primary
    ? "bg-cyan-700 text-white hover:bg-cyan-600"
    : "border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900";

  if (action === "inspect") {
    return (
      <Button asChild size="sm" variant={primary ? "default" : "outline"} className={className}>
        <Link href={item.record.href}>
          <Icon className="mr-2 h-4 w-4" />
          {exceptionActionLabel(action)}
        </Link>
      </Button>
    );
  }

  return (
    <Button
      onClick={() => onRun(item, action)}
      size="sm"
      variant={primary ? "default" : "outline"}
      className={className}
    >
      <Icon className="mr-2 h-4 w-4" />
      {exceptionActionLabel(action)}
    </Button>
  );
}

function ActivationExceptionQueue({
  items,
  onRun,
}: {
  items: ActivationExceptionItem[];
  onRun: (item: ActivationExceptionItem, action: ExceptionAction) => void;
}) {
  const stopCount = items.filter((item) => item.severity === "stop").length;
  const attentionCount = items.filter((item) => item.severity === "attention").length;

  return (
    <Card className="border-amber-500/20 bg-zinc-950/90">
      <CardHeader className="border-b border-zinc-800/80">
        <CardTitle className="flex items-center gap-2 text-zinc-50">
          <Siren className="h-5 w-5 text-amber-300" />
          Activation Exception Queue
        </CardTitle>
        <CardDescription>
          {stopCount.toLocaleString()} stop{stopCount === 1 ? "" : "s"}, {attentionCount.toLocaleString()} attention item
          {attentionCount === 1 ? "" : "s"}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-6">
        {items.length === 0 ? (
          <div className="flex flex-col gap-2 rounded-lg border border-emerald-500/20 bg-emerald-950/10 px-4 py-6 text-sm text-emerald-100 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5" />
              <span>No activation exceptions in the current window.</span>
            </div>
            <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-200">clear</Badge>
          </div>
        ) : (
          items.slice(0, 12).map((item) => {
            const record = item.record;
            return (
              <div
                key={item.id}
                className="flex flex-col gap-4 rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-4 xl:flex-row xl:items-start xl:justify-between"
              >
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={exceptionSeverityTone(item.severity)}>{item.severity}</Badge>
                    <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{kindLabel(record.kind)}</Badge>
                    {metadataString(record, "activation_state") ? (
                      <Badge className={activationTone(metadataString(record, "activation_state"))}>
                        {activationLabel(metadataString(record, "activation_state"))}
                      </Badge>
                    ) : null}
                    <span className="text-xs text-zinc-500">Age {formatAge(item.ageAt)}</span>
                  </div>
                  <div>
                    <p className="break-words text-sm font-semibold text-zinc-50">{item.label}</p>
                    <p className="mt-1 break-words text-sm text-zinc-400">{item.detail}</p>
                  </div>
                  <div className="grid gap-2 text-xs text-zinc-400 md:grid-cols-2 xl:grid-cols-4">
                    <div>
                      <p className="uppercase text-zinc-500">Reservation</p>
                      <p className="truncate">{record.title || "--"}</p>
                    </div>
                    <div>
                      <p className="uppercase text-zinc-500">Cabin</p>
                      <p className="truncate">{record.property_name || "--"}</p>
                    </div>
                    <div>
                      <p className="uppercase text-zinc-500">Guest</p>
                      <p className="truncate">{record.guest_label || "--"}</p>
                    </div>
                    <div>
                      <p className="uppercase text-zinc-500">Stay</p>
                      <p>
                        {formatDate(record.check_in)} to {formatDate(record.check_out)}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 xl:justify-end">
                  <ExceptionActionButton item={item} action={item.primaryAction} onRun={onRun} primary />
                  {item.secondaryAction ? (
                    <ExceptionActionButton item={item} action={item.secondaryAction} onRun={onRun} />
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

function RecordRow({
  record,
  onAction,
  onSend,
  onCreateHold,
  onConvertHold,
  onSendPayment,
  onApprovePayment,
  onSendConfirmation,
  onCloseOps,
  onCleanup,
  onOpenAudit,
  isActionPending,
  isSendPending,
  isHoldPending,
  isConvertPending,
  isPaymentPending,
  isApprovePaymentPending,
  isSendConfirmationPending,
  isCloseOpsPending,
  isCleanupPending,
}: {
  record: QuoteBookingRecord;
  onAction: (record: QuoteBookingRecord, action: SafeAction) => void;
  onSend: (record: QuoteBookingRecord) => void;
  onCreateHold: (record: QuoteBookingRecord) => void;
  onConvertHold: (record: QuoteBookingRecord) => void;
  onSendPayment: (record: QuoteBookingRecord) => void;
  onApprovePayment: (record: QuoteBookingRecord) => void;
  onSendConfirmation: (record: QuoteBookingRecord) => void;
  onCloseOps: (record: QuoteBookingRecord) => void;
  onCleanup: (record: QuoteBookingRecord, action: CleanupAction) => void;
  onOpenAudit: (record: QuoteBookingRecord) => void;
  isActionPending: boolean;
  isSendPending: boolean;
  isHoldPending: boolean;
  isConvertPending: boolean;
  isPaymentPending: boolean;
  isApprovePaymentPending: boolean;
  isSendConfirmationPending: boolean;
  isCloseOpsPending: boolean;
  isCleanupPending: boolean;
}) {
  const Icon = KIND_ICONS[record.kind];
  const readinessState = record.kind === "quote" ? metadataString(record, "readiness_state") : null;
  const readinessLabel = record.kind === "quote" ? metadataString(record, "readiness_label") : null;
  const readinessReasons = record.kind === "quote" ? metadataStrings(record, "readiness_reasons") : [];
  const paymentReconciliationState =
    record.kind === "reservation" ? metadataString(record, "payment_reconciliation_state") : null;
  const paymentReconciliationLabel = reconciliationLabel(paymentReconciliationState);
  const paymentReconciliationDetail =
    record.kind === "reservation" ? metadataString(record, "payment_reconciliation_detail") : null;
  const activationState = record.kind === "reservation" ? metadataString(record, "activation_state") : null;
  const activationStateLabel = activationLabel(activationState);
  const draftStatus = record.kind === "reservation" ? metadataString(record, "guest_confirmation_draft_status") : null;
  const draftSubject = record.kind === "reservation" ? metadataString(record, "guest_confirmation_draft_subject") : null;
  const draftBody = record.kind === "reservation" ? metadataString(record, "guest_confirmation_draft_body") : null;
  const sendPolicy = record.kind === "reservation" ? metadataString(record, "guest_confirmation_send_policy") : null;
  const sentAt = record.kind === "reservation" ? metadataString(record, "guest_confirmation_sent_at") : null;
  const opsStatus = record.kind === "reservation" ? metadataString(record, "ops_handoff_status") : null;
  const opsClosedAt = record.kind === "reservation" ? metadataString(record, "ops_handoff_closed_at") : null;
  const opsWorkOrderIds = record.kind === "reservation" ? metadataStrings(record, "ops_work_order_ids") : [];
  const housekeepingTaskId = record.kind === "reservation" ? metadataString(record, "housekeeping_task_id") : null;
  const activationTimeline =
    record.kind === "reservation" ? metadataTimeline(record, "activation_timeline") : [];
  const cleanupReason = metadataString(record, "cleanup_reason");
  const paymentReceivedCents =
    record.kind === "reservation" ? metadataNumber(record, "payment_reconciliation_amount_received_cents") : null;
  const canSend = canSendGuestQuote(record);
  const canHold = canCreateLocalHold(record);
  const canConvert = canConvertLocalReservation(record);
  const canPayment = canSendPaymentLink(record);
  const canApprove = canApprovePayment(record);
  const canSendConfirmation = canSendGuestConfirmation(record);
  const canCloseOps = canCloseOpsHandoff(record);
  const canCleanupHold = canExpireLocalHold(record);
  const canCleanupReservation = canCancelProofReservation(record);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Icon className="h-4 w-4 text-cyan-200" />
            <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{kindLabel(record.kind)}</Badge>
            <Badge className={stopTone(record.stop_level)}>{record.stop_level}</Badge>
            <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{record.status}</Badge>
            {readinessLabel ? (
              <Badge className={readinessTone(readinessState)}>{readinessLabel}</Badge>
            ) : null}
            {paymentReconciliationLabel ? (
              <Badge className={reconciliationTone(paymentReconciliationState)}>{paymentReconciliationLabel}</Badge>
            ) : null}
            {activationStateLabel ? (
              <Badge className={activationTone(activationState)}>{activationStateLabel}</Badge>
            ) : null}
            {record.assigned_to ? (
              <Badge className="border-cyan-500/30 bg-cyan-500/10 text-cyan-100">
                assigned
              </Badge>
            ) : null}
            {record.escalated ? (
              <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-200">
                escalated
              </Badge>
            ) : null}
            {record.reviewed ? (
              <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-200">
                reviewed
              </Badge>
            ) : null}
            {record.dismissed ? (
              <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">dismissed</Badge>
            ) : null}
          </div>
          <div>
            <p className="break-words text-base font-semibold text-zinc-50">{record.title}</p>
            <p className="mt-1 text-sm text-zinc-400">{record.stop_reason}</p>
          </div>
          <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <p className="text-xs uppercase text-zinc-500">Property</p>
              <p className="truncate">{record.property_name || "--"}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-zinc-500">Guest</p>
              <p className="truncate">{record.guest_label || "--"}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-zinc-500">Stay</p>
              <p>
                {formatDate(record.check_in)} to {formatDate(record.check_out)}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase text-zinc-500">Total</p>
              <p>{formatMoney(record.total_amount)}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-zinc-400">
            {record.payment_state ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <CreditCard className="h-3.5 w-3.5" />
                {record.payment_state}
              </span>
            ) : null}
            {record.parity_status ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                {record.parity_status}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
              <Timer className="h-3.5 w-3.5" />
              {formatTimestamp(record.created_at)}
            </span>
            {record.assigned_to ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <UserCheck className="h-3.5 w-3.5" />
                {record.assigned_to}
              </span>
            ) : null}
            {record.last_action ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                {record.last_action} by {record.last_action_by || "staff"}
              </span>
            ) : null}
            {paymentReceivedCents != null ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <CreditCard className="h-3.5 w-3.5" />
                Stripe {formatMoney(paymentReceivedCents / 100)}
              </span>
            ) : null}
          </div>
          {record.last_note ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-300">
              <span className="text-xs uppercase text-zinc-500">Latest note</span>
              <p className="mt-1">{record.last_note}</p>
            </div>
          ) : null}
          {readinessReasons.length > 0 ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-300">
              <span className="text-xs uppercase text-zinc-500">Readiness gate</span>
              <p className="mt-1">{readinessReasons.slice(0, 3).join(" ")}</p>
            </div>
          ) : null}
          {paymentReconciliationDetail ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-300">
              <span className="text-xs uppercase text-zinc-500">Payment reconciliation</span>
              <p className="mt-1">{paymentReconciliationDetail}</p>
            </div>
          ) : null}
          {activationState ? (
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/10 px-3 py-3 text-sm text-zinc-200">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs uppercase text-cyan-200/80">Activation package</span>
                {draftStatus ? (
                  <Badge className="border-cyan-500/30 bg-cyan-500/10 text-cyan-100">{draftStatus}</Badge>
                ) : null}
                {opsStatus ? (
                  <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-200">{opsStatus}</Badge>
                ) : null}
              </div>
              {draftSubject ? <p className="mt-2 font-medium text-zinc-50">{draftSubject}</p> : null}
              {draftBody ? (
                <p className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-zinc-300">
                  {draftBody}
                </p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-cyan-100/80">
                {sendPolicy ? <span>Send: {sendPolicy}</span> : null}
                {sentAt ? <span>Sent: {formatTimestamp(sentAt)}</span> : null}
                {opsWorkOrderIds.length > 0 ? <span>Work orders: {opsWorkOrderIds.length}</span> : null}
                {opsClosedAt ? <span>Ops closed: {formatTimestamp(opsClosedAt)}</span> : null}
                {housekeepingTaskId ? <span>Housekeeping task: ready</span> : null}
              </div>
              {activationTimeline.length > 0 ? (
                <div className="mt-4 border-t border-cyan-500/15 pt-3">
                  <div className="mb-3 flex items-center gap-2 text-xs uppercase text-cyan-200/80">
                    <History className="h-3.5 w-3.5" />
                    Activation Timeline
                  </div>
                  <div className="space-y-3">
                    {activationTimeline.slice(-3).map((event) => (
                      <div
                        key={event.id}
                        className="relative border-l border-zinc-700 pl-4 text-xs text-zinc-300"
                      >
                        <span className="absolute -left-1.5 top-1.5 h-2.5 w-2.5 rounded-full border border-cyan-400 bg-zinc-950" />
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-zinc-50">{event.label}</span>
                          <Badge className={timelineStageTone(event.stage)}>{event.stage}</Badge>
                          {event.outcome ? (
                            <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">
                              {event.outcome}
                            </Badge>
                          ) : null}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-zinc-500">
                          <span>{formatTimestamp(event.at)}</span>
                          {event.actor_email ? <span>{event.actor_email}</span> : null}
                          {event.resource_kind ? <span>{event.resource_kind}</span> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                  <Button
                    onClick={() => onOpenAudit(record)}
                    variant="outline"
                    size="sm"
                    className="mt-3 border-cyan-500/40 bg-cyan-950/20 text-cyan-100 hover:bg-cyan-950/40"
                  >
                    <History className="mr-2 h-4 w-4" />
                    Open Audit
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null}
          {cleanupReason && (canCleanupHold || canCleanupReservation) ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-300">
              <span className="text-xs uppercase text-zinc-500">Cleanup lane</span>
              <p className="mt-1">{cleanupReason}</p>
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">
          {canSend ? (
            <Button
              onClick={() => onSend(record)}
              disabled={isSendPending}
              size="sm"
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isSendPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              Send
            </Button>
          ) : null}
          {canHold ? (
            <Button
              onClick={() => onCreateHold(record)}
              disabled={isHoldPending}
              size="sm"
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              {isHoldPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CalendarCheck className="mr-2 h-4 w-4" />
              )}
              Hold
            </Button>
          ) : null}
          {canConvert ? (
            <Button
              onClick={() => onConvertHold(record)}
              disabled={isConvertPending}
              size="sm"
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isConvertPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <ClipboardCheck className="mr-2 h-4 w-4" />
              )}
              Reserve
            </Button>
          ) : null}
          {canPayment ? (
            <Button
              onClick={() => onSendPayment(record)}
              disabled={isPaymentPending}
              size="sm"
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isPaymentPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CreditCard className="mr-2 h-4 w-4" />
              )}
              Pay Link
            </Button>
          ) : null}
          {canApprove ? (
            <Button
              onClick={() => onApprovePayment(record)}
              disabled={isApprovePaymentPending}
              size="sm"
              className="bg-amber-700 text-white hover:bg-amber-600"
            >
              {isApprovePaymentPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="mr-2 h-4 w-4" />
              )}
              Approve Pay
            </Button>
          ) : null}
          {canSendConfirmation ? (
            <Button
              onClick={() => onSendConfirmation(record)}
              disabled={isSendConfirmationPending}
              size="sm"
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              {isSendConfirmationPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              Send Confirm
            </Button>
          ) : null}
          {canCloseOps ? (
            <Button
              onClick={() => onCloseOps(record)}
              disabled={isCloseOpsPending}
              size="sm"
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isCloseOpsPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              Close Ops
            </Button>
          ) : null}
          {canCleanupHold ? (
            <Button
              onClick={() => onCleanup(record, "expire_hold")}
              disabled={isCleanupPending}
              size="sm"
              className="bg-zinc-700 text-white hover:bg-zinc-600"
            >
              {isCleanupPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Timer className="mr-2 h-4 w-4" />
              )}
              Expire Hold
            </Button>
          ) : null}
          {canCleanupReservation ? (
            <Button
              onClick={() => onCleanup(record, "cancel_proof")}
              disabled={isCleanupPending}
              size="sm"
              className="bg-rose-700 text-white hover:bg-rose-600"
            >
              {isCleanupPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <XCircle className="mr-2 h-4 w-4" />
              )}
              Cancel Proof
            </Button>
          ) : null}
          {activationTimeline.length > 0 ? (
            <Button
              onClick={() => onOpenAudit(record)}
              variant="outline"
              size="sm"
              className="border-cyan-500/40 bg-cyan-950/20 text-cyan-100 hover:bg-cyan-950/40"
            >
              Audit
              <History className="ml-2 h-4 w-4" />
            </Button>
          ) : null}
          <Button
            onClick={() => onAction(record, "claim")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-cyan-500/40 bg-cyan-950/20 text-cyan-100 hover:bg-cyan-950/40"
          >
            Claim
            <UserCheck className="ml-2 h-4 w-4" />
          </Button>
          <Button
            onClick={() => onAction(record, "mark_reviewed")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-emerald-500/40 bg-emerald-950/20 text-emerald-100 hover:bg-emerald-950/40"
          >
            Reviewed
            <CheckCircle2 className="ml-2 h-4 w-4" />
          </Button>
          <Button
            onClick={() => onAction(record, "note")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            Note
            <StickyNote className="ml-2 h-4 w-4" />
          </Button>
          <Button
            asChild
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            <Link href={record.href}>
              Inspect
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
          {record.stop_level !== "clear" ? (
            <Button
              onClick={() => onAction(record, "escalate")}
              disabled={isActionPending}
              variant="outline"
              size="sm"
              className="border-amber-500/40 bg-amber-950/20 text-amber-100 hover:bg-amber-950/40"
            >
              Escalate
              <AlertTriangle className="ml-2 h-4 w-4" />
            </Button>
          ) : null}
          <Button
            onClick={() => onAction(record, "dismiss")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            Dismiss
            <XCircle className="ml-2 h-4 w-4" />
          </Button>
        </div>
        </div>
      </div>
  );
}

function ActivationAuditDialog({
  record,
  onClose,
}: {
  record: QuoteBookingRecord | null;
  onClose: () => void;
}) {
  const timeline = record ? metadataTimeline(record, "activation_timeline") : [];
  const activationState = record ? metadataString(record, "activation_state") : null;
  const summaryReferences = record
    ? [
        ["Reservation", record.id],
        ["Confirmation", record.title],
        ["Quote", metadataString(record, "quote_ref")],
        ["Hold", metadataString(record, "hold_ref")],
        ["Payment Link", metadataString(record, "payment_link_id")],
        ["Activation", metadataString(record, "activation_id")],
      ].filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].trim().length > 0)
    : [];

  return (
    <Dialog open={Boolean(record)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-hidden border-zinc-800 bg-zinc-950 text-zinc-50 sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="h-5 w-5 text-cyan-300" />
            Activation Audit
          </DialogTitle>
          <DialogDescription>
            {record?.title || "Reservation"} audit chain, staff actions, references, and immutable hashes.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[68vh] space-y-4 overflow-y-auto pr-2">
          <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/10 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">internal only</Badge>
              {activationState ? (
                <Badge className={activationTone(activationState)}>{activationLabel(activationState)}</Badge>
              ) : null}
              <Badge className="border-rose-500/30 bg-rose-500/10 text-rose-100">
                legacy untouched
              </Badge>
              <Badge className="border-rose-500/30 bg-rose-500/10 text-rose-100">
                Streamline blocked
              </Badge>
            </div>
            {summaryReferences.length > 0 ? (
              <div className="mt-3 grid gap-2 text-xs md:grid-cols-2 xl:grid-cols-3">
                {summaryReferences.map(([label, value]) => (
                  <div key={label} className="rounded-md border border-zinc-800 bg-zinc-950/70 px-3 py-2">
                    <p className="uppercase text-zinc-500">{label}</p>
                    <p className="mt-1 break-all font-mono text-zinc-200">{shortAuditValue(value)}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          {timeline.length === 0 ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-8 text-center text-sm text-zinc-400">
              No audit events are available for this reservation.
            </div>
          ) : (
            <div className="space-y-3">
              {timeline.map((event) => {
                const references = auditReferenceEntries(event);
                return (
                  <div key={event.id} className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge className={timelineStageTone(event.stage)}>{event.stage}</Badge>
                          {event.outcome ? (
                            <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">
                              {event.outcome}
                            </Badge>
                          ) : null}
                          {event.activation_state ? (
                            <Badge className={activationTone(event.activation_state)}>
                              {activationLabel(event.activation_state)}
                            </Badge>
                          ) : null}
                        </div>
                        <p className="mt-2 text-sm font-semibold text-zinc-50">{event.label}</p>
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
                          <span>{formatTimestamp(event.at)}</span>
                          {event.actor_email ? <span>{event.actor_email}</span> : null}
                          {event.resource_kind ? <span>{event.resource_kind}</span> : null}
                        </div>
                      </div>
                      {event.audit_hash ? (
                        <div className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs">
                          <p className="uppercase text-zinc-500">Audit Hash</p>
                          <p className="mt-1 break-all font-mono text-zinc-300">{event.audit_hash}</p>
                        </div>
                      ) : null}
                    </div>

                    {event.detail ? (
                      <p className="mt-3 break-words text-sm leading-6 text-zinc-300">{event.detail}</p>
                    ) : null}
                    {event.note ? (
                      <div className="mt-3 rounded-md border border-cyan-500/20 bg-cyan-950/20 px-3 py-2 text-sm text-cyan-100">
                        {event.note}
                      </div>
                    ) : null}

                    {references.length > 0 ? (
                      <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
                        {references.map(([key, values]) => (
                          <div key={`${event.id}-${key}`} className="rounded-md border border-zinc-800 bg-zinc-950/70 px-3 py-2">
                            <p className="uppercase text-zinc-500">{auditReferenceLabel(key)}</p>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {values.map((value) => (
                                <span
                                  key={`${event.id}-${key}-${value}`}
                                  className="rounded-full border border-zinc-700 px-2 py-0.5 font-mono text-zinc-200"
                                  title={value}
                                >
                                  {shortAuditValue(value)}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}

                    {event.safeguards.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {event.safeguards.map((safeguard) => (
                          <span
                            key={`${event.id}-${safeguard}`}
                            className="rounded-full border border-rose-500/20 bg-rose-950/20 px-2 py-0.5 text-xs text-rose-100"
                          >
                            {safeguard}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            onClick={onClose}
            variant="outline"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function QuoteControlPage() {
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [stopFilter, setStopFilter] = useState<StopFilter>("all");
  const [actionTarget, setActionTarget] = useState<ActionTarget | null>(null);
  const [actionNote, setActionNote] = useState("");
  const [sendTarget, setSendTarget] = useState<QuoteBookingRecord | null>(null);
  const [sendNote, setSendNote] = useState("");
  const [isSendingQuote, setIsSendingQuote] = useState(false);
  const [holdTarget, setHoldTarget] = useState<QuoteBookingRecord | null>(null);
  const [holdNote, setHoldNote] = useState("");
  const [isCreatingHold, setIsCreatingHold] = useState(false);
  const [reservationTarget, setReservationTarget] = useState<QuoteBookingRecord | null>(null);
  const [reservationNote, setReservationNote] = useState("");
  const [isConvertingReservation, setIsConvertingReservation] = useState(false);
  const [paymentTarget, setPaymentTarget] = useState<QuoteBookingRecord | null>(null);
  const [paymentNote, setPaymentNote] = useState("");
  const [isSendingPaymentLink, setIsSendingPaymentLink] = useState(false);
  const [paymentApprovalTarget, setPaymentApprovalTarget] = useState<QuoteBookingRecord | null>(null);
  const [paymentApprovalNote, setPaymentApprovalNote] = useState("");
  const [isApprovingPayment, setIsApprovingPayment] = useState(false);
  const [confirmationTarget, setConfirmationTarget] = useState<QuoteBookingRecord | null>(null);
  const [confirmationNote, setConfirmationNote] = useState("");
  const [isSendingConfirmation, setIsSendingConfirmation] = useState(false);
  const [opsCloseTarget, setOpsCloseTarget] = useState<QuoteBookingRecord | null>(null);
  const [opsCloseNote, setOpsCloseNote] = useState("");
  const [isClosingOps, setIsClosingOps] = useState(false);
  const [cleanupTarget, setCleanupTarget] = useState<CleanupTarget | null>(null);
  const [cleanupNote, setCleanupNote] = useState("");
  const [isCleaningUp, setIsCleaningUp] = useState(false);
  const [auditTarget, setAuditTarget] = useState<QuoteBookingRecord | null>(null);
  const [isCreatingProofQuote, setIsCreatingProofQuote] = useState(false);
  const { data, isLoading, error, refetch, isFetching } = useQuoteBookingControlTower(25);
  const actionMutation = useQuoteBookingControlAction();

  const allRecords = useMemo(
    () => [
      ...(data?.quotes ?? []),
      ...(data?.holds ?? []),
      ...(data?.reservations ?? []),
      ...(data?.parity_audits ?? []),
    ],
    [data],
  );

  const visibleRecords = allRecords.filter((record) => {
    const kindMatches = kindFilter === "all" || record.kind === kindFilter;
    const stopMatches = stopFilter === "all" || record.stop_level === stopFilter;
    return kindMatches && stopMatches;
  });
  const exceptionItems = useMemo(() => buildActivationExceptions(allRecords), [allRecords]);

  if (isLoading && !data) {
    return (
      <div className="space-y-6">
        <div>
          <Button
            asChild
            variant="outline"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            <Link href="/command">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Command
            </Link>
          </Button>
        </div>
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="flex items-center gap-3 pt-6 text-sm text-zinc-400">
            <RefreshCw className="h-4 w-4 animate-spin" />
            Loading quote-to-booking posture from local ledgers...
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="space-y-6">
        <Button
          asChild
          variant="outline"
          className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
        >
          <Link href="/command">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Command
          </Link>
        </Button>
        <Card className="border-rose-500/30 bg-rose-950/10">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-rose-100">
              <Siren className="h-5 w-5" />
              Control Tower Unavailable
            </CardTitle>
            <CardDescription className="text-rose-200/80">
              The quote-to-booking aggregate endpoint did not respond.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-rose-100">
            {error instanceof Error ? error.message : "Unknown error"}
          </CardContent>
        </Card>
      </div>
    );
  }

  const summary = data?.summary;
  const openAction = (record: QuoteBookingRecord, action: SafeAction) => {
    setActionTarget({ record, action });
    setActionNote("");
  };
  const openSend = (record: QuoteBookingRecord) => {
    setSendTarget(record);
    setSendNote("");
  };
  const openCreateHold = (record: QuoteBookingRecord) => {
    setHoldTarget(record);
    setHoldNote("");
  };
  const openConvertHold = (record: QuoteBookingRecord) => {
    setReservationTarget(record);
    setReservationNote("");
  };
  const openSendPayment = (record: QuoteBookingRecord) => {
    setPaymentTarget(record);
    setPaymentNote("");
  };
  const openApprovePayment = (record: QuoteBookingRecord) => {
    setPaymentApprovalTarget(record);
    setPaymentApprovalNote("");
  };
  const openSendConfirmation = (record: QuoteBookingRecord) => {
    setConfirmationTarget(record);
    setConfirmationNote("");
  };
  const openCloseOps = (record: QuoteBookingRecord) => {
    setOpsCloseTarget(record);
    setOpsCloseNote("");
  };
  const openCleanup = (record: QuoteBookingRecord, action: CleanupAction) => {
    setCleanupTarget({ record, action });
    setCleanupNote("");
  };
  const openAudit = (record: QuoteBookingRecord) => {
    setAuditTarget(record);
  };
  const runExceptionAction = (item: ActivationExceptionItem, action: ExceptionAction) => {
    switch (action) {
      case "approve_payment":
        openApprovePayment(item.record);
        break;
      case "send_confirmation":
        openSendConfirmation(item.record);
        break;
      case "close_ops":
        openCloseOps(item.record);
        break;
      case "expire_hold":
        openCleanup(item.record, "expire_hold");
        break;
      case "cancel_proof":
        openCleanup(item.record, "cancel_proof");
        break;
      case "open_audit":
        openAudit(item.record);
        break;
      case "inspect":
        break;
    }
  };
  const submitAction = () => {
    if (!actionTarget) return;
    actionMutation.mutate(
      {
        kind: actionTarget.record.kind,
        id: actionTarget.record.id,
        action: actionTarget.action,
        note: actionNote.trim() || undefined,
      },
      {
        onSuccess: () => {
          setActionTarget(null);
          setActionNote("");
        },
      },
    );
  };
  const submitSend = async () => {
    if (!sendTarget) return;
    setIsSendingQuote(true);
    try {
      const response = await api.post<QuoteBookingSendResponse>(
        `/api/vrs/quote-booking/control-tower/quote/${sendTarget.id}/send`,
        {
          ...(sendNote.trim() ? { note: sendNote.trim() } : {}),
        },
      );
      toast.success(response.message || `Quote sent to ${response.guest_email}`);
      setSendTarget(null);
      setSendNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Quote send failed";
      toast.error(message);
    } finally {
      setIsSendingQuote(false);
    }
  };
  const createProofQuote = async () => {
    setIsCreatingProofQuote(true);
    try {
      const response = await api.post<QuoteBookingProofLaneResponse>(
        "/api/vrs/quote-booking/control-tower/proof-lane/test-quote",
        {},
      );
      toast.success(response.message || "Proof lane test quote created");
      setKindFilter("quote");
      setStopFilter("clear");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Proof lane creation failed";
      toast.error(message);
    } finally {
      setIsCreatingProofQuote(false);
    }
  };
  const submitCreateHold = async () => {
    if (!holdTarget) return;
    setIsCreatingHold(true);
    try {
      const response = await api.post<QuoteBookingHoldResponse>(
        `/api/vrs/quote-booking/control-tower/quote/${holdTarget.id}/create-hold`,
        {
          ...(holdNote.trim() ? { note: holdNote.trim() } : {}),
        },
      );
      toast.success(response.message || "Local checkout hold created");
      setHoldTarget(null);
      setHoldNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Local hold creation failed";
      toast.error(message);
    } finally {
      setIsCreatingHold(false);
    }
  };
  const submitConvertHold = async () => {
    if (!reservationTarget) return;
    setIsConvertingReservation(true);
    try {
      const response = await api.post<QuoteBookingReservationResponse>(
        `/api/vrs/quote-booking/control-tower/quote/${reservationTarget.id}/convert-hold`,
        {
          ...(reservationNote.trim() ? { note: reservationNote.trim() } : {}),
        },
      );
      toast.success(response.message || `Reservation ${response.confirmation_code} created`);
      setReservationTarget(null);
      setReservationNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Local reservation conversion failed";
      toast.error(message);
    } finally {
      setIsConvertingReservation(false);
    }
  };
  const submitSendPaymentLink = async () => {
    if (!paymentTarget) return;
    setIsSendingPaymentLink(true);
    try {
      const response = await api.post<QuoteBookingPaymentLinkResponse>(
        `/api/vrs/quote-booking/control-tower/reservation/${paymentTarget.id}/send-payment-link`,
        {
          ...(paymentNote.trim() ? { note: paymentNote.trim() } : {}),
        },
      );
      toast.success(response.message || `Payment link sent for ${response.confirmation_code}`);
      setPaymentTarget(null);
      setPaymentNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Payment link handoff failed";
      toast.error(message);
    } finally {
      setIsSendingPaymentLink(false);
    }
  };
  const submitApprovePayment = async () => {
    if (!paymentApprovalTarget) return;
    setIsApprovingPayment(true);
    try {
      const response = await api.post<QuoteBookingPaymentApprovalResponse>(
        `/api/vrs/quote-booking/control-tower/reservation/${paymentApprovalTarget.id}/approve-payment`,
        {
          ...(paymentApprovalNote.trim() ? { note: paymentApprovalNote.trim() } : {}),
        },
      );
      toast.success(
        response.message ||
          `Payment activated for ${response.confirmation_code}; draft and ops handoff are ready.`,
      );
      setPaymentApprovalTarget(null);
      setPaymentApprovalNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Payment approval failed";
      toast.error(message);
    } finally {
      setIsApprovingPayment(false);
    }
  };
  const submitSendConfirmation = async () => {
    if (!confirmationTarget) return;
    setIsSendingConfirmation(true);
    try {
      const response = await api.post<QuoteBookingConfirmationSendResponse>(
        `/api/vrs/quote-booking/control-tower/reservation/${confirmationTarget.id}/send-confirmation`,
        {
          ...(confirmationNote.trim() ? { note: confirmationNote.trim() } : {}),
        },
      );
      toast.success(response.message || `Confirmation sent for ${response.confirmation_code}`);
      setConfirmationTarget(null);
      setConfirmationNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Confirmation send failed";
      toast.error(message);
    } finally {
      setIsSendingConfirmation(false);
    }
  };
  const submitCloseOps = async () => {
    if (!opsCloseTarget) return;
    setIsClosingOps(true);
    try {
      const response = await api.post<QuoteBookingOpsCloseResponse>(
        `/api/vrs/quote-booking/control-tower/reservation/${opsCloseTarget.id}/close-ops`,
        {
          ...(opsCloseNote.trim() ? { note: opsCloseNote.trim() } : {}),
        },
      );
      toast.success(response.message || `Ops handoff closed for ${response.confirmation_code}`);
      setOpsCloseTarget(null);
      setOpsCloseNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Ops handoff close failed";
      toast.error(message);
    } finally {
      setIsClosingOps(false);
    }
  };
  const submitCleanup = async () => {
    if (!cleanupTarget) return;
    setIsCleaningUp(true);
    try {
      const path =
        cleanupTarget.action === "expire_hold"
          ? `/api/vrs/quote-booking/control-tower/hold/${cleanupTarget.record.id}/expire`
          : `/api/vrs/quote-booking/control-tower/reservation/${cleanupTarget.record.id}/cancel-proof`;
      const response = await api.post<QuoteBookingCleanupResponse>(path, {
        ...(cleanupNote.trim() ? { note: cleanupNote.trim() } : {}),
      });
      toast.success(response.message || "Cleanup recorded");
      setCleanupTarget(null);
      setCleanupNote("");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Cleanup failed";
      toast.error(message);
    } finally {
      setIsCleaningUp(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <Button
          asChild
          variant="outline"
          className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
        >
          <Link href="/command">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Command
          </Link>
        </Button>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase text-cyan-100">
              <PauseCircle className="h-3.5 w-3.5" />
              Read-only control surface
            </div>
            <h1 className="mt-3 text-3xl font-semibold text-zinc-50">Quote-to-Booking Control Tower</h1>
            <p className="mt-2 max-w-4xl text-sm text-zinc-400">
              Internal visibility across guest quotes, checkout holds, Stripe handoff state,
              reservation conversion, and Streamline parity. Risky actions stay behind the
              existing approval workflows.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => refetch()}
              disabled={isFetching}
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/vrs/quotes">
                Quote Tools
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/command/checkout-parity">
                Parity Console
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-8">
        <SummaryMetric
          label="Pending Quotes"
          value={metric(summary, "pending_quotes")}
          detail="Awaiting staff or guest action"
          tone={metric(summary, "pending_quotes") > 0 ? "warning" : "success"}
        />
        <SummaryMetric
          label="Ready Quotes"
          value={metric(summary, "ready_quotes")}
          detail="Eligible for controlled guest-send"
          tone={metric(summary, "ready_quotes") > 0 ? "success" : "default"}
        />
        <SummaryMetric
          label="Need Approval"
          value={metric(summary, "quotes_needing_staff_approval")}
          detail="Machine checks passed, staff gate open"
          tone={metric(summary, "quotes_needing_staff_approval") > 0 ? "warning" : "success"}
        />
        <SummaryMetric
          label="Blocked Quotes"
          value={metric(summary, "blocked_quotes")}
          detail="Expired, conflict, missing payment, or parity issue"
          tone={metric(summary, "blocked_quotes") > 0 ? "danger" : "success"}
        />
        <SummaryMetric
          label="Hard Stops"
          value={metric(summary, "hard_stops")}
          detail={`${metric(summary, "inspection_items").toLocaleString()} more need inspection`}
          tone={metric(summary, "hard_stops") > 0 ? "danger" : "success"}
        />
        <SummaryMetric
          label="Payment Review"
          value={metric(summary, "payment_reconciliations_pending")}
          detail={`${metric(summary, "payment_reconciliations_blocked").toLocaleString()} blocked signals`}
          tone={
            metric(summary, "payment_reconciliations_blocked") > 0
              ? "danger"
              : metric(summary, "payment_reconciliations_pending") > 0
                ? "warning"
                : "success"
          }
        />
        <SummaryMetric
          label="Activation"
          value={metric(summary, "activation_packages_pending")}
          detail="Drafts and ops handoffs pending review"
          tone={metric(summary, "activation_packages_pending") > 0 ? "warning" : "success"}
        />
        <SummaryMetric
          label="Cleanup"
          value={metric(summary, "expired_local_holds_pending") + metric(summary, "proof_reservations_cleanup_pending")}
          detail={`${metric(summary, "proof_reservations_cleanup_pending").toLocaleString()} proof reservations`}
          tone={
            metric(summary, "expired_local_holds_pending") + metric(summary, "proof_reservations_cleanup_pending") > 0
              ? "warning"
              : "success"
          }
        />
      </div>

      <ActivationExceptionQueue items={exceptionItems} onRun={runExceptionAction} />

      <Card className="border-emerald-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <FlaskConical className="h-5 w-5 text-emerald-300" />
            Proof Lane
          </CardTitle>
          <CardDescription>
            Stripe test mode, staff email only, no Streamline write, and no legacy storefront change.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 pt-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-3">
              <p className="text-xs uppercase text-zinc-500">Payment</p>
              <p className="mt-1 text-emerald-100">Stripe test link</p>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-3">
              <p className="text-xs uppercase text-zinc-500">Approval</p>
              <p className="mt-1 text-emerald-100">Staff reviewed</p>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-3">
              <p className="text-xs uppercase text-zinc-500">Boundary</p>
              <p className="mt-1 text-emerald-100">Internal only</p>
            </div>
          </div>
          <Button
            onClick={createProofQuote}
            disabled={isCreatingProofQuote}
            className="bg-emerald-700 text-white hover:bg-emerald-600"
          >
            {isCreatingProofQuote ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <FlaskConical className="mr-2 h-4 w-4" />
            )}
            Create Test Quote
          </Button>
        </CardContent>
      </Card>

      <Card className="border-cyan-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <LockKeyhole className="h-5 w-5 text-cyan-300" />
            Safeguards
          </CardTitle>
          <CardDescription>
            These locks keep this build internal, inspectable, and human-approved.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-6">
          {(data?.safeguards ?? []).map((safeguard) => (
            <SafeguardRow key={safeguard.id} safeguard={safeguard} />
          ))}
        </CardContent>
      </Card>

      <Card className="border-emerald-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <ShieldCheck className="h-5 w-5 text-emerald-300" />
            Conversion Flow
          </CardTitle>
          <CardDescription>
            Quote approval to hold, payment, reservation, and Streamline parity in one view.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap gap-2">
            {KIND_FILTERS.map((filter) => (
              <Button
                key={filter.id}
                onClick={() => setKindFilter(filter.id)}
                size="sm"
                variant={kindFilter === filter.id ? "default" : "outline"}
                className={
                  kindFilter === filter.id
                    ? "bg-emerald-700 text-white hover:bg-emerald-600"
                    : "border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
                }
              >
                {filter.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {STOP_FILTERS.map((filter) => (
              <Button
                key={filter.id}
                onClick={() => setStopFilter(filter.id)}
                size="sm"
                variant={stopFilter === filter.id ? "default" : "outline"}
                className={
                  stopFilter === filter.id
                    ? "bg-cyan-700 text-white hover:bg-cyan-600"
                    : "border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
                }
              >
                {filter.label}
              </Button>
            ))}
          </div>

          {visibleRecords.length === 0 ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-8 text-center text-sm text-zinc-400">
              No records match this filter.
            </div>
          ) : (
            <div className="space-y-3">
              {visibleRecords.map((record) => (
                <RecordRow
                  key={`${record.kind}-${record.id}`}
                  record={record}
                  onAction={openAction}
                  onSend={openSend}
                  onCreateHold={openCreateHold}
                  onConvertHold={openConvertHold}
                  onSendPayment={openSendPayment}
                  onApprovePayment={openApprovePayment}
                  onSendConfirmation={openSendConfirmation}
                  onCloseOps={openCloseOps}
                  onCleanup={openCleanup}
                  onOpenAudit={openAudit}
                  isActionPending={actionMutation.isPending}
                  isSendPending={isSendingQuote}
                  isHoldPending={isCreatingHold}
                  isConvertPending={isConvertingReservation}
                  isPaymentPending={isSendingPaymentLink}
                  isApprovePaymentPending={isApprovingPayment}
                  isSendConfirmationPending={isSendingConfirmation}
                  isCloseOpsPending={isClosingOps}
                  isCleanupPending={isCleaningUp}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ActivationAuditDialog record={auditTarget} onClose={() => setAuditTarget(null)} />

      <Dialog open={Boolean(actionTarget)} onOpenChange={(open) => !open && setActionTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>
              {actionTarget ? actionLabel(actionTarget.action) : "Control Action"}
            </DialogTitle>
            <DialogDescription>
              {actionTarget?.record.title || "Control Tower item"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/20 px-3 py-3 text-sm text-cyan-100">
              Audit-only action. Source quote, booking, payment, public content, and Streamline records stay unchanged.
            </div>
            <Textarea
              value={actionNote}
              onChange={(event) => setActionNote(event.target.value)}
              placeholder="Internal note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setActionTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitAction}
              disabled={actionMutation.isPending || (actionTarget?.action === "note" && !actionNote.trim())}
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              {actionMutation.isPending ? "Recording..." : "Record Action"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(sendTarget)} onOpenChange={(open) => !open && setSendTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Send Guest Quote</DialogTitle>
            <DialogDescription>{sendTarget?.title || "Ready quote"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/20 px-3 py-3 text-sm text-emerald-100">
              Server-side readiness is required again before delivery. This sends the quote email only; it does not
              create a hold, charge a card, change Streamline, touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{sendTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Total</p>
                <p>{formatMoney(sendTarget?.total_amount)}</p>
              </div>
            </div>
            <Textarea
              value={sendNote}
              onChange={(event) => setSendNote(event.target.value)}
              placeholder="Internal send note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setSendTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitSend}
              disabled={isSendingQuote || !sendTarget || !canSendGuestQuote(sendTarget)}
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isSendingQuote ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" />
                  Send Quote
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(holdTarget)} onOpenChange={(open) => !open && setHoldTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Create Local Hold</DialogTitle>
            <DialogDescription>{holdTarget?.title || "Sent quote"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/20 px-3 py-3 text-sm text-cyan-100">
              This creates a local checkout hold only. It does not charge a card, create a PaymentIntent,
              convert a reservation, write to Streamline, touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{holdTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Stay</p>
                <p>
                  {formatDate(holdTarget?.check_in)} to {formatDate(holdTarget?.check_out)}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Total</p>
                <p>{formatMoney(holdTarget?.total_amount)}</p>
              </div>
            </div>
            <Textarea
              value={holdNote}
              onChange={(event) => setHoldNote(event.target.value)}
              placeholder="Internal hold note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setHoldTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitCreateHold}
              disabled={isCreatingHold || !holdTarget || !canCreateLocalHold(holdTarget)}
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              {isCreatingHold ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <CalendarCheck className="mr-2 h-4 w-4" />
                  Create Hold
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(reservationTarget)} onOpenChange={(open) => !open && setReservationTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Create Local Reservation</DialogTitle>
            <DialogDescription>{reservationTarget?.title || "Held quote"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/20 px-3 py-3 text-sm text-emerald-100">
              This converts the local hold into a pending-payment local reservation. It does not charge a card,
              create a PaymentIntent, mark the reservation paid, write to Streamline, touch the public website,
              or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{reservationTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Stay</p>
                <p>
                  {formatDate(reservationTarget?.check_in)} to {formatDate(reservationTarget?.check_out)}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Balance Due</p>
                <p>{formatMoney(reservationTarget?.total_amount)}</p>
              </div>
            </div>
            <Textarea
              value={reservationNote}
              onChange={(event) => setReservationNote(event.target.value)}
              placeholder="Internal reservation note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setReservationTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitConvertHold}
              disabled={isConvertingReservation || !reservationTarget || !canConvertLocalReservation(reservationTarget)}
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isConvertingReservation ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <ClipboardCheck className="mr-2 h-4 w-4" />
                  Create Reservation
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(paymentTarget)} onOpenChange={(open) => !open && setPaymentTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Send Payment Link</DialogTitle>
            <DialogDescription>{paymentTarget?.title || "Pending-payment reservation"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/20 px-3 py-3 text-sm text-emerald-100">
              This creates and emails a Stripe-hosted payment link. CROG-VRS does not charge the card here,
              mark the reservation paid, write to Streamline, touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{paymentTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Reservation</p>
                <p className="truncate">{paymentTarget?.title || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Balance Due</p>
                <p>{formatMoney(Number(paymentTarget?.metadata?.balance_due ?? paymentTarget?.total_amount ?? 0))}</p>
              </div>
            </div>
            <Textarea
              value={paymentNote}
              onChange={(event) => setPaymentNote(event.target.value)}
              placeholder="Internal payment handoff note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setPaymentTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitSendPaymentLink}
              disabled={isSendingPaymentLink || !paymentTarget || !canSendPaymentLink(paymentTarget)}
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isSendingPaymentLink ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <CreditCard className="mr-2 h-4 w-4" />
                  Send Payment Link
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(paymentApprovalTarget)}
        onOpenChange={(open) => !open && setPaymentApprovalTarget(null)}
      >
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Approve Payment Posting</DialogTitle>
            <DialogDescription>
              {paymentApprovalTarget?.title || "Stripe reconciled reservation"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-amber-500/20 bg-amber-950/20 px-3 py-3 text-sm text-amber-100">
              This posts local CROG-VRS payment state after a Stripe webhook signal, creates the guest
              confirmation draft, and opens the ops handoff. It does not charge a card, write to Streamline,
              touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{paymentApprovalTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Stripe Amount</p>
                <p>
                  {formatMoney(
                    Number(paymentApprovalTarget?.metadata?.payment_reconciliation_amount_received_cents ?? 0) / 100,
                  )}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Balance Due</p>
                <p>
                  {formatMoney(
                    Number(paymentApprovalTarget?.metadata?.balance_due ?? paymentApprovalTarget?.total_amount ?? 0),
                  )}
                </p>
              </div>
            </div>
            <Textarea
              value={paymentApprovalNote}
              onChange={(event) => setPaymentApprovalNote(event.target.value)}
              placeholder="Internal approval note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setPaymentApprovalTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitApprovePayment}
              disabled={isApprovingPayment || !paymentApprovalTarget || !canApprovePayment(paymentApprovalTarget)}
              className="bg-amber-700 text-white hover:bg-amber-600"
            >
              {isApprovingPayment ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Posting...
                </>
              ) : (
                <>
                  <ShieldCheck className="mr-2 h-4 w-4" />
                  Post Local Payment
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(confirmationTarget)} onOpenChange={(open) => !open && setConfirmationTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Approve And Send Confirmation</DialogTitle>
            <DialogDescription>{confirmationTarget?.title || "Activated reservation"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/20 px-3 py-3 text-sm text-cyan-100">
              This sends the staff-reviewed confirmation draft to the guest. It does not charge a card, write to
              Streamline, touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{confirmationTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Draft</p>
                <p className="truncate">
                  {metadataString(confirmationTarget || ({} as QuoteBookingRecord), "guest_confirmation_draft_status") ||
                    "--"}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Ops</p>
                <p className="truncate">
                  {metadataString(confirmationTarget || ({} as QuoteBookingRecord), "ops_handoff_status") || "--"}
                </p>
              </div>
            </div>
            {metadataString(confirmationTarget || ({} as QuoteBookingRecord), "guest_confirmation_draft_subject") ? (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-3 text-sm text-zinc-300">
                <span className="text-xs uppercase text-zinc-500">Draft</span>
                <p className="mt-1 font-medium text-zinc-50">
                  {metadataString(confirmationTarget || ({} as QuoteBookingRecord), "guest_confirmation_draft_subject")}
                </p>
                <p className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words text-xs leading-5">
                  {metadataString(confirmationTarget || ({} as QuoteBookingRecord), "guest_confirmation_draft_body")}
                </p>
              </div>
            ) : null}
            <Textarea
              value={confirmationNote}
              onChange={(event) => setConfirmationNote(event.target.value)}
              placeholder="Internal send approval note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setConfirmationTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitSendConfirmation}
              disabled={isSendingConfirmation || !confirmationTarget || !canSendGuestConfirmation(confirmationTarget)}
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              {isSendingConfirmation ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" />
                  Send Confirmation
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(opsCloseTarget)} onOpenChange={(open) => !open && setOpsCloseTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>Close Ops Handoff</DialogTitle>
            <DialogDescription>{opsCloseTarget?.title || "Activated reservation"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/20 px-3 py-3 text-sm text-emerald-100">
              This completes the internal activation work orders and closes the handoff. Housekeeping remains scheduled;
              this does not write to Streamline, touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Guest</p>
                <p className="truncate">{opsCloseTarget?.guest_label || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Work Orders</p>
                <p>{metadataStrings(opsCloseTarget || ({} as QuoteBookingRecord), "ops_work_order_ids").length}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Housekeeping</p>
                <p>
                  {metadataString(opsCloseTarget || ({} as QuoteBookingRecord), "housekeeping_task_id")
                    ? "scheduled"
                    : "--"}
                </p>
              </div>
            </div>
            <Textarea
              value={opsCloseNote}
              onChange={(event) => setOpsCloseNote(event.target.value)}
              placeholder="Internal ops closure note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setOpsCloseTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitCloseOps}
              disabled={isClosingOps || !opsCloseTarget || !canCloseOpsHandoff(opsCloseTarget)}
              className="bg-emerald-700 text-white hover:bg-emerald-600"
            >
              {isClosingOps ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Closing...
                </>
              ) : (
                <>
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  Close Handoff
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(cleanupTarget)} onOpenChange={(open) => !open && setCleanupTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>{cleanupTarget ? cleanupLabel(cleanupTarget.action) : "Cleanup"}</DialogTitle>
            <DialogDescription>{cleanupTarget?.record.title || "Quote-control artifact"}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-rose-500/20 bg-rose-950/20 px-3 py-3 text-sm text-rose-100">
              This cleanup lane only touches local CROG-VRS proof artifacts. It does not refund or charge a card,
              write to Streamline, touch the public website, or alter DNS/tunnels.
            </div>
            <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase text-zinc-500">Kind</p>
                <p className="truncate">{cleanupTarget ? kindLabel(cleanupTarget.record.kind) : "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Status</p>
                <p className="truncate">{cleanupTarget?.record.status || "--"}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-zinc-500">Stay</p>
                <p>
                  {formatDate(cleanupTarget?.record.check_in)} to {formatDate(cleanupTarget?.record.check_out)}
                </p>
              </div>
            </div>
            {metadataString(cleanupTarget?.record || ({} as QuoteBookingRecord), "cleanup_reason") ? (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-300">
                <span className="text-xs uppercase text-zinc-500">Gate</span>
                <p className="mt-1">
                  {metadataString(cleanupTarget?.record || ({} as QuoteBookingRecord), "cleanup_reason")}
                </p>
              </div>
            ) : null}
            <Textarea
              value={cleanupNote}
              onChange={(event) => setCleanupNote(event.target.value)}
              placeholder="Internal cleanup note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setCleanupTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitCleanup}
              disabled={isCleaningUp || !cleanupTarget}
              className="bg-rose-700 text-white hover:bg-rose-600"
            >
              {isCleaningUp ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cleaning...
                </>
              ) : (
                <>
                  <XCircle className="mr-2 h-4 w-4" />
                  Confirm Cleanup
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
