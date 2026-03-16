"use client";

import { useState, useRef, useMemo } from "react";
import {
  useDisputeStats,
  useDisputes,
  useUploadDisputeEvidence,
  type DisputeListItem,
} from "@/lib/hooks";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
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
  Download,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Swords,
  TrendingUp,
  Upload,
  Wifi,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Reason code badge styling
// ---------------------------------------------------------------------------

const REASON_CONFIG: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  fraudulent: { label: "Fraudulent", variant: "destructive" },
  unrecognized: { label: "Unrecognized", variant: "destructive" },
  product_unacceptable: { label: "Product Issue", variant: "default" },
  product_not_received: { label: "Not Received", variant: "secondary" },
  general: { label: "General", variant: "outline" },
};

function ReasonBadge({ reason }: { reason: string }) {
  const cfg = REASON_CONFIG[reason] ?? { label: reason, variant: "outline" as const };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}

const EVIDENCE_STATUS_CONFIG: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { label: "Pending", variant: "secondary" },
  evidence_compiled: { label: "Compiled", variant: "default" },
  submitted: { label: "Submitted", variant: "outline" },
  won: { label: "Won", variant: "default" },
  lost: { label: "Lost", variant: "destructive" },
  expired: { label: "Expired", variant: "destructive" },
};

function EvidenceBadge({ status }: { status: string }) {
  const cfg = EVIDENCE_STATUS_CONFIG[status] ?? {
    label: status,
    variant: "outline" as const,
  };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}

