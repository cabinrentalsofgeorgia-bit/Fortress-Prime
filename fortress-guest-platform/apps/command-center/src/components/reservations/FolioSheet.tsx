"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

/* ── Folio Type Contracts (mirrors backend Pydantic schemas) ────── */

interface FolioGuest {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  phone_number: string;
  loyalty_tier: string;
  lifetime_stays: number;
  lifetime_revenue: number;
  vip_status: string | null;
}

interface FolioStay {
  id: string;
  confirmation_code: string;
  property_name: string;
  property_address: string;
  check_in_date: string | null;
  check_out_date: string | null;
  nights: number;
  num_guests: number;
  num_pets: number;
  status: string;
  booking_source: string;
  access_code: string | null;
  access_code_type: string;
  access_code_location: string;
  wifi_ssid: string;
  wifi_password: string;
  special_requests: string;
  internal_notes: string;
  streamline_notes: Array<Record<string, unknown>> | null;
}

interface FolioLineItem {
  label: string;
  amount_cents: number;
  category: string;
}

interface FolioSecurityDeposit {
  is_required: boolean;
  amount_cents: number;
  status: string;
  stripe_payment_intent: string | null;
  updated_at: string | null;
}

interface FolioFinancials {
  total_amount_cents: number;
  paid_amount_cents: number;
  balance_due_cents: number;
  nightly_rate_cents: number;
  cleaning_fee_cents: number;
  tax_amount_cents: number;
  currency: string;
  line_items: FolioLineItem[];
  security_deposit?: FolioSecurityDeposit;
  streamline_financial_detail?: Record<string, unknown>;
}

interface FolioMessage {
  id: string;
  direction: string;
  body: string;
  status: string;
  phone_from: string;
  phone_to: string;
  channel: string;
  is_auto_response: boolean;
  intent: string | null;
  sentiment: string | null;
  created_at: string | null;
}

interface FolioWorkOrder {
  id: string;
  ticket_number: string | null;
  title: string;
  priority: string | null;
  status: string;
  created_at: string | null;
}

interface FolioDamageClaim {
  id: string;
  claim_number: string | null;
  damage_description: string;
  estimated_cost: number;
  status: string;
  has_legal_draft: boolean;
  created_at: string | null;
}

interface FolioAgreement {
  id: string;
  status: string;
  signed_at: string | null;
  signer_name: string;
  agreement_type: string;
  has_content: boolean;
}

interface FolioLifecycle {
  pre_arrival_sent: boolean;
  digital_guide_sent: boolean;
  access_info_sent: boolean;
  mid_stay_checkin_sent: boolean;
  checkout_reminder_sent: boolean;
  post_stay_followup_sent: boolean;
}

interface ReservationFolio {
  guest: FolioGuest;
  stay: FolioStay;
  financials: FolioFinancials;
  messages: FolioMessage[];
  work_orders: FolioWorkOrder[];
  damage_claims: FolioDamageClaim[];
  agreement: FolioAgreement | null;
  lifecycle: FolioLifecycle;
  aggregation_errors: string[];
  custom_flags?: string[];
}

/* ── Helpers ────────────────────────────────────────────────────── */

