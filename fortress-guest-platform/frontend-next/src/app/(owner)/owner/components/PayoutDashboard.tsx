"use client";

import { useState } from "react";
import {
  usePayoutAccount,
  usePayoutHistory,
  useSetupPayouts,
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
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Banknote,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ExternalLink,
  Loader2,
  Zap,
  XCircle,
} from "lucide-react";

interface PayoutEntry {
  id: number;
  confirmation_code: string;
  gross_amount: number;
  owner_amount: number;
  status: string;
  stripe_transfer_id: string | null;
  initiated_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

interface AccountStatus {
  has_account: boolean;
  account_status: string;
  instant_payout: boolean;
  owner_email?: string;
  charges_enabled?: boolean;
  payouts_enabled?: boolean;
  message?: string;
}

interface PayoutHistoryData {
  property_id: string;
  total_paid_out: number;
  pending_count: number;
  payout_count: number;
  payouts: PayoutEntry[];
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<
    string,
    { variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ReactNode }
  > = {
    completed: {
      variant: "default",
      icon: <CheckCircle2 className="h-3 w-3 mr-1" />,
    },
    processing: {
      variant: "secondary",
      icon: <Clock className="h-3 w-3 mr-1 animate-pulse" />,
    },
    staged: {
      variant: "outline",
      icon: <Clock className="h-3 w-3 mr-1" />,
    },
    manual: {
      variant: "secondary",
      icon: <Banknote className="h-3 w-3 mr-1" />,
    },
    failed: {
      variant: "destructive",
      icon: <XCircle className="h-3 w-3 mr-1" />,
    },
  };
  const v = variants[status] ?? { variant: "outline" as const, icon: null };
  return (
    <Badge variant={v.variant} className="text-xs capitalize">
      {v.icon}
      {status}
    </Badge>
  );
}

export function PayoutDashboard({ propertyId }: { propertyId: string }) {
  const account = usePayoutAccount(propertyId);
  const history = usePayoutHistory(propertyId);
  const setupPayouts = useSetupPayouts(propertyId);
  const [email, setEmail] = useState("");

  const acct = account.data as AccountStatus | undefined;
  const hist = history.data as PayoutHistoryData | undefined;

  const handleSetup = () => {
    if (!email) return;
    setupPayouts.mutate({ owner_email: email });
  };

  return (
    <div className="space-y-6">
      {/* Account status */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Account Status</p>
            {acct?.has_account ? (
              <Badge
                variant={
                  acct.account_status === "active" ? "default" : "secondary"
                }
                className="mt-1 capitalize"
              >
                {acct.account_status === "active" && (
                  <Zap className="h-3 w-3 mr-1" />
                )}
                {acct.account_status}
              </Badge>
            ) : (
              <p className="text-sm text-muted-foreground mt-1">
                Not configured
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Total Paid Out</p>
            <p className="text-2xl font-bold font-mono text-emerald-500">
              ${hist?.total_paid_out?.toLocaleString() ?? "0.00"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Pending</p>
            <p className="text-2xl font-bold font-mono">
              {hist?.pending_count ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Setup flow (when no account exists) */}
      {acct && !acct.has_account && (
        <Card className="border-dashed">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="h-4 w-4 text-emerald-500" />
              Enable Instant Payouts
            </CardTitle>
            <CardDescription>
              Connect your bank account to receive payouts the moment your guest
              checks out. No more waiting 30 days.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <Input
                placeholder="Owner email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="max-w-sm"
              />
              <Button
                onClick={handleSetup}
                disabled={setupPayouts.isPending || !email}
              >
                {setupPayouts.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                    Setting up...
                  </>
                ) : (
                  "Connect Bank Account"
                )}
              </Button>
            </div>
            {setupPayouts.data?.onboarding_url && (
              <div className="mt-3 flex items-center gap-2 text-sm text-emerald-500">
                <ExternalLink className="h-4 w-4" />
                <a
                  href={setupPayouts.data.onboarding_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  Complete Stripe onboarding
                </a>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Onboarding in progress */}
      {acct?.has_account && acct.account_status === "onboarding" && (
        <div className="flex items-center gap-2 text-sm text-amber-500 border border-amber-500/30 rounded-md p-3 bg-amber-500/5">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Stripe onboarding in progress. Complete the verification to enable
          instant payouts. Check your email for the onboarding link.
        </div>
      )}

      {/* Active account badge */}
      {acct?.has_account && acct.account_status === "active" && (
        <div className="flex items-center gap-2 text-sm text-emerald-500 border border-emerald-500/30 rounded-md p-3 bg-emerald-500/5">
          <Zap className="h-4 w-4 flex-shrink-0" />
          Continuous Liquidity is active. Payouts are processed instantly upon
          guest checkout.
        </div>
      )}

      {/* Payout history */}
      {hist && hist.payouts.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Payout History</CardTitle>
            <CardDescription>
              {hist.payout_count} disbursement
              {hist.payout_count !== 1 ? "s" : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reservation</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                  <TableHead className="text-right">Your Payout</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {hist.payouts.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">
                      {p.confirmation_code || "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      ${p.gross_amount.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right font-mono font-semibold text-emerald-500">
                      ${p.owner_amount.toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={p.status} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.completed_at
                        ? new Date(p.completed_at).toLocaleDateString()
                        : p.initiated_at
                          ? new Date(p.initiated_at).toLocaleDateString()
                          : p.created_at
                            ? new Date(p.created_at).toLocaleDateString()
                            : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {hist && hist.payouts.length === 0 && (
        <div className="text-center py-8 text-muted-foreground text-sm">
          No payouts yet. Payouts are generated automatically when guests
          check out of your property.
        </div>
      )}
    </div>
  );
}
