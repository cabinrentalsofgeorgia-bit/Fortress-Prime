"use client";

import { useState } from "react";
import {
  useMarketingPreferences,
  useUpdateMarketingPreferences,
  useMarketingAttribution,
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
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  TrendingUp,
  DollarSign,
  BarChart3,
  Target,
  Loader2,
  Zap,
  ArrowRight,
  PiggyBank,
  MousePointerClick,
  Eye,
  CalendarDays,
} from "lucide-react";

interface DirectBookingEngineProps {
  propertyId: string;
}

const PRESET_STOPS = [0, 2, 5, 10];
const OTA_FEE_PCT = 15;

export default function DirectBookingEngine({
  propertyId,
}: DirectBookingEngineProps) {
  const { data: prefs, isLoading: prefsLoading } =
    useMarketingPreferences(propertyId);
  const { data: attribution, isLoading: attrLoading } =
    useMarketingAttribution(propertyId);
  const updatePrefs = useUpdateMarketingPreferences(propertyId);

  const [localPct, setLocalPct] = useState<number | null>(null);
  const [localEnabled, setLocalEnabled] = useState<boolean | null>(null);

  const currentPct = localPct ?? prefs?.marketing_pct ?? 0;
  const currentEnabled = localEnabled ?? prefs?.enabled ?? false;
  const escrowBalance = prefs?.escrow_balance ?? 0;

  const isDirty =
    localPct !== null && localPct !== (prefs?.marketing_pct ?? 0) ||
    localEnabled !== null && localEnabled !== (prefs?.enabled ?? false);

  const handleSave = () => {
    updatePrefs.mutate(
      { marketing_pct: currentPct, enabled: currentEnabled },
      {
        onSuccess: () => {
          setLocalPct(null);
          setLocalEnabled(null);
        },
      }
    );
  };

  const netSavings = OTA_FEE_PCT - currentPct;
  const sampleBooking = 1000;
  const adAllocation = (sampleBooking * currentPct) / 100;

  if (prefsLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
          <Zap className="h-5 w-5 text-emerald-500" />
          Direct Booking Engine
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Allocate a portion of your earnings to targeted ad campaigns. Bypass
          OTA platform fees and drive direct bookings to your property.
        </p>
      </div>

      {/* Row 1: Boost Dial + Escrow Balance */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Marketing Boost Dial */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Target className="h-4 w-4 text-emerald-500" />
              Marketing Boost
            </CardTitle>
            <CardDescription>
              Set the percentage of your revenue share to reinvest
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                Allocation active
              </span>
              <Switch
                checked={currentEnabled}
                onCheckedChange={(v) => setLocalEnabled(v)}
              />
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-3xl font-bold tabular-nums">
                  {currentPct}%
                </span>
                <div className="flex gap-1">
                  {PRESET_STOPS.map((stop) => (
                    <Button
                      key={stop}
                      variant={currentPct === stop ? "default" : "outline"}
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => setLocalPct(stop)}
                    >
                      {stop}%
                    </Button>
                  ))}
                </div>
              </div>
              <Slider
                value={[currentPct]}
                onValueChange={(v) => setLocalPct(v[0])}
                max={25}
                step={0.5}
                className="py-1"
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>0%</span>
                <span>25% max</span>
              </div>
            </div>

            {currentPct > 0 && (
              <div className="rounded-lg border bg-muted/50 p-3">
                <p className="text-sm">
                  On a{" "}
                  <span className="font-semibold">
                    ${sampleBooking.toLocaleString()}
                  </span>{" "}
                  booking,{" "}
                  <span className="font-semibold text-emerald-500">
                    ${adAllocation.toFixed(0)}
                  </span>{" "}
                  goes to your ad campaign.
                </p>
              </div>
            )}

            {isDirty && (
              <Button
                onClick={handleSave}
                disabled={updatePrefs.isPending}
                className="w-full bg-emerald-600 hover:bg-emerald-700"
              >
                {updatePrefs.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : null}
                Save Allocation
              </Button>
            )}
          </CardContent>
        </Card>

        {/* Escrow Balance */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <PiggyBank className="h-4 w-4 text-blue-500" />
              Marketing Escrow
            </CardTitle>
            <CardDescription>
              Funds available for direct-booking campaigns
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-4xl font-bold tabular-nums">
              ${escrowBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <Badge
              variant={escrowBalance > 0 ? "default" : "secondary"}
              className={
                escrowBalance > 0
                  ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                  : ""
              }
            >
              Account 2400 — Owner Marketing Escrow
            </Badge>
            <p className="text-sm text-muted-foreground">
              These funds are held in fiduciary trust and allocated to Google Ads
              campaigns targeting your property. Taylor manages campaign
              execution and reports attribution metrics below.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Row 2: Savings Calculator */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-amber-500" />
            OTA Fee Savings Calculator
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="rounded-lg border p-4">
              <p className="text-xs text-muted-foreground mb-1">OTA Fee (Airbnb/Vrbo)</p>
              <p className="text-2xl font-bold text-red-400">{OTA_FEE_PCT}%</p>
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-xs text-muted-foreground mb-1">Your Ad Cost</p>
              <p className="text-2xl font-bold text-emerald-500">
                {currentPct}%
              </p>
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-xs text-muted-foreground mb-1">Net Savings per Booking</p>
              <p className="text-2xl font-bold text-blue-400">
                {netSavings > 0 ? `${netSavings}%` : "—"}
              </p>
            </div>
          </div>
          {netSavings > 0 && (
            <p className="text-sm text-muted-foreground mt-3 text-center">
              Every direct booking saves you{" "}
              <span className="font-semibold text-foreground">
                ${((sampleBooking * netSavings) / 100).toFixed(0)}
              </span>{" "}
              compared to an OTA-sourced booking on a ${sampleBooking.toLocaleString()} reservation.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Row 3: Attribution Matrix */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-violet-500" />
            Attribution Matrix
          </CardTitle>
          <CardDescription>
            Campaign performance data — updated by your property manager
          </CardDescription>
        </CardHeader>
        <CardContent>
          {attrLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : !attribution?.periods?.length ? (
            <div className="text-center py-8 text-muted-foreground">
              <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-40" />
              <p className="text-sm">No campaign data yet.</p>
              <p className="text-xs mt-1">
                Attribution metrics will appear here once your property manager
                enters campaign performance data.
              </p>
            </div>
          ) : (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
                <MiniStat
                  icon={<DollarSign className="h-3.5 w-3.5" />}
                  label="Total Spend"
                  value={`$${attribution.totals.ad_spend.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                />
                <MiniStat
                  icon={<Eye className="h-3.5 w-3.5" />}
                  label="Impressions"
                  value={attribution.totals.impressions.toLocaleString()}
                />
                <MiniStat
                  icon={<MousePointerClick className="h-3.5 w-3.5" />}
                  label="Clicks"
                  value={attribution.totals.clicks.toLocaleString()}
                />
                <MiniStat
                  icon={<CalendarDays className="h-3.5 w-3.5" />}
                  label="Direct Bookings"
                  value={String(attribution.totals.direct_bookings)}
                />
                <MiniStat
                  icon={<TrendingUp className="h-3.5 w-3.5" />}
                  label="ROAS"
                  value={`${attribution.totals.roas.toFixed(1)}x`}
                  highlight
                />
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Period</TableHead>
                    <TableHead className="text-right">Ad Spend</TableHead>
                    <TableHead className="text-right">Impressions</TableHead>
                    <TableHead className="text-right">Clicks</TableHead>
                    <TableHead className="text-right">Bookings</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead className="text-right">ROAS</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {attribution.periods.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-medium text-xs">
                        {p.period_start}
                        <ArrowRight className="h-3 w-3 inline mx-1 text-muted-foreground" />
                        {p.period_end}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        ${p.ad_spend.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {p.impressions.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {p.clicks.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {p.direct_bookings}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        ${p.gross_revenue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge
                          variant="secondary"
                          className={
                            p.roas >= 3
                              ? "bg-emerald-500/10 text-emerald-500"
                              : p.roas >= 1
                                ? "bg-blue-500/10 text-blue-500"
                                : "bg-red-500/10 text-red-400"
                          }
                        >
                          {p.roas.toFixed(1)}x
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MiniStat({
  icon,
  label,
  value,
  highlight,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        {icon}
        <span className="text-xs">{label}</span>
      </div>
      <p
        className={`text-lg font-bold tabular-nums ${highlight ? "text-emerald-500" : ""}`}
      >
        {value}
      </p>
    </div>
  );
}
