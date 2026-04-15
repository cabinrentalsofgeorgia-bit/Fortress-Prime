"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import {
  useAdminStatement,
  useApproveStatement,
  useVoidStatement,
  useMarkStatementPaid,
  useMarkStatementEmailed,
  useSendTestStatement,
  useAdminCharges,
  useCreateOwnerCharge,
  useUpdateOwnerCharge,
  useVoidOwnerCharge,
} from "@/lib/hooks";
import type {
  OwnerBalancePeriod,
  OwnerCharge,
  StatementPeriodStatus,
  StatementLineItem,
  CreateOwnerChargeRequest,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
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
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Mail,
  Plus,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function fmtCurrency(s: string | number | null | undefined): string {
  if (s == null) return "—";
  const n = typeof s === "string" ? parseFloat(s) : s;
  if (isNaN(n)) return String(s);
  const formatted = Math.abs(n).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
  return n < 0 ? `(${formatted})` : formatted;
}

const STATUS_LABELS: Record<StatementPeriodStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending Approval",
  approved: "Approved",
  paid: "Paid",
  emailed: "Emailed",
  voided: "Voided",
};

const STATUS_CLASSES: Record<StatementPeriodStatus, string> = {
  draft:            "bg-slate-500/10 text-slate-500 border border-slate-500/30",
  pending_approval: "bg-amber-500/10 text-amber-600 border border-amber-500/30",
  approved:         "bg-emerald-500/10 text-emerald-600 border border-emerald-500/30",
  paid:             "bg-blue-500/10 text-blue-600 border border-blue-500/30",
  emailed:          "bg-teal-500/10 text-teal-600 border border-teal-500/30",
  voided:           "bg-red-500/10 text-red-500 border border-red-500/30",
};

