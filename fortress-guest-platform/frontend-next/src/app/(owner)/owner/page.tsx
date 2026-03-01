"use client";

import { useState } from "react";
import {
  useOwnerDashboard,
  useOwnerStatements,
  useOwnerReservations,
  useOwnerBalances,
  useIronDomeActivity,
  useLegacyStatements,
  useProperties,
  useWorkOrders,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertTriangle,
  Building2,
  CalendarDays,
  DollarSign,
  Download,
  FileText,
  MessageSquare,
  Banknote,
  Pickaxe,
  Radio,
  Shield,
  TrendingUp,
  Wrench,
} from "lucide-react";
import { OwnerCalendar } from "./components/OwnerCalendar";
import { CapexApprovalCards } from "./components/CapexApprovalCards";
import { OwnerConcierge } from "./components/OwnerConcierge";
import { RoiSimulator } from "./components/RoiSimulator";
import { DigitalTwinHud } from "./components/DigitalTwinHud";
import { PayoutDashboard } from "./components/PayoutDashboard";
import DirectBookingEngine from "./components/DirectBookingEngine";

interface DashboardData {
  total_properties: number;
  active_reservations: number;
  revenue_mtd: number;
  revenue_ytd: number;
  occupancy_rate: number;
  open_work_orders: number;
  upcoming_reservations: number;
}

interface StatementRow {
  id: string;
  period_start: string;
  period_end: string;
  gross_revenue: number;
  management_fee: number;
  cleaning_fees: number;
  maintenance_costs: number;
  net_payout: number;
  status: string;
  generated_at: string;
}

interface TrustBalanceRow {
  property_id: string;
  owner_funds: number;
  operating_funds: number;
  escrow_funds: number;
  security_deposits: number;
  last_updated: string | null;
}

interface BalancesData {
  trust_balances: TrustBalanceRow[];
  property_balances: Array<Record<string, unknown>>;
}

interface ActivityRow {
  id: number;
  date: string;
  description: string;
  amount: number;
}

interface LegacyStatement {
  id: string;
  month: string;
  period_start: string;
  period_end: string;
  source: string;
  download_url: string;
}

