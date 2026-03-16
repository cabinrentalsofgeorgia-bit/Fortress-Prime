"use client";

import { useState } from "react";
import { useRoiSimulator, useAuthorizeUpgrade } from "@/lib/hooks";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Pickaxe,
  TrendingUp,
  TrendingDown,
  Zap,
  Clock,
  Flame,
  Waves,
  Gamepad2,
  MonitorPlay,
  Thermometer,
  Loader2,
} from "lucide-react";

const ICON_MAP: Record<string, React.ReactNode> = {
  flame: <Flame className="h-5 w-5" />,
  waves: <Waves className="h-5 w-5" />,
  "gamepad-2": <Gamepad2 className="h-5 w-5" />,
  "monitor-play": <MonitorPlay className="h-5 w-5" />,
  zap: <Zap className="h-5 w-5" />,
  thermometer: <Thermometer className="h-5 w-5" />,
};

interface Opportunity {
  id: string;
  project_name: string;
  category: string;
  icon: string;
  description: string;
  estimated_cost: number;
  projected_adr_lift: number;
  added_annual_revenue: number;
  payback_period_months: number;
  five_year_roi_pct: number;
}

interface SimulatorData {
  property_id: string;
  current_adr: number;
  current_occupancy_pct: number;
  annual_occupancy_days: number;
  annual_revenue: number;
  market_adr: number;
  adr_vs_market_pct: number;
  bedrooms: number;
  opportunities: Opportunity[];
}

export function RoiSimulator({ propertyId }: { propertyId: string }) {
  const { data, isLoading } = useRoiSimulator(propertyId);
  const authorizeUpgrade = useAuthorizeUpgrade(propertyId);
  const [selectedUpgrade, setSelectedUpgrade] = useState<Opportunity | null>(
    null,
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-500">
        <Loader2 className="h-5 w-5 mr-2 animate-spin" />
        Analyzing market intelligence...
      </div>
    );
  }

  const sim = data as SimulatorData | undefined;
  if (!sim) return null;

  const handleAuthorize = () => {
    if (!selectedUpgrade) return;
    authorizeUpgrade.mutate(
      {
        project_name: selectedUpgrade.project_name,
        estimated_cost: selectedUpgrade.estimated_cost,
        projected_adr_lift: selectedUpgrade.projected_adr_lift,
      },
      { onSuccess: () => setSelectedUpgrade(null) },
    );
  };

  const aboveMarket = sim.adr_vs_market_pct >= 0;

  return (
    <div className="space-y-6">
      {/* Performance baseline */}
      <div className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Current ADR</p>
            <p className="text-2xl font-bold font-mono">
              ${sim.current_adr.toFixed(0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Occupancy</p>
            <p className="text-2xl font-bold font-mono">
              {sim.current_occupancy_pct}%
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Annual Revenue</p>
            <p className="text-2xl font-bold font-mono">
              ${sim.annual_revenue.toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">vs Blue Ridge Market</p>
            <p
              className={`text-2xl font-bold font-mono flex items-center ${aboveMarket ? "text-emerald-500" : "text-red-400"}`}
            >
              {aboveMarket ? (
                <TrendingUp className="h-4 w-4 mr-1" />
              ) : (
                <TrendingDown className="h-4 w-4 mr-1" />
              )}
              {aboveMarket ? "+" : ""}
              {sim.adr_vs_market_pct}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Section header */}
      <div className="flex items-center space-x-2">
        <Pickaxe className="h-5 w-5 text-emerald-500" />
        <h3 className="text-lg font-semibold">
          Strategic Upgrade Opportunities
        </h3>
      </div>
      <p className="text-sm text-muted-foreground">
        Our market intelligence engine has identified the following upgrades to
        maximize your asset&apos;s yield based on Blue Ridge demand data.
      </p>

      {sim.opportunities.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            Your property already has all identified high-yield amenities. No
            upgrades recommended at this time.
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sim.opportunities.map((opp) => (
            <Card
              key={opp.id}
              className="hover:border-emerald-500/50 transition-colors"
            >
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2 mb-1 text-emerald-500">
                  {ICON_MAP[opp.icon] ?? <Pickaxe className="h-5 w-5" />}
                  <span className="text-xs uppercase tracking-wider font-medium text-muted-foreground">
                    {opp.category}
                  </span>
                </div>
                <CardTitle className="text-base">{opp.project_name}</CardTitle>
                <CardDescription className="min-h-[48px] text-xs">
                  {opp.description}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="p-3 rounded-lg border bg-muted/30 space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">
                      Estimated Cost
                    </span>
                    <span className="font-mono">
                      ${opp.estimated_cost.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">ADR Lift</span>
                    <span className="font-mono text-emerald-500">
                      +${opp.projected_adr_lift.toFixed(2)}/night
                    </span>
                  </div>
                  <div className="flex justify-between border-t pt-1 mt-1">
                    <span className="font-medium">Added Annual Revenue</span>
                    <span className="font-mono font-bold text-emerald-500">
                      +${opp.added_annual_revenue.toLocaleString()}
                    </span>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-muted-foreground">
                  <span className="flex items-center">
                    <Clock className="h-3 w-3 mr-1" />
                    Payback: {opp.payback_period_months} mo
                  </span>
                  <span className="flex items-center text-emerald-500">
                    <TrendingUp className="h-3 w-3 mr-1" />
                    5yr ROI: {opp.five_year_roi_pct}%
                  </span>
                </div>

                <Button
                  className="w-full"
                  variant="default"
                  onClick={() => setSelectedUpgrade(opp)}
                >
                  <Zap className="h-4 w-4 mr-2" />
                  Initialize Project
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Authorization dialog */}
      <Dialog
        open={!!selectedUpgrade}
        onOpenChange={() => setSelectedUpgrade(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Authorize CapEx Execution</DialogTitle>
            <DialogDescription>
              You are authorizing CROG Development to execute the{" "}
              <span className="font-medium text-foreground">
                {selectedUpgrade?.project_name}
              </span>
              .
            </DialogDescription>
          </DialogHeader>

          {selectedUpgrade && (
            <div className="p-4 rounded-lg border bg-muted/30 font-mono text-sm space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">CapEx Draw:</span>
                <span className="text-red-400">
                  -${selectedUpgrade.estimated_cost.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">ADR Lift:</span>
                <span className="text-emerald-400">
                  +${selectedUpgrade.projected_adr_lift.toFixed(2)}/night
                </span>
              </div>
              <div className="flex justify-between border-t pt-2">
                <span className="text-muted-foreground">Projected Yield:</span>
                <span className="text-emerald-400 font-bold">
                  +${selectedUpgrade.added_annual_revenue.toLocaleString()}/yr
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Payback:</span>
                <span>{selectedUpgrade.payback_period_months} months</span>
              </div>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            By confirming, funds will be staged from your operating balance and
            CROG Development will automatically schedule the upgrade.
          </p>

          <DialogFooter className="sm:justify-between">
            <Button variant="ghost" onClick={() => setSelectedUpgrade(null)}>
              Cancel
            </Button>
            <Button
              onClick={handleAuthorize}
              disabled={authorizeUpgrade.isPending}
            >
              {authorizeUpgrade.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Executing...
                </>
              ) : (
                <>
                  <Zap className="h-4 w-4 mr-2" />
                  Confirm & Dispatch
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
