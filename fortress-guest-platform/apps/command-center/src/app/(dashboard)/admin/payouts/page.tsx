"use client";

import { useState } from "react";
import {
  useAdminPendingPayouts,
  useSendOwnerPayout,
  useUpdatePayoutSchedule,
  useTriggerPayoutSweep,
  type PayoutSummaryRow,
} from "@/lib/hooks";
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
  Building2,
  Calendar,
  CheckCircle2,
  DollarSign,
  Loader2,
  Play,
  RefreshCw,
  Send,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

const SCHEDULE_LABELS: Record<string, string> = {
  manual: "Manual",
  weekly: "Weekly",
  biweekly: "Bi-weekly",
  monthly: "Monthly",
};

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      className={cn(
        "text-xs",
        status === "active"
          ? "bg-emerald-500/10 text-emerald-600 border border-emerald-500/30"
          : "bg-slate-500/10 text-slate-500 border border-slate-500/30"
      )}
    >
      {status}
    </Badge>
  );
}

interface ScheduleModalProps {
  row: PayoutSummaryRow;
  onClose: () => void;
}

function ScheduleModal({ row, onClose }: ScheduleModalProps) {
  const updateSchedule = useUpdatePayoutSchedule();
  const [schedule, setSchedule] = useState(row.payout_schedule);
  const [dow, setDow] = useState<string>(
    row.payout_day_of_week != null ? String(row.payout_day_of_week) : ""
  );
  const [dom, setDom] = useState<string>(
    row.payout_day_of_month != null ? String(row.payout_day_of_month) : ""
  );
  const [threshold, setThreshold] = useState<string>(
    String(row.minimum_payout_threshold ?? 100)
  );

  function handleSave() {
    updateSchedule.mutate(
      {
        propertyId: row.property_id,
        payout_schedule: schedule,
        payout_day_of_week: dow !== "" ? Number(dow) : null,
        payout_day_of_month: dom !== "" ? Number(dom) : null,
        minimum_payout_threshold: threshold !== "" ? Number(threshold) : null,
      },
      { onSuccess: onClose }
    );
  }

  return (
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Settings className="h-5 w-5" />
          Payout Schedule — {row.owner_name}
        </DialogTitle>
      </DialogHeader>
      <div className="space-y-4 pt-2">
        <div className="space-y-1.5">
          <Label>Schedule</Label>
          <Select value={schedule} onValueChange={setSchedule}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="manual">Manual only</SelectItem>
              <SelectItem value="weekly">Weekly</SelectItem>
              <SelectItem value="biweekly">Bi-weekly</SelectItem>
              <SelectItem value="monthly">Monthly</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {(schedule === "weekly" || schedule === "biweekly") && (
          <div className="space-y-1.5">
            <Label>Day of week</Label>
            <Select value={dow} onValueChange={setDow}>
              <SelectTrigger>
                <SelectValue placeholder="Select day" />
              </SelectTrigger>
              <SelectContent>
                {DOW_LABELS.map((d, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {d}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {schedule === "monthly" && (
          <div className="space-y-1.5">
            <Label>Day of month (1–28)</Label>
            <Input
              type="number"
              min={1}
              max={28}
              value={dom}
              onChange={(e) => setDom(e.target.value)}
              placeholder="1"
            />
          </div>
        )}

        <div className="space-y-1.5">
          <Label>Minimum threshold ($)</Label>
          <Input
            type="number"
            step="0.01"
            min="1"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Payouts below this amount are skipped until the next cycle.
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={updateSchedule.isPending}
            onClick={handleSave}
          >
            {updateSchedule.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Saving…</>
            ) : (
              <><CheckCircle2 className="mr-1.5 h-4 w-4" /> Save Schedule</>
            )}
          </Button>
        </div>
      </div>
    </DialogContent>
  );
}

export default function AdminPayoutsPage() {
  const { data: rows, isLoading, refetch } = useAdminPendingPayouts();
  const sendPayout = useSendOwnerPayout();
  const sweep = useTriggerPayoutSweep();
  const [scheduleTarget, setScheduleTarget] = useState<PayoutSummaryRow | null>(null);
  const [confirmSend, setConfirmSend] = useState<PayoutSummaryRow | null>(null);

  const payoutRows = rows ?? [];
  const totalOutstanding = payoutRows.reduce(
    (sum, r) => sum + (r.outstanding_amount ?? 0),
    0
  );
  const activeCount = payoutRows.filter((r) => r.account_status === "active").length;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/admin">
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Owner Payouts</h1>
            <p className="text-sm text-muted-foreground">
              Manage Stripe Connect disbursements and schedules
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
          >
            <RefreshCw className={cn("mr-1.5 h-4 w-4", isLoading && "animate-spin")} />
            Refresh
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={sweep.isPending}
            onClick={() => sweep.mutate()}
          >
            {sweep.isPending ? (
              <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Running…</>
            ) : (
              <><Play className="mr-1.5 h-4 w-4" /> Run Sweep</>
            )}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs">Active Accounts</CardDescription>
            <CardTitle className="text-2xl flex items-center gap-2">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              {activeCount}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs">Total Outstanding</CardDescription>
            <CardTitle className="text-2xl flex items-center gap-2">
              <DollarSign className="h-5 w-5 text-muted-foreground" />
              {fmtCurrency(totalOutstanding)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="text-xs">Scheduled Transfers</CardDescription>
            <CardTitle className="text-2xl flex items-center gap-2">
              <Calendar className="h-5 w-5 text-muted-foreground" />
              {payoutRows.filter((r) => r.payout_schedule !== "manual").length}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Owner Accounts</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : payoutRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-sm text-muted-foreground">
              <DollarSign className="h-8 w-8 mb-2 opacity-30" />
              No active payout accounts found
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Owner</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Payout</TableHead>
                  <TableHead>Outstanding</TableHead>
                  <TableHead>Schedule</TableHead>
                  <TableHead>Next Run</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {payoutRows.map((row) => (
                  <TableRow key={row.property_id}>
                    <TableCell>
                      <div className="font-medium text-sm">{row.owner_name}</div>
                      {row.owner_email && (
                        <div className="text-xs text-muted-foreground">{row.owner_email}</div>
                      )}
                      {row.stripe_account_id && (
                        <div className="text-xs text-muted-foreground font-mono">
                          {row.stripe_account_id}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={row.account_status} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {fmtDate(row.last_payout_at)}
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "font-medium text-sm",
                          (row.outstanding_amount ?? 0) > 0
                            ? "text-emerald-600"
                            : "text-muted-foreground"
                        )}
                      >
                        {fmtCurrency(row.outstanding_amount)}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm">
                      {SCHEDULE_LABELS[row.payout_schedule] ?? row.payout_schedule}
                    </TableCell>
                    <TableCell className="text-sm">
                      {fmtDate(row.next_scheduled_payout)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 px-2 text-xs"
                          onClick={() => setScheduleTarget(row)}
                        >
                          <Settings className="h-3 w-3 mr-1" />
                          Schedule
                        </Button>
                        <Button
                          size="sm"
                          className="h-7 px-2 text-xs"
                          disabled={
                            row.account_status !== "active" ||
                            !row.stripe_account_id ||
                            (row.outstanding_amount ?? 0) <= 0 ||
                            sendPayout.isPending
                          }
                          onClick={() => setConfirmSend(row)}
                        >
                          <Send className="h-3 w-3 mr-1" />
                          Send Now
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Schedule modal */}
      <Dialog open={!!scheduleTarget} onOpenChange={(open) => !open && setScheduleTarget(null)}>
        {scheduleTarget && (
          <ScheduleModal row={scheduleTarget} onClose={() => setScheduleTarget(null)} />
        )}
      </Dialog>

      {/* Confirm send modal */}
      <Dialog open={!!confirmSend} onOpenChange={(open) => !open && setConfirmSend(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Send className="h-5 w-5" />
              Confirm Payout
            </DialogTitle>
          </DialogHeader>
          {confirmSend && (
            <div className="space-y-4 pt-2">
              <p className="text-sm text-muted-foreground">
                Send{" "}
                <span className="font-semibold text-foreground">
                  {fmtCurrency(confirmSend.outstanding_amount)}
                </span>{" "}
                to{" "}
                <span className="font-semibold text-foreground">
                  {confirmSend.owner_name}
                </span>{" "}
                via Stripe Connect?
              </p>
              {confirmSend.stripe_account_id && (
                <p className="text-xs text-muted-foreground font-mono">
                  {confirmSend.stripe_account_id}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setConfirmSend(null)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  disabled={sendPayout.isPending}
                  onClick={() => {
                    sendPayout.mutate(
                      { propertyId: confirmSend.property_id },
                      { onSuccess: () => setConfirmSend(null) }
                    );
                  }}
                >
                  {sendPayout.isPending ? (
                    <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Sending…</>
                  ) : (
                    <><Send className="mr-1.5 h-4 w-4" /> Send Payout</>
                  )}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
