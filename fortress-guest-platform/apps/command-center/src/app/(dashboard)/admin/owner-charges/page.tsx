"use client";

import { useState, useMemo, useRef } from "react";
import {
  useAdminCharges,
  useCreateOwnerCharge,
  useUpdateOwnerCharge,
  useVoidOwnerCharge,
  useAdminOPAs,
  useVendors,
  type AdminOPA,
  type Vendor,
} from "@/lib/hooks";
import type { OwnerCharge, ChargeListFilters, CreateOwnerChargeRequest } from "@/lib/types";
import {
  OWNER_CHARGE_CODES,
  CHARGE_CODE_PLACEHOLDER,
  PAYMENT_CODES,
  CREDIT_CODES,
  chargeCodeLabel,
} from "@/lib/owner-charge-codes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertTriangle,
  Loader2,
  PlusCircle,
  ArrowDownCircle,
  CreditCard,
  Pencil,
  Ban,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Controls which action mode the ChargeModal is in for a new entry. */
type ModalMode = "charge" | "payment" | "credit";

/** Client-side display filter applied to the loaded charges table. */
type TypeFilter = "all" | "charges" | "payments" | "credits";

// ── Helpers ───────────────────────────────────────────────────────────────────

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Format a Decimal string as currency. Negative values shown as ($x.xx). */
function fmtCurrency(val: string | null | undefined): string {
  if (!val) return "—";
  const n = parseFloat(val);
  if (isNaN(n)) return val;
  if (n < 0) {
    const abs = Math.abs(n).toLocaleString("en-US", { style: "currency", currency: "USD" });
    return `(${abs})`;
  }
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function isVoided(c: OwnerCharge): boolean {
  return !!c.voided_at;
}

// ── OPA display helper ────────────────────────────────────────────────────────

function opaLabel(opa: AdminOPA): string {
  const name = opa.owner_name ?? "Unknown";
  const prop = opa.property_name ?? opa.property_id.slice(0, 8);
  return `${name} — ${prop}`;
}

// ── Charge Modal ──────────────────────────────────────────────────────────────

interface ChargeModalProps {
  open: boolean;
  mode: ModalMode;
  onClose: () => void;
  opas: AdminOPA[];
  vendors: Vendor[];
  existing?: OwnerCharge | null;
}

const MODE_CONFIG: Record<ModalMode, {
  title: string;
  amountLabel: string;
  amountHint: string;
  descPlaceholder: string;
  defaultCode: string;
}> = {
  charge: {
    title: "Post Owner Charge",
    amountLabel: "Amount (debit to owner)",
    amountHint: "+ charge  /  − credit",
    descPlaceholder: "Appears on owner statement PDF…",
    defaultCode: "",
  },
  payment: {
    title: "Receive Owner Payment",
    amountLabel: "Payment Amount (credit to owner)",
    amountHint: "Enter positive — stored as negative",
    descPlaceholder: "Payment received from owner",
    defaultCode: "owner_payment_received",
  },
  credit: {
    title: "Credit Owner Account",
    amountLabel: "Credit Amount (credit to owner)",
    amountHint: "Enter positive — stored as negative",
    descPlaceholder: "Account adjustment / credit",
    defaultCode: "credit_from_management",
  },
};

function ChargeModal({ open, mode, onClose, opas, vendors, existing }: ChargeModalProps) {
  const isEdit = !!existing;
  const cfg = MODE_CONFIG[mode];

  // Default transaction type pre-selected per mode
  const defaultCode = existing?.transaction_type ?? cfg.defaultCode;

  const [opaId, setOpaId] = useState<string>(existing ? String(existing.owner_payout_account_id) : "");
  const [txType, setTxType] = useState<string>(defaultCode);
  const [description, setDescription] = useState<string>(existing?.description ?? "");
  const [postedDate, setPostedDate] = useState<string>(
    existing?.posting_date ? existing.posting_date.slice(0, 10) : todayIso()
  );
  // For edit: show existing amount as-is. For payment/credit create: user enters positive.
  const [amount, setAmount] = useState<string>(
    existing ? String(Math.abs(parseFloat(existing.amount))) : ""
  );
  const [referenceId, setReferenceId] = useState<string>(existing?.reference_id ?? "");
  const [formError, setFormError] = useState<string | null>(null);

  // Vendor + markup state (I.1a)
  const [showVendor, setShowVendor] = useState<boolean>(!!existing?.vendor_id);
  const [selectedTrade, setSelectedTrade] = useState<string>("");
  const [vendorId, setVendorId] = useState<string>(existing?.vendor_id ?? "");
  const [vendorAmount, setVendorAmount] = useState<string>(
    existing?.vendor_amount ? String(parseFloat(existing.vendor_amount)) : ""
  );
  const [markupPct, setMarkupPct] = useState<string>(
    existing?.markup_percentage ? String(parseFloat(existing.markup_percentage)) : "0"
  );

  const createMutation = useCreateOwnerCharge();
  const updateMutation = useUpdateOwnerCharge();
  const isLoading = createMutation.isPending || updateMutation.isPending;
  const sendNotifRef = useRef(false);

  // Codes available in dropdown — filtered by mode for payment/credit
  const availableCodes = useMemo(() => {
    if (!isEdit && mode === "payment") return OWNER_CHARGE_CODES.filter((c) => PAYMENT_CODES.has(c.value));
    if (!isEdit && mode === "credit") return OWNER_CHARGE_CODES.filter((c) => CREDIT_CODES.has(c.value));
    return OWNER_CHARGE_CODES;
  }, [isEdit, mode]);

  // Derived: distinct trades and filtered vendor list
  const trades = useMemo(
    () => [...new Set(vendors.map((v) => v.trade).filter(Boolean))].sort() as string[],
    [vendors]
  );
  const filteredVendors = useMemo(
    () => (selectedTrade ? vendors.filter((v) => v.trade === selectedTrade) : vendors),
    [vendors, selectedTrade]
  );

  // Computed owner amount when vendor is used (always positive — vendor amounts are charges)
  const computedOwnerAmount = useMemo(() => {
    const va = parseFloat(vendorAmount);
    const mp = parseFloat(markupPct || "0");
    if (!isNaN(va) && va > 0 && !isNaN(mp)) {
      return (va * (1 + mp / 100)).toFixed(2);
    }
    return null;
  }, [vendorAmount, markupPct]);

  function resetForm() {
    setOpaId("");
    setTxType(cfg.defaultCode);
    setDescription("");
    setPostedDate(todayIso());
    setAmount("");
    setReferenceId("");
    setFormError(null);
    setShowVendor(false);
    setSelectedTrade("");
    setVendorId("");
    setVendorAmount("");
    setMarkupPct("0");
  }

  function handleClose() { resetForm(); onClose(); }

  async function handleSubmit(e: React.FormEvent) {
    const sendNotification = sendNotifRef.current;
    sendNotifRef.current = false;
    e.preventDefault();
    setFormError(null);

    if (!isEdit && !opaId) { setFormError("Select an owner / property."); return; }
    if (!isEdit && !txType) { setFormError("Select a transaction type."); return; }
    if (!description.trim()) { setFormError("Description is required."); return; }
    if (!postedDate) { setFormError("Posted date is required."); return; }

    // Vendor validation
    if (showVendor && !isEdit) {
      if (!vendorId) { setFormError("Select a vendor or collapse the vendor section."); return; }
      const va = parseFloat(vendorAmount);
      if (isNaN(va) || va <= 0) { setFormError("Vendor amount must be a positive number."); return; }
    } else {
      const amountNum = parseFloat(amount);
      if (!isEdit) {
        if (mode === "charge") {
          if (isNaN(amountNum) || amountNum === 0) {
            setFormError("Amount must be a non-zero number."); return;
          }
        } else {
          // payment / credit: user enters positive
          if (isNaN(amountNum) || amountNum <= 0) {
            setFormError("Enter a positive amount."); return;
          }
        }
      }
    }

    try {
      if (isEdit && existing) {
        // Edit: preserve sign from the existing amount
        const existingSign = parseFloat(existing.amount) < 0 ? -1 : 1;
        await updateMutation.mutateAsync({
          chargeId: existing.id,
          description: description.trim(),
          posting_date: postedDate,
          ...(showVendor && vendorAmount
            ? {
                vendor_amount: parseFloat(vendorAmount),
                markup_percentage: parseFloat(markupPct || "0"),
              }
            : { amount: existingSign * Math.abs(parseFloat(amount)) }),
          reference_id: referenceId.trim() || undefined,
        });
      } else {
        // For payment/credit modes: negate the user-entered positive value
        const rawAmount = parseFloat(amount);
        const finalAmount =
          (mode === "payment" || mode === "credit") && !showVendor
            ? -Math.abs(rawAmount)
            : rawAmount;

        const body: CreateOwnerChargeRequest = {
          owner_payout_account_id: parseInt(opaId, 10),
          posting_date: postedDate,
          transaction_type: txType,
          description: description.trim(),
          reference_id: referenceId.trim() || undefined,
          send_notification: sendNotification,
          ...(showVendor && vendorId
            ? {
                vendor_id: vendorId,
                vendor_amount: parseFloat(vendorAmount),
                markup_percentage: parseFloat(markupPct || "0"),
              }
            : { amount: finalAmount }),
        };
        const result = await createMutation.mutateAsync(body);

        if (sendNotification) {
          const ownerEmail = opas.find((o) => String(o.id) === opaId)?.owner_email ?? "owner";
          if (result.notification_sent) {
            toast.success(`Posted. Notification sent to ${ownerEmail}.`);
          } else {
            toast.warning(
              `Posted but notification failed: ${result.notification_error ?? "unknown error"}.`
            );
          }
        }
      }
      handleClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to save");
    }
  }

  const selectedOpa = opas.find((o) => String(o.id) === opaId);
  const selectedVendor = vendors.find((v) => v.id === vendorId);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {mode === "payment" ? (
              <ArrowDownCircle className="h-5 w-5 text-emerald-600" />
            ) : mode === "credit" ? (
              <CreditCard className="h-5 w-5 text-blue-600" />
            ) : (
              <PlusCircle className="h-5 w-5" />
            )}
            {isEdit ? "Edit Entry" : cfg.title}
          </DialogTitle>
        </DialogHeader>

        {/* Payment/credit banner */}
        {!isEdit && (mode === "payment" || mode === "credit") && (
          <div className="rounded-md bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-400">
            {mode === "payment"
              ? "Stored as a negative charge — reduces owner's outstanding balance."
              : "Credit adjustment — stored as negative, increases owner's closing balance."}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 pt-2">

          {/* Owner / Property */}
          {!isEdit && (
            <div className="space-y-1.5">
              <Label>Owner / Property <span className="text-red-500">*</span></Label>
              <Select value={opaId} onValueChange={setOpaId}>
                <SelectTrigger><SelectValue placeholder="Select owner…" /></SelectTrigger>
                <SelectContent>
                  {opas.map((o) => (
                    <SelectItem key={o.id} value={String(o.id)}>{opaLabel(o)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedOpa && !selectedOpa.stripe_account_id && (
                <p className="text-xs text-amber-600 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />Stripe not linked — backend may reject posting.
                </p>
              )}
            </div>
          )}
          {isEdit && (
            <div className="rounded-md bg-muted/50 p-2 text-sm text-muted-foreground">
              {existing?.owner_name} — {existing?.property_name}
            </div>
          )}

          {/* Transaction Type */}
          {!isEdit && (
            <div className="space-y-1.5">
              <Label>Transaction Type <span className="text-red-500">*</span></Label>
              <Select value={txType} onValueChange={setTxType}>
                <SelectTrigger><SelectValue placeholder={CHARGE_CODE_PLACEHOLDER} /></SelectTrigger>
                <SelectContent>
                  {availableCodes.map((c) => (
                    <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {isEdit && (
            <div className="space-y-1.5">
              <Label>Transaction Type</Label>
              <div className="rounded-md border bg-muted/50 px-3 py-2 text-sm">
                {chargeCodeLabel(existing?.transaction_type ?? "")}
              </div>
              <p className="text-xs text-muted-foreground">Cannot be changed after posting.</p>
            </div>
          )}

          {/* Description */}
          <div className="space-y-1.5">
            <Label>Description <span className="text-red-500">*</span></Label>
            <Textarea
              rows={2}
              maxLength={500}
              placeholder={cfg.descPlaceholder}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            {selectedVendor && !description.includes(selectedVendor.name) && (
              <p className="text-xs text-muted-foreground">
                Vendor name will be appended on PDF: &ldquo;{description || "…"} — {selectedVendor.name}&rdquo;
              </p>
            )}
          </div>

          {/* Vendor section (collapsible, optional — available in all modes) */}
          {!isEdit && (
            <div className="rounded-md border">
              <button
                type="button"
                className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium hover:bg-muted/50 transition-colors"
                onClick={() => {
                  setShowVendor(!showVendor);
                  if (showVendor) { setVendorId(""); setVendorAmount(""); setMarkupPct("0"); }
                }}
              >
                <span>Vendor &amp; Markup <span className="text-muted-foreground font-normal">(optional)</span></span>
                {showVendor ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
              {showVendor && (
                <div className="px-3 pb-3 space-y-3 border-t pt-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Trade</Label>
                    <Select
                      value={selectedTrade}
                      onValueChange={(v) => { setSelectedTrade(v); setVendorId(""); }}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="All trades" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="">All trades</SelectItem>
                        {trades.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Vendor <span className="text-red-500">*</span></Label>
                    <Select value={vendorId} onValueChange={setVendorId}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select vendor…" />
                      </SelectTrigger>
                      <SelectContent>
                        {filteredVendors.map((v) => (
                          <SelectItem key={v.id} value={v.id}>
                            {v.name}
                            {v.trade ? (
                              <span className="text-muted-foreground ml-1">({v.trade})</span>
                            ) : null}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-xs">Vendor Amount (USD) <span className="text-red-500">*</span></Label>
                      <Input
                        type="number" step="0.01" placeholder="100.00"
                        className="h-8 text-xs"
                        value={vendorAmount}
                        onChange={(e) => setVendorAmount(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Markup %</Label>
                      <Input
                        type="number" step="0.01" min="0" max="100" placeholder="0"
                        className="h-8 text-xs"
                        value={markupPct}
                        onChange={(e) => setMarkupPct(e.target.value)}
                      />
                    </div>
                  </div>
                  {computedOwnerAmount && (
                    <div className="rounded bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 px-3 py-2">
                      <span className="text-xs text-muted-foreground">Owner amount: </span>
                      <span className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
                        ${computedOwnerAmount}
                      </span>
                      <span className="text-xs text-muted-foreground ml-2">
                        (= ${vendorAmount} × {(1 + parseFloat(markupPct || "0") / 100).toFixed(4)})
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {isEdit && existing?.vendor_id && (
            <div className="rounded-md bg-muted/50 p-2 text-sm space-y-1">
              <div>
                <span className="text-muted-foreground text-xs">Vendor:</span>{" "}
                {existing.vendor_name ?? existing.vendor_id.slice(0, 8)}
              </div>
              <div>
                <span className="text-muted-foreground text-xs">Vendor Amount:</span>{" "}
                ${existing.vendor_amount ? parseFloat(existing.vendor_amount).toFixed(2) : "—"}
              </div>
              <div>
                <span className="text-muted-foreground text-xs">Markup:</span>{" "}
                {parseFloat(existing.markup_percentage).toFixed(2)}%
              </div>
            </div>
          )}

          {/* Posted Date + Amount */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Posted Date <span className="text-red-500">*</span></Label>
              <Input
                type="date"
                value={postedDate}
                onChange={(e) => setPostedDate(e.target.value)}
              />
            </div>
            {(!showVendor || isEdit) && (
              <div className="space-y-1.5">
                <Label>{cfg.amountLabel} <span className="text-red-500">*</span></Label>
                <Input
                  type="number"
                  step="0.01"
                  min={mode !== "charge" && !isEdit ? "0.01" : undefined}
                  placeholder="100.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">{cfg.amountHint}</p>
              </div>
            )}
            {showVendor && !isEdit && computedOwnerAmount && (
              <div className="space-y-1.5">
                <Label>Owner Amount</Label>
                <Input value={`$${computedOwnerAmount}`} disabled className="bg-muted/50" />
              </div>
            )}
          </div>

          {/* W.O. / REF # */}
          <div className="space-y-1.5">
            <Label>W.O. / REF # <span className="text-muted-foreground">(optional)</span></Label>
            <Input
              placeholder="Work order or reference number"
              maxLength={100}
              value={referenceId}
              onChange={(e) => setReferenceId(e.target.value)}
            />
          </div>

          {formError && (
            <p className="text-sm text-red-500 flex items-center gap-1">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />{formError}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2 flex-wrap">
            <Button type="button" variant="ghost" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            {!isEdit && mode === "charge" && (
              <Button
                type="submit"
                variant="outline"
                disabled={isLoading}
                onClick={() => { sendNotifRef.current = true; }}
              >
                {isLoading && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
                Email and Close
              </Button>
            )}
            <Button
              type="submit"
              disabled={isLoading}
              onClick={() => { sendNotifRef.current = false; }}
            >
              {isLoading && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              {isEdit ? "Save Changes" : "Save and Close"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Void Modal ────────────────────────────────────────────────────────────────

interface VoidModalProps {
  charge: OwnerCharge | null;
  onClose: () => void;
}

function VoidModal({ charge, onClose }: VoidModalProps) {
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const voidMutation = useVoidOwnerCharge();

  function handleClose() {
    setReason("");
    setFormError(null);
    onClose();
  }

  async function handleVoid(e: React.FormEvent) {
    e.preventDefault();
    if (!charge) return;
    if (!reason.trim()) { setFormError("Void reason is required."); return; }
    try {
      await voidMutation.mutateAsync({ chargeId: charge.id, void_reason: reason.trim() });
      handleClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Void failed");
    }
  }

  const amountNum = charge ? parseFloat(charge.amount) : 0;
  const isCredit = amountNum < 0;

  return (
    <Dialog open={!!charge} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600">
            <Ban className="h-5 w-5" />
            Void {isCredit ? "Payment / Credit" : "Charge"}
          </DialogTitle>
        </DialogHeader>
        {charge && (
          <form onSubmit={handleVoid} className="space-y-4 pt-2">
            <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
              <div><span className="text-muted-foreground">Owner:</span> {charge.owner_name}</div>
              <div><span className="text-muted-foreground">Type:</span> {charge.transaction_type_display}</div>
              <div><span className="text-muted-foreground">Amount:</span>{" "}
                <span className={isCredit ? "text-emerald-600" : ""}>{fmtCurrency(charge.amount)}</span>
              </div>
              <div><span className="text-muted-foreground">Posted:</span> {fmtDate(charge.posting_date)}</div>
              <div><span className="text-muted-foreground">Desc:</span> {charge.description}</div>
            </div>
            <div className="space-y-1.5">
              <Label>Void Reason <span className="text-red-500">*</span></Label>
              <Textarea
                rows={2}
                maxLength={500}
                placeholder="Reason for voiding…"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
            {formError && <p className="text-sm text-red-500">{formError}</p>}
            <div className="flex justify-end gap-2">
              <Button
                type="button" variant="ghost"
                onClick={handleClose} disabled={voidMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" variant="destructive" disabled={voidMutation.isPending}>
                {voidMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
                Void Entry
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function OwnerChargesPage() {
  const [filters, setFilters] = useState<ChargeListFilters>({
    include_voided: false,
    limit: 100,
  });
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [modalMode, setModalMode] = useState<ModalMode | null>(null);
  const [editCharge, setEditCharge] = useState<OwnerCharge | null>(null);
  const [voidTarget, setVoidTarget] = useState<OwnerCharge | null>(null);

  const { data: opasData } = useAdminOPAs();
  const { data: vendorsData } = useVendors();
  const { data: chargesData, isLoading, isError } = useAdminCharges(filters);

  const opas = opasData?.accounts ?? [];
  const vendors = vendorsData?.vendors ?? [];
  const charges = chargesData?.charges ?? [];
  const total = chargesData?.total ?? 0;

  // Client-side type filter (Charges / Payments / Credits)
  const filteredCharges = useMemo(() => {
    if (typeFilter === "charges") return charges.filter((c) => parseFloat(c.amount) > 0);
    if (typeFilter === "payments") return charges.filter(
      (c) => parseFloat(c.amount) < 0 && PAYMENT_CODES.has(c.transaction_type)
    );
    if (typeFilter === "credits") return charges.filter(
      (c) => parseFloat(c.amount) < 0 && CREDIT_CODES.has(c.transaction_type)
    );
    return charges;
  }, [charges, typeFilter]);

  function setFilter<K extends keyof ChargeListFilters>(key: K, val: ChargeListFilters[K]) {
    setFilters((prev) => ({ ...prev, [key]: val }));
  }

  function clearFilters() {
    setFilters({ include_voided: false, limit: 100 });
    setTypeFilter("all");
  }

  const TYPE_FILTER_LABELS: Record<TypeFilter, string> = {
    all: "All",
    charges: "Charges",
    payments: "Payments",
    credits: "Credits",
  };

  // Determine modal mode when editing (infer from existing charge sign/code)
  const editMode: ModalMode = useMemo(() => {
    if (!editCharge) return "charge";
    const n = parseFloat(editCharge.amount);
    if (n < 0 && PAYMENT_CODES.has(editCharge.transaction_type)) return "payment";
    if (n < 0 && CREDIT_CODES.has(editCharge.transaction_type)) return "credit";
    return "charge";
  }, [editCharge]);

  return (
    <div className="flex flex-col gap-6 p-6">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Owner Charges</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Post charges, receive payments, and credit owner accounts.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button onClick={() => setModalMode("charge")}>
            <PlusCircle className="h-4 w-4 mr-2" />
            Post Charge
          </Button>
          <Button variant="outline" onClick={() => setModalMode("payment")}>
            <ArrowDownCircle className="h-4 w-4 mr-2 text-emerald-600" />
            Receive Payment
          </Button>
          <Button variant="outline" onClick={() => setModalMode("credit")}>
            <CreditCard className="h-4 w-4 mr-2 text-blue-600" />
            Credit Account
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">

            {/* Owner / OPA */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Owner</Label>
              <Select
                value={
                  filters.owner_payout_account_id !== undefined
                    ? String(filters.owner_payout_account_id)
                    : "all"
                }
                onValueChange={(v) =>
                  setFilter("owner_payout_account_id", v === "all" ? undefined : parseInt(v, 10))
                }
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="All owners" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All owners</SelectItem>
                  {opas.map((o) => (
                    <SelectItem key={o.id} value={String(o.id)}>
                      {opaLabel(o)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Date from */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">From</Label>
              <Input
                type="date"
                className="h-8 text-xs"
                value={filters.period_start ?? ""}
                onChange={(e) => setFilter("period_start", e.target.value || undefined)}
              />
            </div>

            {/* Date to */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">To</Label>
              <Input
                type="date"
                className="h-8 text-xs"
                value={filters.period_end ?? ""}
                onChange={(e) => setFilter("period_end", e.target.value || undefined)}
              />
            </div>

            {/* Type filter — All / Charges / Payments / Credits */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Type</Label>
              <Select
                value={typeFilter}
                onValueChange={(v) => setTypeFilter(v as TypeFilter)}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(["all", "charges", "payments", "credits"] as TypeFilter[]).map((t) => (
                    <SelectItem key={t} value={t}>{TYPE_FILTER_LABELS[t]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Show voided toggle + clear */}
            <div className="flex items-end gap-2 col-span-2">
              <Button
                variant={filters.include_voided ? "secondary" : "outline"}
                size="sm"
                className="h-8 text-xs"
                onClick={() => setFilter("include_voided", !filters.include_voided)}
              >
                {filters.include_voided ? "Hide Voided" : "Show Voided"}
              </Button>
              <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clearFilters}>
                Clear
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {typeFilter !== "all" ? TYPE_FILTER_LABELS[typeFilter] : "All Entries"}
            {total > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({filteredCharges.length}{typeFilter !== "all" ? ` of ${total}` : ""})
              </span>
            )}
          </CardTitle>
          <CardDescription>
            Positive = debit to owner (reduces balance). Negative = credit/payment (increases balance).
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
          {isError && (
            <div className="flex items-center justify-center gap-2 py-12 text-red-500">
              <AlertTriangle className="h-5 w-5" />
              <span className="text-sm">Failed to load entries.</span>
            </div>
          )}
          {!isLoading && !isError && filteredCharges.length === 0 && (
            <div className="py-16 text-center text-muted-foreground text-sm">
              No entries found.{" "}
              <button
                className="underline underline-offset-2 hover:text-foreground"
                onClick={() => setModalMode("charge")}
              >
                Post Charge to get started.
              </button>
            </div>
          )}
          {!isLoading && !isError && filteredCharges.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Posted Date</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead>Property</TableHead>
                  <TableHead>Transaction Type</TableHead>
                  <TableHead>Vendor</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="pr-6">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredCharges.map((c) => {
                  const voided = isVoided(c);
                  const amountNum = parseFloat(c.amount);
                  const isCredit = amountNum < 0;
                  return (
                    <TableRow key={c.id} className={cn(voided && "opacity-50")}>
                      <TableCell className="pl-6 text-sm">{fmtDate(c.posting_date)}</TableCell>
                      <TableCell className="text-sm">{c.owner_name ?? "—"}</TableCell>
                      <TableCell className="text-sm">{c.property_name ?? "—"}</TableCell>
                      <TableCell className="text-sm">
                        <div className="flex items-center gap-1.5">
                          {isCredit && (
                            <Badge
                              variant="outline"
                              className="text-[10px] px-1 py-0 text-emerald-600 border-emerald-300"
                            >
                              {PAYMENT_CODES.has(c.transaction_type) ? "PMT" : "CR"}
                            </Badge>
                          )}
                          <span className="font-medium">{c.transaction_type_display}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {c.vendor_name ?? "—"}
                      </TableCell>
                      <TableCell
                        className="text-sm max-w-[180px] truncate"
                        title={c.description}
                      >
                        {c.description}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right text-sm font-mono",
                          isCredit ? "text-emerald-600" : "text-foreground"
                        )}
                      >
                        {fmtCurrency(c.amount)}
                      </TableCell>
                      <TableCell>
                        {voided ? (
                          <Badge className="bg-red-500/10 text-red-500 border border-red-500/30 text-xs">
                            Voided
                          </Badge>
                        ) : (
                          <Badge className="bg-emerald-500/10 text-emerald-600 border border-emerald-500/30 text-xs">
                            Active
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="pr-6">
                        <div className="flex items-center gap-1">
                          {!voided && (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2"
                                onClick={() => setEditCharge(c)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-red-500 hover:text-red-600"
                                onClick={() => setVoidTarget(c)}
                              >
                                <Ban className="h-3.5 w-3.5" />
                              </Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Modals — key forces remount on mode change so useState reinitializes */}
      <ChargeModal
        key={modalMode ?? "closed"}
        open={modalMode !== null}
        mode={modalMode ?? "charge"}
        onClose={() => setModalMode(null)}
        opas={opas}
        vendors={vendors}
      />
      <ChargeModal
        key={editCharge ? `edit-${editCharge.id}` : "edit-closed"}
        open={!!editCharge}
        mode={editMode}
        onClose={() => setEditCharge(null)}
        opas={opas}
        vendors={vendors}
        existing={editCharge}
      />
      <VoidModal
        charge={voidTarget}
        onClose={() => setVoidTarget(null)}
      />
    </div>
  );
}