function fmtCurrency(amount: number | null | undefined): string {
  if (amount == null) return "$0.00";
  return `$${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function deadlineLabel(days: number | null): string {
  if (days == null) return "—";
  if (days <= 0) return "OVERDUE";
  if (days === 1) return "1 day";
  return `${days} days`;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function DisputeExceptionDesk({
  onBack,
}: {
  onBack: () => void;
}) {
  const { data: stats, isLoading: statsLoading } = useDisputeStats();
  const { data: disputeList, isLoading: listLoading } = useDisputes();
  const uploadMutation = useUploadDisputeEvidence();

  const [selectedDispute, setSelectedDispute] = useState<DisputeListItem | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const disputes = useMemo(() => disputeList?.data ?? [], [disputeList]);

  const handleUpload = () => {
    const file = fileRef.current?.files?.[0];
    if (!file || !selectedDispute) return;
    uploadMutation.mutate(
      { disputeId: selectedDispute.dispute_id, file },
      {
        onSuccess: () => {
          if (fileRef.current) fileRef.current.value = "";
        },
      }
    );
  };

  // ─── Telemetry HUD ──────────────────────────────────────────────────────
  const hudCards = [
    {
      title: "Win Rate",
      value: stats ? `${stats.win_rate_pct}%` : "—",
      desc: stats
        ? `${stats.win_count}W / ${stats.loss_count}L`
        : "Loading…",
      icon: <ShieldCheck className="h-5 w-5 text-emerald-500" />,
      accent:
        (stats?.win_rate_pct ?? 0) >= 80
          ? "text-emerald-400"
          : "text-red-400",
    },
    {
      title: "Disputed Funds",
      value: stats ? fmtCurrency(stats.total_disputed_amount) : "—",
      desc: "Currently locked by Stripe",
      icon: <ShieldAlert className="h-5 w-5 text-amber-500" />,
      accent: "text-amber-400",
    },
    {
      title: "Active Operations",
      value: stats?.total_active?.toString() ?? "—",
      desc: "Defense packets in flight",
      icon: <Swords className="h-5 w-5 text-blue-500" />,
      accent: "text-blue-400",
    },
    {
      title: "Recovered YTD",
      value: stats ? fmtCurrency(stats.funds_recovered_ytd) : "—",
      desc: "Chargebacks defeated this year",
      icon: <TrendingUp className="h-5 w-5 text-emerald-500" />,
      accent: "text-emerald-400",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">
              Dispute Exception Desk
            </h2>
            <p className="text-sm text-muted-foreground">
              Chargeback Ironclad — Autonomous Defense Monitoring
            </p>
          </div>
        </div>
      </div>

      {/* HUD Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {hudCards.map((c) => (
          <Card key={c.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{c.title}</CardTitle>
              {c.icon}
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${c.accent}`}>
                {statsLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  c.value
                )}
              </div>
              <p className="text-xs text-muted-foreground">{c.desc}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Reason Code Breakdown */}
      {stats && Object.keys(stats.by_reason_code).length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              Disputes by Reason Code
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.by_reason_code).map(([reason, info]) => (
                <div
                  key={reason}
                  className="flex items-center gap-2 rounded-lg border px-3 py-2"
                >
                  <ReasonBadge reason={reason} />
                  <span className="text-sm font-medium">{info.count}</span>
                  <span className="text-xs text-muted-foreground">
                    ({fmtCurrency(info.amount)})
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Active Battlefield Table */}
      <Card>
        <CardHeader>
          <CardTitle>Active Battlefield</CardTitle>
          <CardDescription>
            All disputes sorted by response deadline urgency
          </CardDescription>
        </CardHeader>
        <CardContent>
          {listLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : disputes.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              <ShieldCheck className="mx-auto mb-3 h-10 w-10 opacity-40" />
              <p className="text-lg font-medium">All Clear</p>
              <p className="text-sm">No active chargebacks — the Iron Dome holds.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Guest</TableHead>
                  <TableHead>Property</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Evidence</TableHead>
                  <TableHead>Deadline</TableHead>
                  <TableHead className="text-center">IoT</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {disputes.map((d) => (
                  <TableRow
                    key={d.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setSelectedDispute(d)}
                  >
                    <TableCell className="font-medium">
                      {d.guest_name}
                    </TableCell>
                    <TableCell>{d.property_name}</TableCell>
                    <TableCell className="text-right font-mono">
                      {fmtCurrency(d.dispute_amount)}
                    </TableCell>
                    <TableCell>
                      <ReasonBadge reason={d.dispute_reason} />
                    </TableCell>
                    <TableCell>
                      <EvidenceBadge status={d.evidence_status} />
                    </TableCell>
                    <TableCell>
                      <span
                        className={
                          (d.days_remaining ?? 99) <= 2
                            ? "font-bold text-red-500"
                            : (d.days_remaining ?? 99) <= 4
                              ? "font-semibold text-amber-500"
                              : ""
                        }
                      >
                        {deadlineLabel(d.days_remaining)}
                      </span>
                    </TableCell>
                    <TableCell className="text-center">
                      {d.iot_events_count > 0 ? (
                        <span className="inline-flex items-center gap-1 text-emerald-500">
                          <Wifi className="h-3.5 w-3.5" />
                          {d.iot_events_count}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {disputeList?.pagination && disputeList.pagination.total > 0 && (
            <p className="mt-3 text-xs text-muted-foreground text-right">
              Showing {disputes.length} of {disputeList.pagination.total} disputes
            </p>
          )}
        </CardContent>
      </Card>

      {/* Detail Sheet */}
      <Sheet
        open={!!selectedDispute}
        onOpenChange={(open) => {
          if (!open) setSelectedDispute(null);
        }}
      >
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          {selectedDispute && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5 text-red-500" />
                  Dispute Detail
                </SheetTitle>
                <SheetDescription>
                  {selectedDispute.dispute_id}
                </SheetDescription>
              </SheetHeader>

              <div className="mt-6 space-y-5">
                {/* Summary Grid */}
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-muted-foreground">Guest</p>
                    <p className="font-medium">{selectedDispute.guest_name}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Property</p>
                    <p className="font-medium">{selectedDispute.property_name}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Disputed Amount</p>
                    <p className="font-mono font-bold text-red-500">
                      {fmtCurrency(selectedDispute.dispute_amount)}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Reason Code</p>
                    <ReasonBadge reason={selectedDispute.dispute_reason} />
                  </div>
                  <div>
                    <p className="text-muted-foreground">Confirmation</p>
                    <p className="font-mono">
                      {selectedDispute.confirmation_code ?? "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Stay Dates</p>
                    <p className="text-xs">
                      {selectedDispute.check_in_date ?? "—"} →{" "}
                      {selectedDispute.check_out_date ?? "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Evidence Status</p>
                    <EvidenceBadge status={selectedDispute.evidence_status} />
                  </div>
                  <div>
                    <p className="text-muted-foreground">Deadline</p>
                    <p
                      className={
                        (selectedDispute.days_remaining ?? 99) <= 2
                          ? "font-bold text-red-500"
                          : ""
                      }
                    >
                      {deadlineLabel(selectedDispute.days_remaining)}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">IoT Events</p>
                    <p>
                      {selectedDispute.iot_events_count > 0 ? (
                        <span className="text-emerald-500 font-medium">
                          {selectedDispute.iot_events_count} events
                        </span>
                      ) : (
                        "None"
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Stripe Status</p>
                    <p className="capitalize">
                      {selectedDispute.dispute_status?.replace(/_/g, " ") ?? "—"}
                    </p>
                  </div>
                </div>

                {/* Evidence PDF Download */}
                {selectedDispute.has_evidence_pdf && (
                  <Button
                    variant="outline"
                    className="w-full"
                    asChild
                  >
                    <a
                      href={`/api/admin/disputes/${selectedDispute.dispute_id}/evidence`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Download className="mr-2 h-4 w-4" />
                      Download Evidence Packet (PDF)
                    </a>
                  </Button>
                )}

                {/* Manual Upload */}
                <div className="space-y-3 rounded-lg border p-4">
                  <h4 className="text-sm font-semibold flex items-center gap-2">
                    <Upload className="h-4 w-4" />
                    Upload Additional Evidence
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    Upload damage photos, receipts, or inspection documents.
                    The Ironclad will re-compile and re-submit the full evidence
                    packet to Stripe automatically.
                  </p>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/*,.pdf,.doc,.docx"
                    className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
                  />
                  <Button
                    onClick={handleUpload}
                    disabled={uploadMutation.isPending}
                    className="w-full"
                  >
                    {uploadMutation.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Uploading & Re-compiling…
                      </>
                    ) : (
                      <>
                        <Upload className="mr-2 h-4 w-4" />
                        Re-compile &amp; Submit to Stripe
                      </>
                    )}
                  </Button>
                </div>

                {selectedDispute.submitted_to_stripe_at && (
                  <p className="text-xs text-muted-foreground text-center">
                    Last submitted to Stripe:{" "}
                    {new Date(
                      selectedDispute.submitted_to_stripe_at
                    ).toLocaleString()}
                  </p>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
