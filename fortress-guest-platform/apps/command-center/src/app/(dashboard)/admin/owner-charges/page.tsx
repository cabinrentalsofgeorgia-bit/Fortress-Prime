"use client";

import { useState } from "react";
import {
  useAdminCharges,
  useCreateOwnerCharge,
  useUpdateOwnerCharge,
  useVoidOwnerCharge,
  useAdminOPAs,
  type AdminOPA,
} from "@/lib/hooks";
import type { OwnerCharge, ChargeListFilters, CreateOwnerChargeRequest } from "@/lib/types";
import {
  OWNER_CHARGE_CODES,
  CHARGE_CODE_PLACEHOLDER,
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
import { AlertTriangle, Loader2, PlusCircle, Pencil, Ban } from "lucide-react";
import { cn } from "@/lib/utils";

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

function fmtCurrency(val: string | null | undefined): string {
  if (!val) return "—";
  const n = parseFloat(val);
  if (isNaN(n)) return val;
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

// ── Post Charge Modal ─────────────────────────────────────────────────────────

interface ChargeModalProps {
  open: boolean;
  onClose: () => void;
  opas: AdminOPA[];
  existing?: OwnerCharge | null;
}

function ChargeModal({ open, onClose, opas, existing }: ChargeModalProps) {
  const isEdit = !!existing;

  const [opaId, setOpaId] = useState<string>(existing ? String(existing.owner_payout_account_id) : "");
  const [txType, setTxType] = useState<string>(existing?.transaction_type ?? "");
  const [description, setDescription] = useState<string>(existing?.description ?? "");
  const [postedDate, setPostedDate] = useState<string>(
    existing?.posting_date ? existing.posting_date.slice(0, 10) : todayIso()
  );
  const [amount, setAmount] = useState<string>(existing ? String(parseFloat(existing.amount)) : "");
  const [referenceId, setReferenceId] = useState<string>(existing?.reference_id ?? "");
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useCreateOwnerCharge();
  const updateMutation = useUpdateOwnerCharge();

  const isLoading = createMutation.isPending || updateMutation.isPending;

  function resetForm() {
    setOpaId("");
    setTxType("");
    setDescription("");
    setPostedDate(todayIso());
    setAmount("");
    setReferenceId("");
    setFormError(null);
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!isEdit && !opaId) { setFormError("Select an owner / property."); return; }
    if (!isEdit && !txType) { setFormError("Select a transaction type."); return; }
    if (!description.trim()) { setFormError("Description is required."); return; }
    if (!postedDate) { setFormError("Posted date is required."); return; }
    const amountNum = parseFloat(amount);
    if (isNaN(amountNum) || amountNum === 0) { setFormError("Amount must be a non-zero number."); return; }

    try {
      if (isEdit && existing) {
        await updateMutation.mutateAsync({
          chargeId: existing.id,
          description: description.trim(),
          posting_date: postedDate,
          amount: amountNum,
          reference_id: referenceId.trim() || undefined,
        });
      } else {
        const body: CreateOwnerChargeRequest = {
          owner_payout_account_id: parseInt(opaId, 10),
          posting_date: postedDate,
          transaction_type: txType,
          description: description.trim(),
          amount: amountNum,
          reference_id: referenceId.trim() || undefined,
        };
        await createMutation.mutateAsync(body);
      }
      handleClose();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to save charge");
    }
  }

  const selectedOpa = opas.find((o) => String(o.id) === opaId);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <PlusCircle className="h-5 w-5" />
            {isEdit ? "Edit Charge" : "Post Owner Charge"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 pt-2">

          {/* Owner / Property */}
          {!isEdit && (
            <div className="space-y-1.5">
              <Label>Owner / Property <span className="text-red-500">*</span></Label>
              <Select value={opaId} onValueChange={setOpaId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select owner…" />
                </SelectTrigger>
                <SelectContent>
                  {opas.map((o) => (
                    <SelectItem key={o.id} value={String(o.id)}>
                      {opaLabel(o)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedOpa && !selectedOpa.stripe_account_id && (
                <p className="text-xs text-amber-600 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Stripe not linked — backend may reject charge posting.
                </p>
              )}
            </div>
          )}

          {isEdit && (
            <div className="rounded-md bg-muted/50 p-2 text-sm text-muted-foreground">
              {existing?.owner_name} — {existing?.property_name}
            </div>
          )}

          {/* Transaction Type (create only) */}
          {!isEdit && (
            <div className="space-y-1.5">
              <Label>Transaction Type <span className="text-red-500">*</span></Label>
              <Select value={txType} onValueChange={setTxType}>
                <SelectTrigger>
                  <SelectValue placeholder={CHARGE_CODE_PLACEHOLDER} />
                </SelectTrigger>
                <SelectContent>
                  {OWNER_CHARGE_CODES.map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
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
              <p className="text-xs text-muted-foreground">Transaction type cannot be changed after posting.</p>
            </div>
          )}

          {/* Description */}
          <div className="space-y-1.5">
            <Label>Description <span className="text-red-500">*</span></Label>
            <Textarea
              rows={2}
              maxLength={500}
              placeholder="Appears on owner statement PDF…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

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
            <div className="space-y-1.5">
              <Label>Amount (USD) <span className="text-red-500">*</span></Label>
              <Input
                type="number"
                step="0.01"
                placeholder="100.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">+&thinsp;charge&nbsp;/&nbsp;&minus;&thinsp;credit</p>
            </div>
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
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              {formError}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              {isEdit ? "Save Changes" : "Post Charge"}
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

  return (
    <Dialog open={!!charge} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600">
            <Ban className="h-5 w-5" />
            Void Charge
          </DialogTitle>
        </DialogHeader>
        {charge && (
          <form onSubmit={handleVoid} className="space-y-4 pt-2">
            <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
              <div><span className="text-muted-foreground">Owner:</span> {charge.owner_name}</div>
              <div><span className="text-muted-foreground">Type:</span> {charge.transaction_type_display}</div>
              <div><span className="text-muted-foreground">Amount:</span> {fmtCurrency(charge.amount)}</div>
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
            {formError && (
              <p className="text-sm text-red-500">{formError}</p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={handleClose} disabled={voidMutation.isPending}>
                Cancel
              </Button>
              <Button type="submit" variant="destructive" disabled={voidMutation.isPending}>
                {voidMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
                Void Charge
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
  const [showPostModal, setShowPostModal] = useState(false);
  const [editCharge, setEditCharge] = useState<OwnerCharge | null>(null);
  const [voidTarget, setVoidTarget] = useState<OwnerCharge | null>(null);

  const { data: opasData } = useAdminOPAs();
  const { data: chargesData, isLoading, isError } = useAdminCharges(filters);

  const opas = opasData?.accounts ?? [];
  const charges = chargesData?.charges ?? [];
  const total = chargesData?.total ?? 0;

  function setFilter<K extends keyof ChargeListFilters>(key: K, val: ChargeListFilters[K]) {
    setFilters((prev) => ({ ...prev, [key]: val }));
  }

  function clearFilters() {
    setFilters({ include_voided: false, limit: 100 });
  }

  return (
    <div className="flex flex-col gap-6 p-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Owner Charges</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Post and manage owner expenses / credits against statement periods.
          </p>
        </div>
        <Button onClick={() => setShowPostModal(true)}>
          <PlusCircle className="h-4 w-4 mr-2" />
          Post Charge
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">

            {/* Owner / OPA */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Owner</Label>
              <Select
                value={filters.owner_payout_account_id !== undefined ? String(filters.owner_payout_account_id) : "all"}
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

            {/* Transaction type */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Transaction Type</Label>
              <Select
                value={(filters as Record<string, unknown>).transaction_type as string ?? "all"}
                onValueChange={(v) => setFilter("owner_payout_account_id", filters.owner_payout_account_id)}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All types</SelectItem>
                  {OWNER_CHARGE_CODES.map((c) => (
                    <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
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

            {/* Show voided toggle + clear */}
            <div className="flex items-end gap-2">
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
            Charges
            {total > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">({total})</span>
            )}
          </CardTitle>
          <CardDescription>
            Positive amounts are debits to owner; negative are credits.
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
              <span className="text-sm">Failed to load charges.</span>
            </div>
          )}
          {!isLoading && !isError && charges.length === 0 && (
            <div className="py-16 text-center text-muted-foreground text-sm">
              No charges posted.{" "}
              <button
                className="underline underline-offset-2 hover:text-foreground"
                onClick={() => setShowPostModal(true)}
              >
                Click Post Charge to get started.
              </button>
            </div>
          )}
          {!isLoading && !isError && charges.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Posted Date</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead>Property</TableHead>
                  <TableHead>Transaction Type</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="pr-6">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {charges.map((c) => {
                  const voided = isVoided(c);
                  const amountNum = parseFloat(c.amount);
                  const amountColor = amountNum < 0
                    ? "text-emerald-600"
                    : amountNum > 0
                    ? "text-foreground"
                    : "";
                  return (
                    <TableRow
                      key={c.id}
                      className={cn(voided && "opacity-50")}
                    >
                      <TableCell className="pl-6 text-sm">{fmtDate(c.posting_date)}</TableCell>
                      <TableCell className="text-sm">{c.owner_name ?? "—"}</TableCell>
                      <TableCell className="text-sm">{c.property_name ?? "—"}</TableCell>
                      <TableCell className="text-sm">
                        <span className="font-medium">{c.transaction_type_display}</span>
                      </TableCell>
                      <TableCell className="text-sm max-w-[220px] truncate" title={c.description}>
                        {c.description}
                      </TableCell>
                      <TableCell className={cn("text-right text-sm font-mono", amountColor)}>
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

      {/* Modals */}
      <ChargeModal
        open={showPostModal}
        onClose={() => setShowPostModal(false)}
        opas={opas}
      />
      <ChargeModal
        open={!!editCharge}
        onClose={() => setEditCharge(null)}
        opas={opas}
        existing={editCharge}
      />
      <VoidModal
        charge={voidTarget}
        onClose={() => setVoidTarget(null)}
      />
    </div>
  );
}