function StatusBadge({ status }: { status: StatementPeriodStatus }) {
  return (
    <Badge className={cn("text-xs", STATUS_CLASSES[status])}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}

const CHARGE_TYPE_OPTIONS = [
  { value: "cleaning_fee", label: "Cleaning Fee" },
  { value: "maintenance", label: "Maintenance" },
  { value: "management_fee", label: "Management Fee" },
  { value: "supplies", label: "Supplies" },
  { value: "landscaping", label: "Landscaping" },
  { value: "linen", label: "Linen" },
  { value: "electric_bill", label: "Electric Bill" },
  { value: "housekeeper_pay", label: "Housekeeper Pay" },
  { value: "advertising_fee", label: "Advertising Fee" },
  { value: "third_party_ota_commission", label: "3rd Party OTA Commission" },
  { value: "travel_agent_fee", label: "Travel Agent Fee" },
  { value: "credit_card_dispute", label: "Credit Card Dispute" },
  { value: "federal_tax_withholding", label: "Federal Tax Withholding" },
  { value: "adjust_owner_revenue", label: "Adjust Owner Revenue" },
  { value: "credit_from_management", label: "Credit From Management" },
  { value: "pay_to_old_owner", label: "Pay To Old Owner" },
  { value: "misc_guest_charges", label: "Misc. Guest Charges" },
];

// ── Confirm dialogs ───────────────────────────────────────────────────────────

interface ApproveDialogProps {
  periodId: number;
  open: boolean;
  onClose: () => void;
}
function ApproveDialog({ periodId, open, onClose }: ApproveDialogProps) {
  const approve = useApproveStatement();
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            Approve Statement
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Transition this statement from{" "}
          <span className="font-medium">pending approval</span> to{" "}
          <span className="font-medium text-emerald-600">approved</span>. This
          signals the financials are correct.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={approve.isPending}
            onClick={() =>
              approve.mutate({ periodId }, { onSuccess: onClose })
            }
          >
            {approve.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Approving…</>
            ) : (
              <>Approve</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface VoidDialogProps {
  periodId: number;
  open: boolean;
  onClose: () => void;
}
function VoidDialog({ periodId, open, onClose }: VoidDialogProps) {
  const [reason, setReason] = useState("");
  const voidStmt = useVoidStatement();
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-500" />
            Void Statement
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Voiding is irreversible. Provide a reason for the audit trail.
          </p>
          <div className="space-y-1.5">
            <Label>Reason</Label>
            <Textarea
              placeholder="e.g. Duplicate period, incorrect data entered…"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={!reason.trim() || voidStmt.isPending}
            onClick={() =>
              voidStmt.mutate({ periodId, reason: reason.trim() }, { onSuccess: onClose })
            }
          >
            {voidStmt.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Voiding…</>
            ) : (
              <>Void Statement</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface MarkPaidDialogProps {
  periodId: number;
  open: boolean;
  onClose: () => void;
}
function MarkPaidDialog({ periodId, open, onClose }: MarkPaidDialogProps) {
  const [ref, setRef] = useState("");
  const markPaid = useMarkStatementPaid();
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Mark as Paid</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Record payment reference (e.g. QuickBooks ACH batch number).
          </p>
          <div className="space-y-1.5">
            <Label>Payment reference</Label>
            <Input
              placeholder="e.g. QuickBooks ACH 2026-05-15-001"
              value={ref}
              onChange={(e) => setRef(e.target.value)}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!ref.trim() || markPaid.isPending}
            onClick={() =>
              markPaid.mutate(
                { periodId, payment_reference: ref.trim() },
                { onSuccess: onClose }
              )
            }
          >
            {markPaid.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Saving…</>
            ) : (
              <>Mark Paid</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface MarkEmailedDialogProps {
  periodId: number;
  open: boolean;
  onClose: () => void;
}
function MarkEmailedDialog({ periodId, open, onClose }: MarkEmailedDialogProps) {
  const markEmailed = useMarkStatementEmailed();
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            Mark as Emailed
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Confirm this statement has been emailed to the owner.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={markEmailed.isPending}
            onClick={() =>
              markEmailed.mutate({ periodId }, { onSuccess: onClose })
            }
          >
            {markEmailed.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Saving…</>
            ) : (
              <>Confirm</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface SendTestDialogProps {
  periodId: number;
  open: boolean;
  onClose: () => void;
}
function SendTestDialog({ periodId, open, onClose }: SendTestDialogProps) {
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const sendTest = useSendTestStatement();
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            Send Test Email
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Sends a <span className="font-medium">[TEST]</span>-prefixed copy to
            the override email. The real owner is NOT notified. Statement status
            is unchanged.
          </p>
          <div className="space-y-1.5">
            <Label>Send to</Label>
            <Input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Note (optional)</Label>
            <Input
              placeholder="Optional verification note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!email.trim() || sendTest.isPending}
            onClick={() =>
              sendTest.mutate(
                { periodId, override_email: email.trim(), note: note || undefined },
                { onSuccess: onClose }
              )
            }
          >
            {sendTest.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Sending…</>
            ) : (
              <>Send Test</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Charge modal ──────────────────────────────────────────────────────────────

interface ChargeModalProps {
  opaId: number;
  periodStart: string;
  periodEnd: string;
  charge?: OwnerCharge;
  open: boolean;
  onClose: () => void;
}
function ChargeModal({ opaId, periodStart, periodEnd, charge, open, onClose }: ChargeModalProps) {
  const isEdit = !!charge;
  const [type, setType] = useState(charge?.transaction_type ?? "cleaning_fee");
  const [amount, setAmount] = useState(charge ? charge.amount : "");
  const [description, setDescription] = useState(charge?.description ?? "");
  const [postingDate, setPostingDate] = useState(
    charge?.posting_date?.slice(0, 10) ?? periodStart
  );
  const [refId, setRefId] = useState(charge?.reference_id ?? "");

  const createCharge = useCreateOwnerCharge();
  const updateCharge = useUpdateOwnerCharge();

  function handleSave() {
    if (isEdit && charge) {
      updateCharge.mutate(
        {
          chargeId: charge.id,
          description: description.trim() || undefined,
          posting_date: postingDate || undefined,
          amount: amount ? parseFloat(amount) : undefined,
          reference_id: refId.trim() || undefined,
        },
        { onSuccess: onClose }
      );
    } else {
      const body: CreateOwnerChargeRequest = {
        owner_payout_account_id: opaId,
        posting_date: postingDate,
        transaction_type: type,
        description: description.trim(),
        amount: parseFloat(amount),
        ...(refId.trim() ? { reference_id: refId.trim() } : {}),
      };
      createCharge.mutate(body, { onSuccess: onClose });
    }
  }

  const isPending = createCharge.isPending || updateCharge.isPending;
  const canSave = description.trim() && amount && !isNaN(parseFloat(amount)) && postingDate;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Charge" : "Add Charge"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          {!isEdit && (
            <div className="space-y-1.5">
              <Label>Type</Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CHARGE_TYPE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label>Description</Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Amount ($)</Label>
              <Input
                type="number"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. -150.00 for credit"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Posting date</Label>
              <Input
                type="date"
                value={postingDate}
                min={periodStart}
                max={periodEnd}
                onChange={(e) => setPostingDate(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Reference ID (optional)</Label>
            <Input
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              placeholder="Invoice # or work order #"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" disabled={!canSave || isPending} onClick={handleSave}>
            {isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Saving…</>
            ) : (
              <>Save Charge</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface VoidChargeDialogProps {
  charge: OwnerCharge;
  open: boolean;
  onClose: () => void;
}
function VoidChargeDialog({ charge, open, onClose }: VoidChargeDialogProps) {
  const [reason, setReason] = useState("");
  const voidCharge = useVoidOwnerCharge();
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Void Charge</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Void{" "}
            <span className="font-medium">
              {charge.transaction_type_display} — {fmtCurrency(charge.amount)}
            </span>
            ? Enter a reason.
          </p>
          <Textarea
            placeholder="Reason for voiding…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={!reason.trim() || voidCharge.isPending}
            onClick={() =>
              voidCharge.mutate(
                { chargeId: charge.id, void_reason: reason.trim() },
                { onSuccess: onClose }
              )
            }
          >
            {voidCharge.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /></>
            ) : (
              <>Void</>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

type Tab = "overview" | "charges" | "activity";

interface OverviewTabProps {
  period: OwnerBalancePeriod;
  lineItems: StatementLineItem[];
  statementError?: string;
}
function OverviewTab({ period, lineItems, statementError }: OverviewTabProps) {
  return (
    <div className="space-y-4">
      {/* Financial summary */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Financial Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            {[
              { label: "Opening Balance", value: period.opening_balance },
              { label: "Total Revenue", value: period.total_revenue },
              { label: "Total Commission", value: period.total_commission },
              { label: "Total Charges", value: period.total_charges },
              { label: "Total Payments", value: period.total_payments },
              { label: "Total Owner Income", value: period.total_owner_income },
              { label: "Closing Balance", value: period.closing_balance, bold: true },
            ].map(({ label, value, bold }) => (
              <div key={label}>
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className={cn("font-medium", bold && "text-base")}>
                  {fmtCurrency(value)}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Line items */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Reservation Line Items</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {statementError ? (
            <div className="p-4 text-sm text-red-600">
              Could not compute line items: {statementError}
            </div>
          ) : lineItems.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              No reservations in this period.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Confirmation</TableHead>
                  <TableHead>Check-in</TableHead>
                  <TableHead>Nights</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                  <TableHead className="text-right">Commission</TableHead>
                  <TableHead className="text-right">Net to Owner</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lineItems.map((li) => (
                  <TableRow key={li.reservation_id}>
                    <TableCell className="font-mono text-xs">{li.confirmation_code}</TableCell>
                    <TableCell className="text-sm">{fmtDate(li.check_in)}</TableCell>
                    <TableCell className="text-sm">{li.nights}</TableCell>
                    <TableCell className="text-right text-sm">{fmtCurrency(li.gross_revenue)}</TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {fmtCurrency(li.commission_amount)}
                    </TableCell>
                    <TableCell className="text-right text-sm font-medium text-emerald-600">
                      {fmtCurrency(li.net_owner_payout)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

interface ChargesTabProps {
  period: OwnerBalancePeriod;
}
function ChargesTab({ period }: ChargesTabProps) {
  const [addOpen, setAddOpen] = useState(false);
  const [editCharge, setEditCharge] = useState<OwnerCharge | null>(null);
  const [voidCharge, setVoidCharge] = useState<OwnerCharge | null>(null);

  const { data: chargeData, isLoading } = useAdminCharges({
    owner_payout_account_id: period.owner_payout_account_id,
    period_start: period.period_start,
    period_end: period.period_end,
    include_voided: true,
  });

  const charges = chargeData?.charges ?? [];
  const isLocked = ["approved", "paid", "emailed", "voided"].includes(period.status);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Manual charges and credits for this period.
          {isLocked && (
            <span className="ml-1 text-amber-600">
              Period is locked — charges cannot be added or modified.
            </span>
          )}
        </p>
        {!isLocked && (
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="mr-1.5 h-4 w-4" />
            Add Charge
          </Button>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center h-24">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : charges.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              No manual charges for this period.
              {!isLocked && " Click Add Charge to add one."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Status</TableHead>
                  {!isLocked && <TableHead className="text-right">Actions</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {charges.map((ch) => (
                  <TableRow key={ch.id} className={cn(ch.voided_at && "opacity-50")}>
                    <TableCell className="text-sm">{fmtDate(ch.posting_date)}</TableCell>
                    <TableCell className="text-sm">{ch.transaction_type_display}</TableCell>
                    <TableCell className="text-sm">{ch.description}</TableCell>
                    <TableCell className="text-right text-sm font-medium">
                      <span className={cn(parseFloat(ch.amount) < 0 ? "text-emerald-600" : "text-foreground")}>
                        {fmtCurrency(ch.amount)}
                      </span>
                    </TableCell>
                    <TableCell>
                      {ch.voided_at ? (
                        <Badge className="text-xs bg-red-500/10 text-red-500 border border-red-500/30">
                          Voided
                        </Badge>
                      ) : (
                        <Badge className="text-xs bg-emerald-500/10 text-emerald-600 border border-emerald-500/30">
                          Active
                        </Badge>
                      )}
                    </TableCell>
                    {!isLocked && (
                      <TableCell className="text-right">
                        {!ch.voided_at && (
                          <div className="flex justify-end gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs"
                              onClick={() => setEditCharge(ch)}
                            >
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs text-red-600 hover:text-red-700"
                              onClick={() => setVoidCharge(ch)}
                            >
                              Void
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {addOpen && (
        <ChargeModal
          opaId={period.owner_payout_account_id}
          periodStart={period.period_start}
          periodEnd={period.period_end}
          open={addOpen}
          onClose={() => setAddOpen(false)}
        />
      )}
      {editCharge && (
        <ChargeModal
          opaId={period.owner_payout_account_id}
          periodStart={period.period_start}
          periodEnd={period.period_end}
          charge={editCharge}
          open={!!editCharge}
          onClose={() => setEditCharge(null)}
        />
      )}
      {voidCharge && (
        <VoidChargeDialog
          charge={voidCharge}
          open={!!voidCharge}
          onClose={() => setVoidCharge(null)}
        />
      )}
    </div>
  );
}

interface ActivityTabProps {
  period: OwnerBalancePeriod;
}
function ActivityTab({ period }: ActivityTabProps) {
  const events: Array<{ date: string | null; label: string }> = [
    { date: period.created_at, label: "Statement created (draft)" },
    ...(period.approved_at
      ? [{ date: period.approved_at, label: `Approved by ${period.approved_by ?? "staff"}` }]
      : []),
    ...(period.paid_at
      ? [{ date: period.paid_at, label: `Marked paid by ${period.paid_by ?? "staff"}` }]
      : []),
    ...(period.emailed_at
      ? [{ date: period.emailed_at, label: "Emailed to owner" }]
      : []),
    ...(period.voided_at
      ? [{ date: period.voided_at, label: `Voided by ${period.voided_by ?? "staff"}` }]
      : []),
  ].filter((e) => e.date);

  return (
    <Card>
      <CardContent className="pt-4">
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No activity recorded yet.
          </p>
        ) : (
          <ol className="relative border-l border-border ml-3 space-y-4">
            {events.map((ev, i) => (
              <li key={i} className="ml-4">
                <div className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full bg-border" />
                <p className="text-xs text-muted-foreground">{fmtDate(ev.date)}</p>
                <p className="text-sm">{ev.label}</p>
              </li>
            ))}
          </ol>
        )}
        {period.voided_at && period.notes && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-800 dark:bg-red-950/30">
            <span className="font-medium text-red-600">Void reason: </span>
            {period.notes}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main Detail Page ──────────────────────────────────────────────────────────

export default function StatementDetailPage() {
  const params = useParams();
  const periodId = Number(params.id);

  const { data, isLoading, isError } = useAdminStatement(periodId);

  const [tab, setTab] = useState<Tab>("overview");
  const [showApprove, setShowApprove] = useState(false);
  const [showVoid, setShowVoid] = useState(false);
  const [showMarkPaid, setShowMarkPaid] = useState(false);
  const [showMarkEmailed, setShowMarkEmailed] = useState(false);
  const [showSendTest, setShowSendTest] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-6 text-sm text-red-600">
        Statement #{periodId} not found or failed to load.
      </div>
    );
  }

  const { balance_period: period, statement } = data;
  const status = period.status as StatementPeriodStatus;

  const lineItems =
    statement && !("error" in statement)
      ? (statement as { reservations?: StatementLineItem[] }).reservations ?? []
      : [];
  const statementError = statement && "error" in statement ? statement.error : undefined;

  const ownerName =
    statement && !("error" in statement)
      ? (statement as { owner_name?: string | null }).owner_name
      : null;
  const propertyName =
    statement && !("error" in statement)
      ? (statement as { property_name?: string }).property_name
      : null;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Link href="/admin/statements">
            <Button variant="ghost" size="icon" className="h-8 w-8 mt-0.5">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-semibold tracking-tight">
                {ownerName ?? `Owner Account #${period.owner_payout_account_id}`}
              </h1>
              <StatusBadge status={status} />
            </div>
            {propertyName && (
              <p className="text-sm text-muted-foreground">{propertyName}</p>
            )}
            <p className="text-sm text-muted-foreground">
              {fmtDate(period.period_start)} → {fmtDate(period.period_end)}
            </p>
          </div>
        </div>

        {/* Action bar */}
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {(status === "draft" || status === "pending_approval") && (
            <Button size="sm" onClick={() => setShowApprove(true)}>
              <CheckCircle2 className="mr-1.5 h-4 w-4" />
              Approve
            </Button>
          )}
          {status === "approved" && (
            <>
              <Button size="sm" variant="outline" onClick={() => setShowMarkPaid(true)}>
                Mark Paid
              </Button>
              <Button size="sm" variant="outline" onClick={() => setShowMarkEmailed(true)}>
                <Mail className="mr-1.5 h-4 w-4" />
                Mark Emailed
              </Button>
            </>
          )}
          {status === "paid" && !period.emailed_at && (
            <Button size="sm" variant="outline" onClick={() => setShowMarkEmailed(true)}>
              <Mail className="mr-1.5 h-4 w-4" />
              Mark Emailed
            </Button>
          )}
          {status !== "voided" && (
            <Button
              size="sm"
              variant="outline"
              className="text-red-600 hover:text-red-700 border-red-200 hover:border-red-300"
              onClick={() => setShowVoid(true)}
            >
              <XCircle className="mr-1.5 h-4 w-4" />
              Void
            </Button>
          )}
          {/* Always available */}
          <a
            href={`/api/admin/payouts/statements/${periodId}/pdf`}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Button size="sm" variant="outline">
              <Download className="mr-1.5 h-4 w-4" />
              PDF
            </Button>
          </a>
          <Button size="sm" variant="outline" onClick={() => setShowSendTest(true)}>
            <Mail className="mr-1.5 h-4 w-4" />
            Send Test
          </Button>
        </div>
      </div>

      {/* Voided notice */}
      {status === "voided" && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          Voided on {fmtDate(period.voided_at)} by {period.voided_by ?? "staff"}.
          {period.notes && <> Reason: {period.notes}</>}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b gap-0">
        {(["overview", "charges", "activity"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && (
        <OverviewTab
          period={period}
          lineItems={lineItems}
          statementError={statementError}
        />
      )}
      {tab === "charges" && <ChargesTab period={period} />}
      {tab === "activity" && <ActivityTab period={period} />}

      {/* Dialogs */}
      <ApproveDialog
        periodId={periodId}
        open={showApprove}
        onClose={() => setShowApprove(false)}
      />
      <VoidDialog
        periodId={periodId}
        open={showVoid}
        onClose={() => setShowVoid(false)}
      />
      <MarkPaidDialog
        periodId={periodId}
        open={showMarkPaid}
        onClose={() => setShowMarkPaid(false)}
      />
      <MarkEmailedDialog
        periodId={periodId}
        open={showMarkEmailed}
        onClose={() => setShowMarkEmailed(false)}
      />
      <SendTestDialog
        periodId={periodId}
        open={showSendTest}
        onClose={() => setShowSendTest(false)}
      />
    </div>
  );
}