function fmt(n: number | null | undefined): string {
  if (n == null) return "–";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function OwnerPortalPage() {
  const [ownerId, setOwnerId] = useState<string>("");

  const { data: properties } = useProperties();
  const { data: dashboardRaw } = useOwnerDashboard(ownerId);
  const dashboard = dashboardRaw as DashboardData | undefined;
  const { data: statementsRaw } = useOwnerStatements(ownerId);
  const statements = statementsRaw as StatementRow[] | undefined;
  const { data: reservations } = useOwnerReservations(ownerId);
  const { data: workOrders } = useWorkOrders();
  const { data: balancesRaw } = useOwnerBalances(ownerId);
  const balances = balancesRaw as BalancesData | undefined;
  const { data: activityRaw } = useIronDomeActivity(ownerId);
  const activity = activityRaw as { transactions: ActivityRow[] } | undefined;
  const { data: legacyRaw } = useLegacyStatements(ownerId);
  const legacy = legacyRaw as { statements: LegacyStatement[] } | undefined;

  const trustRow = balances?.trust_balances?.[0];
  const operatingFunds = trustRow?.operating_funds ?? 0;
  const capitalCallActive = operatingFunds <= 0 && !!ownerId;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Owner Portal</h1>
          <p className="text-muted-foreground">
            Property performance, trust accounting, and financial overview
          </p>
        </div>
        <div className="w-72">
          <Select value={ownerId} onValueChange={setOwnerId}>
            <SelectTrigger>
              <SelectValue placeholder="Select a property / owner…" />
            </SelectTrigger>
            <SelectContent>
              {(properties ?? []).map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {!ownerId && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Building2 className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>Select a property above to view the owner dashboard</p>
          </CardContent>
        </Card>
      )}

      {ownerId && (
        <>
          {capitalCallActive && (
            <Card className="border-destructive bg-destructive/5">
              <CardContent className="flex items-center gap-3 py-4">
                <AlertTriangle className="h-5 w-5 text-destructive shrink-0" />
                <div>
                  <p className="font-semibold text-destructive">Capital Call Required</p>
                  <p className="text-sm text-muted-foreground">
                    Operating funds are depleted. Pending work orders and invoices cannot be
                    processed until additional funds are deposited into the trust account.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Revenue MTD
                </CardTitle>
                <DollarSign className="h-4 w-4 text-green-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  ${fmt(dashboard?.revenue_mtd)}
                </div>
                <p className="text-xs text-muted-foreground">
                  YTD: ${fmt(dashboard?.revenue_ytd)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Occupancy
                </CardTitle>
                <TrendingUp className="h-4 w-4 text-emerald-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {dashboard ? `${Math.round(dashboard.occupancy_rate)}%` : "–"}
                </div>
                <p className="text-xs text-muted-foreground">
                  {dashboard?.active_reservations ?? 0} active reservations
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Properties
                </CardTitle>
                <Building2 className="h-4 w-4 text-blue-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {dashboard?.total_properties ?? "–"}
                </div>
                <p className="text-xs text-muted-foreground">
                  {dashboard?.upcoming_reservations ?? 0} upcoming bookings
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Work Orders
                </CardTitle>
                <Wrench className="h-4 w-4 text-orange-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {dashboard?.open_work_orders ?? "–"}
                </div>
                <p className="text-xs text-muted-foreground">Open issues</p>
              </CardContent>
            </Card>
          </div>

          <Tabs defaultValue="trust-account">
            <TabsList>
              <TabsTrigger value="trust-account">
                <Shield className="h-4 w-4 mr-1" />
                Trust Account
              </TabsTrigger>
              <TabsTrigger value="statements">
                <FileText className="h-4 w-4 mr-1" />
                Statements
              </TabsTrigger>
              <TabsTrigger value="calendar">
                <CalendarDays className="h-4 w-4 mr-1" />
                Reservations
              </TabsTrigger>
              <TabsTrigger value="work-orders">
                <Wrench className="h-4 w-4 mr-1" />
                Work Orders
              </TabsTrigger>
              <TabsTrigger value="concierge">
                <MessageSquare className="h-4 w-4 mr-1" />
                Concierge
              </TabsTrigger>
              <TabsTrigger value="investments">
                <Pickaxe className="h-4 w-4 mr-1" />
                Investments
              </TabsTrigger>
              <TabsTrigger value="asset-health">
                <Radio className="h-4 w-4 mr-1" />
                Asset Health
              </TabsTrigger>
              <TabsTrigger value="payouts">
                <Banknote className="h-4 w-4 mr-1" />
                Payouts
              </TabsTrigger>
              <TabsTrigger value="direct-booking">
                <TrendingUp className="h-4 w-4 mr-1" />
                Direct Booking
              </TabsTrigger>
            </TabsList>

            {/* ============================================================ */}
            {/* TRUST ACCOUNT TAB                                            */}
            {/* ============================================================ */}
            <TabsContent value="trust-account" className="mt-4 space-y-4">
              <div className="grid gap-4 md:grid-cols-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardDescription>Owner Funds</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="text-xl font-bold">${fmt(trustRow?.owner_funds)}</div>
                  </CardContent>
                </Card>
                <Card className={operatingFunds <= 0 ? "border-destructive" : ""}>
                  <CardHeader className="pb-2">
                    <CardDescription>Operating Funds</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className={`text-xl font-bold ${operatingFunds <= 0 ? "text-destructive" : ""}`}>
                      ${fmt(trustRow?.operating_funds)}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardDescription>Escrow</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="text-xl font-bold">${fmt(trustRow?.escrow_funds)}</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardDescription>Security Deposits</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="text-xl font-bold">${fmt(trustRow?.security_deposits)}</div>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Pending CapEx Approvals</CardTitle>
                  <CardDescription>
                    High-ticket invoices staged for your authorization before dispatch
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <CapexApprovalCards propertyId={ownerId} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Recent Account Activity</CardTitle>
                  <CardDescription>
                    Operational charges processed against the trust account
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(activity?.transactions ?? []).length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={3} className="text-center py-8 text-muted-foreground">
                            No recent activity
                          </TableCell>
                        </TableRow>
                      ) : (
                        (activity?.transactions ?? []).map((t) => (
                          <TableRow key={t.id}>
                            <TableCell className="text-sm">{t.date}</TableCell>
                            <TableCell className="text-sm">{t.description}</TableCell>
                            <TableCell className="text-right text-sm font-medium">
                              ${fmt(t.amount)}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* STATEMENTS TAB — Unified Timeline                            */}
            {/* ============================================================ */}
            <TabsContent value="statements" className="mt-4 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Iron Dome Statements</CardTitle>
                  <CardDescription>Real-time financial statements from the sovereign ledger</CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Period</TableHead>
                        <TableHead className="text-right">Gross Revenue</TableHead>
                        <TableHead className="text-right">Mgmt Fee</TableHead>
                        <TableHead className="text-right">Cleaning</TableHead>
                        <TableHead className="text-right">Maintenance</TableHead>
                        <TableHead className="text-right">Net Payout</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(statements ?? []).length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                            No statements available
                          </TableCell>
                        </TableRow>
                      ) : (
                        (statements ?? []).map((s) => (
                          <TableRow key={s.id}>
                            <TableCell className="text-sm">
                              <div className="flex items-center gap-2">
                                {s.period_start} — {s.period_end}
                                <Badge variant="default" className="text-[10px] px-1.5 py-0">
                                  Live
                                </Badge>
                              </div>
                            </TableCell>
                            <TableCell className="text-right text-sm">
                              ${fmt(s.gross_revenue)}
                            </TableCell>
                            <TableCell className="text-right text-sm text-muted-foreground">
                              -${fmt(s.management_fee)}
                            </TableCell>
                            <TableCell className="text-right text-sm text-muted-foreground">
                              -${fmt(s.cleaning_fees)}
                            </TableCell>
                            <TableCell className="text-right text-sm text-muted-foreground">
                              -${fmt(s.maintenance_costs)}
                            </TableCell>
                            <TableCell className="text-right text-sm font-semibold">
                              ${fmt(s.net_payout)}
                            </TableCell>
                            <TableCell>
                              <Badge variant={s.status === "paid" ? "default" : "secondary"}>
                                {s.status}
                              </Badge>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Historical Statements</CardTitle>
                  <CardDescription>
                    Archived statements from the legacy property management system
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Period</TableHead>
                        <TableHead>Source</TableHead>
                        <TableHead className="text-right">Download</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(legacy?.statements ?? []).length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={3} className="text-center py-8 text-muted-foreground">
                            No historical statements available
                          </TableCell>
                        </TableRow>
                      ) : (
                        (legacy?.statements ?? []).map((ls) => (
                          <TableRow key={ls.id}>
                            <TableCell className="text-sm">{ls.month}</TableCell>
                            <TableCell>
                              <Badge variant="secondary" className="text-[10px]">
                                Streamline
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 gap-1"
                                asChild
                              >
                                <a href={ls.download_url} target="_blank" rel="noopener noreferrer">
                                  <Download className="h-3.5 w-3.5" />
                                  PDF
                                </a>
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* CALENDAR & OWNER BLOCKS TAB (Yield Loss Engine)              */}
            {/* ============================================================ */}
            <TabsContent value="calendar" className="mt-4 space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Property Calendar</CardTitle>
                  <CardDescription>
                    Click available dates to request an owner hold. The Yield Loss Engine
                    will calculate the revenue impact before confirming.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <OwnerCalendar propertyId={ownerId} />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* WORK ORDERS TAB                                              */}
            {/* ============================================================ */}
            <TabsContent value="work-orders" className="mt-4">
              <Card>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Title</TableHead>
                        <TableHead>Property</TableHead>
                        <TableHead>Priority</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Created</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(workOrders ?? []).length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                            No work orders
                          </TableCell>
                        </TableRow>
                      ) : (
                        (workOrders ?? []).slice(0, 20).map((wo) => (
                          <TableRow key={wo.id}>
                            <TableCell className="text-sm font-medium">
                              {wo.title}
                            </TableCell>
                            <TableCell className="text-sm">
                              {wo.property?.name ?? "–"}
                            </TableCell>
                            <TableCell>
                              <Badge variant={wo.priority === "urgent" ? "destructive" : "secondary"} className="text-xs">
                                {wo.priority}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              <Badge variant="outline" className="text-xs">
                                {wo.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                              {(wo.created_at ?? "").slice(0, 10)}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* CONCIERGE TAB — AI Chat with Information Wall                 */}
            {/* ============================================================ */}
            <TabsContent value="concierge" className="mt-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Fiduciary Concierge</CardTitle>
                  <CardDescription>
                    Ask questions about your property finances, reservations, maintenance,
                    or trust account. Powered by on-premise AI.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <OwnerConcierge propertyId={ownerId} />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* INVESTMENTS TAB — ROI Simulator (Wealth Multiplier)           */}
            {/* ============================================================ */}
            <TabsContent value="investments" className="mt-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Pickaxe className="h-4 w-4 text-emerald-500" />
                    CROG Alpha: Wealth Multiplier
                  </CardTitle>
                  <CardDescription>
                    Data-driven upgrade recommendations powered by Blue Ridge market
                    intelligence. One-click authorization dispatches CROG Development.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <RoiSimulator propertyId={ownerId} />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* ASSET HEALTH TAB — IoT Digital Twin                          */}
            {/* ============================================================ */}
            <TabsContent value="asset-health" className="mt-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Radio className="h-4 w-4 text-blue-400" />
                    Live Asset Telemetry
                  </CardTitle>
                  <CardDescription>
                    Real-time physical status of your cabin — locks, climate,
                    sensors, and cameras. Powered by Z-Wave mesh telemetry.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <DigitalTwinHud propertyId={ownerId} />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ============================================================ */}
            {/* PAYOUTS TAB — Continuous Liquidity                           */}
            {/* ============================================================ */}
            <TabsContent value="payouts" className="mt-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Banknote className="h-4 w-4 text-emerald-500" />
                    Continuous Liquidity
                  </CardTitle>
                  <CardDescription>
                    Real-time payouts — get paid the moment your guest checks out.
                    No more waiting for end-of-month statements.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <PayoutDashboard propertyId={ownerId} />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="direct-booking" className="mt-4">
              <DirectBookingEngine propertyId={ownerId} />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