function usd(amount: number | null | undefined): string {
  return `$${(amount ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function centsToUsd(cents: number | null | undefined): string {
  return usd((cents ?? 0) / 100);
}

function statusColor(status: string | null | undefined): string {
  const s = (status ?? "").toLowerCase();
  if (s === "confirmed" || s === "signed" || s === "paid") return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  if (s === "checked_in" || s === "active") return "bg-blue-500/15 text-blue-400 border-blue-500/30";
  if (s === "checked_out" || s === "completed") return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  if (s === "cancelled" || s === "overdue") return "bg-red-500/15 text-red-400 border-red-500/30";
  if (s === "draft_ready" || s === "reported") return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  return "bg-zinc-700/30 text-zinc-300 border-zinc-600/30";
}

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return d;
  }
}

function formatDateTime(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return d;
  }
}

/* ── Component Props ───────────────────────────────────────────── */

interface FolioSheetProps {
  reservationId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/* ── Main Component ────────────────────────────────────────────── */

export function FolioSheet({ reservationId, open, onOpenChange }: FolioSheetProps) {
  const [folio, setFolio] = useState<ReservationFolio | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchFolio = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ReservationFolio>(`/api/reservations/${id}/folio`);
      setFolio(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load folio";
      setError(msg);
      setFolio(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && reservationId) {
      fetchFolio(reservationId);
    }
    if (!open) {
      setFolio(null);
      setError(null);
    }
  }, [open, reservationId, fetchFolio]);

  const guest = folio?.guest;
  const stay = folio?.stay;
  const fin = folio?.financials;
  const lifecycle = folio?.lifecycle;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-3xl overflow-y-auto bg-zinc-950 border-zinc-800 text-white">
        <SheetHeader className="sr-only">
          <SheetTitle>
            {loading ? "Loading…" : `Reservation ${stay?.confirmation_code ?? ""}`}
          </SheetTitle>
          <SheetDescription>Reservation folio detail panel</SheetDescription>
        </SheetHeader>

        {error && (
          <div className="mt-4 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
            {error}
          </div>
        )}

        {loading && (
          <div className="mt-6 space-y-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full bg-zinc-800 rounded-lg" />
            ))}
          </div>
        )}

        {/* ── PINNED HERO DASHBOARD (always visible above tabs) ── */}
        {folio && !loading && (
          <>
            <div className="mt-2 p-6 rounded-2xl bg-zinc-900/50 border border-zinc-800/80">
              {/* Hero: Left/Right Split */}
              <div className="flex items-start justify-between gap-8">
                {/* LEFT — Guest identity, property, dates, badges */}
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex items-center gap-3">
                    <h2 className="text-xl font-semibold text-white truncate">
                      {guest?.first_name ?? ""} {guest?.last_name ?? ""}
                    </h2>
                    <Badge className={`shrink-0 ${statusColor(stay?.status)}`}>
                      {stay?.status ?? "unknown"}
                    </Badge>
                  </div>
                  <p className="text-sm text-zinc-400 truncate">
                    {stay?.property_name ?? "—"}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-zinc-500">
                    <span className="font-mono tracking-wide text-zinc-300">{stay?.confirmation_code ?? "—"}</span>
                    <span className="text-zinc-700">&bull;</span>
                    <span>{formatDate(stay?.check_in_date)} → {formatDate(stay?.check_out_date)}</span>
                    <span className="text-zinc-700">&bull;</span>
                    <span>{stay?.nights ?? 0} nights</span>
                  </div>

                  {/* System + Custom Flags */}
                  {(() => {
                    const flags: { label: string; color: string }[] = [];
                    const depositFlag = fin?.security_deposit?.is_required && fin?.security_deposit?.status === "none";
                    if (depositFlag) flags.push({ label: "DEPOSIT PENDING", color: "bg-amber-500/20 text-amber-400 border-amber-500/30" });
                    if ((fin?.balance_due_cents ?? 0) > 0) flags.push({ label: "BALANCE DUE", color: "bg-red-500/20 text-red-400 border-red-500/30" });
                    if ((folio.damage_claims?.length ?? 0) > 0) flags.push({ label: `${folio.damage_claims.length} DAMAGE CLAIM${folio.damage_claims.length > 1 ? "S" : ""}`, color: "bg-orange-500/20 text-orange-400 border-orange-500/30" });
                    if (folio.agreement && folio.agreement.status !== "signed") flags.push({ label: "AGREEMENT UNSIGNED", color: "bg-amber-500/20 text-amber-400 border-amber-500/30" });
                    if (folio.aggregation_errors && folio.aggregation_errors.length > 0) flags.push({ label: "PARTIAL DATA", color: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30" });
                    if (Array.isArray(folio.custom_flags)) {
                      folio.custom_flags.forEach((cf) => flags.push({ label: String(cf), color: "bg-purple-500/20 text-purple-400 border-purple-500/30" }));
                    }
                    if (flags.length === 0) return null;
                    return (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {flags.map((f) => (
                          <Badge key={f.label} className={`text-[10px] font-semibold ${f.color}`}>{f.label}</Badge>
                        ))}
                      </div>
                    );
                  })()}
                </div>

                {/* RIGHT — Financial summary block */}
                <div className="shrink-0 text-right space-y-1.5 pl-6 border-l border-zinc-800/60">
                  <p className="text-[10px] uppercase tracking-widest text-zinc-500 font-semibold">Balance Due</p>
                  <p className={`text-3xl font-bold tabular-nums leading-none ${(fin?.balance_due_cents ?? 0) > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                    {centsToUsd(fin?.balance_due_cents)}
                  </p>
                  <div className="pt-2 space-y-0.5">
                    <p className="text-xs text-zinc-500">Total <span className="text-zinc-300 font-medium ml-1">{centsToUsd(fin?.total_amount_cents)}</span></p>
                    <p className="text-xs text-zinc-500">Paid <span className="text-emerald-400 font-medium ml-1">{centsToUsd(fin?.paid_amount_cents)}</span></p>
                  </div>
                </div>
              </div>
            </div>

            <Tabs defaultValue="overview" className="mt-6">
              <TabsList className="grid w-full grid-cols-4 bg-zinc-900/80 border border-zinc-800 rounded-xl h-10">
                <TabsTrigger value="overview" className="rounded-lg data-[state=active]:bg-zinc-800 text-zinc-400 data-[state=active]:text-white text-sm">Overview</TabsTrigger>
                <TabsTrigger value="financials" className="rounded-lg data-[state=active]:bg-zinc-800 text-zinc-400 data-[state=active]:text-white text-sm">Financials</TabsTrigger>
                <TabsTrigger value="comms" className="rounded-lg data-[state=active]:bg-zinc-800 text-zinc-400 data-[state=active]:text-white text-sm">
                  Comms
                  {(folio.messages?.length ?? 0) > 0 && (
                    <span className="ml-1.5 inline-flex items-center justify-center h-5 min-w-5 px-1 rounded-full bg-emerald-500/20 text-emerald-400 text-[10px] font-medium">
                      {folio.messages.length}
                    </span>
                  )}
                </TabsTrigger>
                <TabsTrigger value="notes" className="rounded-lg data-[state=active]:bg-zinc-800 text-zinc-400 data-[state=active]:text-white text-sm">
                  Notes
                  {(() => {
                    const noteCount = (stay?.internal_notes?.trim() ? 1 : 0) + (Array.isArray(stay?.streamline_notes) ? stay!.streamline_notes!.length : 0);
                    return noteCount > 0 ? (
                      <span className="ml-1.5 inline-flex items-center justify-center h-5 min-w-5 px-1 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-medium">
                        {noteCount}
                      </span>
                    ) : null;
                  })()}
                </TabsTrigger>
              </TabsList>

            {/* ── OVERVIEW TAB ── */}
            <TabsContent value="overview" className="mt-6 space-y-5">
              {/* Guest Card */}
              <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Guest</h3>
                <p className="text-base font-medium">
                  {guest?.first_name ?? ""} {guest?.last_name ?? ""}
                  {guest?.vip_status && <Badge className="ml-2 bg-amber-500/20 text-amber-400 border-amber-500/30 text-[10px]">{guest.vip_status}</Badge>}
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-zinc-400">
                  <span>{guest?.email || "—"}</span>
                  <span>{guest?.phone_number || "—"}</span>
                  <span>Stays: {guest?.lifetime_stays ?? 0}</span>
                  <span>LTV: {usd(guest?.lifetime_revenue)}</span>
                </div>
              </section>

              {/* Stay Card */}
              <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Stay Details</h3>
                <div className="flex items-center gap-2 mb-2">
                  <Badge className={statusColor(stay?.status)}>{stay?.status ?? "unknown"}</Badge>
                  <span className="text-sm text-zinc-400">{stay?.booking_source || "Direct"}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm text-zinc-400">
                  <span>Guests: {stay?.num_guests ?? 0}</span>
                  <span>Pets: {stay?.num_pets ?? 0}</span>
                  {stay?.access_code && (
                    <div className="col-span-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                      <span className="text-xs text-emerald-500 font-semibold uppercase">Door Code</span>
                      <p className="font-mono text-lg text-emerald-400">{stay.access_code}</p>
                      {stay.access_code_location && <p className="text-xs text-zinc-500">{stay.access_code_location}</p>}
                    </div>
                  )}
                  {(stay?.wifi_ssid || stay?.wifi_password) && (
                    <div className="col-span-2 p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                      <span className="text-xs text-blue-500 font-semibold uppercase">WiFi</span>
                      <p className="text-zinc-300">{stay.wifi_ssid ?? "—"} <span className="text-zinc-500">/ pw:</span> <span className="font-mono text-blue-300">{stay.wifi_password ?? "—"}</span></p>
                    </div>
                  )}
                  {stay?.special_requests && <p className="col-span-2 text-zinc-300 italic">&ldquo;{stay.special_requests}&rdquo;</p>}
                </div>
              </section>

              {/* Agreement Card */}
              {folio.agreement && (
                <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Rental Agreement</h3>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge className={statusColor(folio.agreement.status)}>{folio.agreement.status}</Badge>
                      {folio.agreement.signed_at && <span className="text-sm text-zinc-400">Signed {formatDate(folio.agreement.signed_at)}</span>}
                    </div>
                    {folio.agreement.has_content && (
                      <button
                        onClick={() => {
                          window.open(`/api/reservations/${stay?.id}/agreement.pdf`, "_blank");
                        }}
                        className="px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-xs font-medium hover:bg-emerald-500/25 transition-colors"
                      >
                        View PDF
                      </button>
                    )}
                  </div>
                  {folio.agreement.signer_name && <p className="mt-1 text-sm text-zinc-400">By: {folio.agreement.signer_name}</p>}
                </section>
              )}

              {/* Lifecycle Card */}
              <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Communication Lifecycle</h3>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  {[
                    ["Pre-Arrival", lifecycle?.pre_arrival_sent],
                    ["Digital Guide", lifecycle?.digital_guide_sent],
                    ["Access Info", lifecycle?.access_info_sent],
                    ["Mid-Stay Check-in", lifecycle?.mid_stay_checkin_sent],
                    ["Checkout Reminder", lifecycle?.checkout_reminder_sent],
                    ["Post-Stay Follow-up", lifecycle?.post_stay_followup_sent],
                  ].map(([label, sent]) => (
                    <div key={label as string} className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${sent ? "bg-emerald-400" : "bg-zinc-600"}`} />
                      <span className={sent ? "text-zinc-300" : "text-zinc-500"}>{label as string}</span>
                    </div>
                  ))}
                </div>
              </section>

              {/* Work Orders */}
              {Array.isArray(folio.work_orders) && folio.work_orders.length > 0 && (
                <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
                    Work Orders ({folio.work_orders.length})
                  </h3>
                  <div className="space-y-2">
                    {folio.work_orders.map((wo) => (
                      <div key={wo.id} className="flex items-center justify-between text-sm">
                        <span className="text-zinc-300">{wo.title || wo.ticket_number || "Work Order"}</span>
                        <Badge className={statusColor(wo.status)}>{wo.status}</Badge>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Damage Claims */}
              {Array.isArray(folio.damage_claims) && folio.damage_claims.length > 0 && (
                <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
                    Damage Claims ({folio.damage_claims.length})
                  </h3>
                  <div className="space-y-2">
                    {folio.damage_claims.map((dc) => (
                      <div key={dc.id} className="flex items-center justify-between text-sm">
                        <span className="text-zinc-300 truncate max-w-[300px]">{dc.damage_description || "Claim"}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-zinc-400">{usd(dc.estimated_cost)}</span>
                          <Badge className={statusColor(dc.status)}>{dc.status}</Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </TabsContent>

            {/* ── FINANCIALS TAB ── */}
            <TabsContent value="financials" className="mt-6 space-y-5">
              {/* Summary KPIs */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  ["Total", fin?.total_amount_cents],
                  ["Paid", fin?.paid_amount_cents],
                  ["Balance", fin?.balance_due_cents],
                ].map(([label, val]) => (
                  <div key={label as string} className="p-3 rounded-xl bg-zinc-900 border border-zinc-800 text-center">
                    <p className="text-xs text-zinc-500 uppercase">{label as string}</p>
                    <p className={`text-lg font-semibold ${(label as string) === "Balance" && (val as number ?? 0) > 0 ? "text-amber-400" : "text-white"}`}>
                      {centsToUsd(val as number)}
                    </p>
                  </div>
                ))}
              </div>

              {/* Line Items */}
              <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Folio Line Items</h3>
                {Array.isArray(fin?.line_items) && fin!.line_items.length > 0 ? (
                  <div className="space-y-2">
                    {fin!.line_items.map((item, i) => (
                      <div key={`${item.label}-${i}`} className="flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2">
                          <span className="text-zinc-300">{item.label}</span>
                          <Badge variant="outline" className="text-[10px] border-zinc-700 text-zinc-500">{item.category}</Badge>
                        </div>
                        <span className={item.amount_cents < 0 ? "text-emerald-400" : "text-white"}>
                          {item.amount_cents < 0 ? "−" : ""}{centsToUsd(Math.abs(item.amount_cents))}
                        </span>
                      </div>
                    ))}
                    <div className="pt-2 mt-2 border-t border-zinc-800 flex items-center justify-between text-sm font-semibold">
                      <span className="text-zinc-300">Net Total</span>
                      <span className="text-white">{centsToUsd(fin?.total_amount_cents)}</span>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500">No line items available</p>
                )}
              </section>

              {/* Security Deposit Card */}
              <SecurityDepositCard
                deposit={fin?.security_deposit ?? null}
                reservationId={stay?.id ?? null}
                checkInDate={stay?.check_in_date ?? null}
                onToggled={(updated) => {
                  if (!folio || !fin) return;
                  setFolio({
                    ...folio,
                    financials: {
                      ...fin,
                      security_deposit: {
                        is_required: updated.security_deposit_required,
                        amount: updated.security_deposit_amount,
                        status: updated.security_deposit_status,
                        stripe_payment_intent: fin.security_deposit?.stripe_payment_intent ?? null,
                        updated_at: new Date().toISOString(),
                      },
                    },
                  });
                }}
              />

              {/* Streamline Detail (raw JSONB) */}
              {fin?.streamline_financial_detail && (
                <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Streamline Financial Detail</h3>
                  <pre className="text-xs text-zinc-400 overflow-x-auto max-h-48 whitespace-pre-wrap">
                    {JSON.stringify(fin.streamline_financial_detail, null, 2)}
                  </pre>
                </section>
              )}
            </TabsContent>

            {/* ── COMMUNICATIONS TAB ── */}
            <TabsContent value="comms" className="mt-6 space-y-3">
              {!Array.isArray(folio.messages) || folio.messages.length === 0 ? (
                <div className="p-8 text-center text-zinc-500">
                  <p className="text-lg mb-1">No messages</p>
                  <p className="text-sm">No SMS or email communications recorded for this reservation.</p>
                </div>
              ) : (
                folio.messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`p-3 rounded-xl border text-sm ${
                      msg.direction === "outbound"
                        ? "bg-emerald-500/5 border-emerald-500/20 ml-6"
                        : "bg-zinc-900 border-zinc-800 mr-6"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="outline"
                          className={
                            msg.direction === "outbound"
                              ? "text-emerald-400 border-emerald-500/30 text-[10px]"
                              : "text-blue-400 border-blue-500/30 text-[10px]"
                          }
                        >
                          {msg.direction === "outbound" ? "↑ Sent" : "↓ Received"}
                        </Badge>
                        {msg.is_auto_response && (
                          <Badge variant="outline" className="text-purple-400 border-purple-500/30 text-[10px]">Auto</Badge>
                        )}
                        {msg.intent && (
                          <Badge variant="outline" className="text-zinc-400 border-zinc-600/30 text-[10px]">{msg.intent}</Badge>
                        )}
                        {msg.sentiment && (
                          <Badge
                            variant="outline"
                            className={`text-[10px] ${
                              msg.sentiment === "positive" ? "text-emerald-400 border-emerald-500/30"
                              : msg.sentiment === "negative" ? "text-red-400 border-red-500/30"
                              : "text-zinc-400 border-zinc-600/30"
                            }`}
                          >
                            {msg.sentiment}
                          </Badge>
                        )}
                      </div>
                      <span className="text-[11px] text-zinc-500">{formatDateTime(msg.created_at)}</span>
                    </div>
                    <p className="text-zinc-300 whitespace-pre-wrap">{msg.body}</p>
                    <p className="mt-1 text-[11px] text-zinc-600">
                      {msg.phone_from} → {msg.phone_to}
                    </p>
                  </div>
                ))
              )}

              {/* Staff Notes reference — full notes are in Notes tab */}
              {Array.isArray(stay?.streamline_notes) && stay!.streamline_notes!.length > 0 && (
                <div className="p-3 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-500 text-center">
                  {stay!.streamline_notes!.length} staff note{stay!.streamline_notes!.length !== 1 ? "s" : ""} — see Notes tab
                </div>
              )}
            </TabsContent>

            {/* ── NOTES TAB ── */}
            <TabsContent value="notes" className="mt-6 space-y-5">
              {/* Internal Notes */}
              <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Internal Notes</h3>
                {stay?.internal_notes && stay.internal_notes.trim().length > 0 ? (
                  <p className="text-sm text-zinc-300 whitespace-pre-wrap">{stay.internal_notes}</p>
                ) : (
                  <p className="text-sm text-zinc-500 italic">No internal notes recorded.</p>
                )}
              </section>

              {/* Streamline Staff Notes (PMS) */}
              <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
                  Staff Notes (PMS)
                  {Array.isArray(stay?.streamline_notes) && stay!.streamline_notes!.length > 0 && (
                    <span className="ml-2 text-zinc-400 normal-case font-normal">
                      ({stay!.streamline_notes!.length})
                    </span>
                  )}
                </h3>
                {Array.isArray(stay?.streamline_notes) && stay!.streamline_notes!.length > 0 ? (
                  <div className="space-y-2">
                    {stay!.streamline_notes!.map((note, i) => (
                      <div key={i} className="text-sm p-3 rounded-lg bg-zinc-800/50">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-zinc-400 text-xs font-medium">{String(note?.processor_name ?? "Staff")}</span>
                          <span className="text-zinc-500 text-xs">{String(note?.creation_date ?? "")}</span>
                        </div>
                        <p className="text-zinc-300 whitespace-pre-wrap">{String(note?.message ?? "")}</p>
                        {note?.schedule_follow_up ? (
                          <p className="mt-1 text-xs text-amber-400">Follow-up: {String(note.schedule_follow_up)}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500 italic">No staff notes from Streamline PMS.</p>
                )}
              </section>

              {/* Special Requests */}
              {stay?.special_requests && stay.special_requests.trim().length > 0 && (
                <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Special Requests</h3>
                  <p className="text-sm text-zinc-300 italic">&ldquo;{stay.special_requests}&rdquo;</p>
                </section>
              )}

              {/* Aggregation Errors / Warnings */}
              {Array.isArray(folio.aggregation_errors) && folio.aggregation_errors.length > 0 && (
                <section className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-500 mb-3">Data Warnings</h3>
                  <ul className="space-y-1">
                    {folio.aggregation_errors.map((err, i) => (
                      <li key={i} className="text-sm text-amber-300 flex items-start gap-2">
                        <span className="mt-1 h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />
                        {err}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </TabsContent>
          </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}


/* ── Security Deposit Card ──────────────────────────────────────── */

interface DepositToggleResponse {
  reservation_id: string;
  security_deposit_required: boolean;
  security_deposit_amount: number;
  security_deposit_status: string;
  system_flag: string | null;
}

const DEPOSIT_STATUS_STYLES: Record<string, string> = {
  none: "bg-zinc-700/30 text-zinc-400 border-zinc-600/30",
  scheduled: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  authorized: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  captured: "bg-red-500/15 text-red-400 border-red-500/30",
  released: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

function SecurityDepositCard({
  deposit,
  reservationId,
  checkInDate,
  onToggled,
}: {
  deposit: FolioSecurityDeposit | null;
  reservationId: string | null;
  checkInDate: string | null;
  onToggled: (resp: DepositToggleResponse) => void;
}) {
  const [toggling, setToggling] = useState(false);
  const [depositAction, setDepositAction] = useState<"initiate" | "capture" | "release" | null>(null);

  const isRequired = deposit?.is_required ?? false;
  const amount = (deposit?.amount_cents ?? 50000) / 100;
  const status = deposit?.status ?? "none";
  const showPendingFlag = isRequired && status === "none";

  const handleDepositAction = async (action: "initiate" | "capture" | "release") => {
    if (!reservationId || depositAction) return;
    setDepositAction(action);
    try {
      const resp = await api.post<{ security_deposit_status: string; stripe_pi?: string; amount?: number }>(
        `/api/reservations/${reservationId}/deposit/${action}`
      );
      onToggled({
        reservation_id: reservationId,
        security_deposit_required: isRequired,
        security_deposit_amount: resp.amount ?? amount,
        security_deposit_status: resp.security_deposit_status,
      } as DepositToggleResponse);
    } catch {
      // Error handled by api wrapper
    } finally {
      setDepositAction(null);
    }
  };

  const handleToggle = async () => {
    if (!reservationId || toggling) return;
    setToggling(true);
    try {
      const resp = await api.post<DepositToggleResponse>(
        `/api/reservations/${reservationId}/toggle-deposit`
      );
      onToggled(resp);
    } catch {
      // Silently fail — the toggle state won't change in the UI
    } finally {
      setToggling(false);
    }
  };

  return (
    <section className="p-4 rounded-xl bg-zinc-900 border border-zinc-800">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Security Deposit
        </h3>
        {showPendingFlag && (
          <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[10px] animate-pulse">
            DEPOSIT PENDING
          </Badge>
        )}
      </div>

      {/* Toggle Row */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex-1 min-w-0 mr-4">
          <Label htmlFor="deposit-toggle" className="text-sm text-zinc-300 cursor-pointer">
            Require {usd(amount)} deposit for this stay
          </Label>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            Card vaulted at booking. Hold executes T-24h before check-in.
          </p>
        </div>
        <Switch
          id="deposit-toggle"
          checked={isRequired}
          onCheckedChange={handleToggle}
          disabled={toggling}
          className={`shrink-0 data-[state=checked]:bg-emerald-500 data-[state=unchecked]:bg-zinc-700 ${toggling ? "opacity-50" : ""}`}
        />
      </div>

      {/* Status Display (only when deposit is required) */}
      {isRequired && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge className={DEPOSIT_STATUS_STYLES[status] ?? DEPOSIT_STATUS_STYLES.none}>
              {status.toUpperCase()}
            </Badge>
            <span className="text-sm font-semibold text-white">{usd(amount)}</span>
          </div>

          {/* Contextual Status Messages */}
          {status === "none" && checkInDate && (
            <p className="text-xs text-amber-400">
              Awaiting card vault. Hold will be scheduled automatically for{" "}
              {formatDate(checkInDate)} (T-24h).
            </p>
          )}
          {status === "scheduled" && (
            <p className="text-xs text-blue-400">
              Card vaulted. {usd(amount)} hold will execute 24 hours prior to arrival.
            </p>
          )}
          {(status === "none" || status === "pending" || status === "scheduled") && isRequired && (
            <div className="pt-1">
              <button
                disabled={!!depositAction}
                onClick={() => handleDepositAction("initiate")}
                className="px-3 py-1.5 rounded-lg bg-blue-500/15 text-blue-400 border border-blue-500/30 text-xs font-medium hover:bg-blue-500/25 transition-colors disabled:opacity-50"
              >
                {depositAction === "initiate" ? "Initiating…" : "Initiate Hold"}
              </button>
            </div>
          )}
          {status === "authorized" && (
            <div className="space-y-2">
              <p className="text-xs text-amber-400">
                {usd(amount)} hold active on guest&apos;s card. Expires in 7 days from authorization.
              </p>
              <div className="flex gap-2">
                <button
                  disabled={!!depositAction}
                  onClick={() => handleDepositAction("capture")}
                  className="px-3 py-1.5 rounded-lg bg-red-500/15 text-red-400 border border-red-500/30 text-xs font-medium hover:bg-red-500/25 transition-colors disabled:opacity-50"
                >
                  {depositAction === "capture" ? "Capturing…" : "Capture for Damage"}
                </button>
                <button
                  disabled={!!depositAction}
                  onClick={() => handleDepositAction("release")}
                  className="px-3 py-1.5 rounded-lg bg-zinc-700/50 text-zinc-400 border border-zinc-600/30 text-xs font-medium hover:bg-zinc-700 transition-colors disabled:opacity-50"
                >
                  {depositAction === "release" ? "Releasing…" : "Release Hold"}
                </button>
              </div>
            </div>
          )}
          {status === "captured" && (
            <p className="text-xs text-red-400">
              {usd(amount)} captured from guest&apos;s card for damage claim.
            </p>
          )}
          {status === "released" && (
            <p className="text-xs text-emerald-400">
              Hold released. No charges applied.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
