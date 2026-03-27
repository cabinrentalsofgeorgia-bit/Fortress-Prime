"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  TrendingDown,
} from "lucide-react";

import {
  approveYieldRecommendations,
  runYieldSwarmAnalysis,
  type ApproveYieldActionResult,
  type YieldAnalysisActionResult,
} from "@/app/actions/yield";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProperties } from "@/lib/hooks";

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

export function YieldShell() {
  const properties = useProperties();
  const activeProperties = useMemo(
    () => (properties.data ?? []).filter((property) => property.is_active),
    [properties.data],
  );
  const [selectedPropertyId, setSelectedPropertyId] = useState<string>("");
  const [analysisResult, setAnalysisResult] = useState<YieldAnalysisActionResult | null>(null);
  const [approvalResult, setApprovalResult] = useState<ApproveYieldActionResult | null>(null);
  const [isAnalyzing, startAnalyze] = useTransition();
  const [isApproving, startApprove] = useTransition();

  useEffect(() => {
    if (!selectedPropertyId && activeProperties.length > 0) {
      setSelectedPropertyId(activeProperties[0].id);
    }
  }, [activeProperties, selectedPropertyId]);

  const selectedProperty = activeProperties.find((property) => property.id === selectedPropertyId) ?? null;
  const canApprove =
    analysisResult?.ok === true && analysisResult.analysis.pricing_recommendations.length > 0;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">Yield Management</h1>
        <p className="text-sm text-muted-foreground">
          Human-in-the-loop yield control. Run the swarm, inspect the recommendation,
          and commit a sovereign rate override only after explicit approval.
        </p>
      </div>

      <Card className="border-primary/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            Yield Swarm Analysis
          </CardTitle>
          <CardDescription>
            Select an active property and query the Financial Swarm through the internal DGX lane.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Property
              </div>
              <Select value={selectedPropertyId} onValueChange={setSelectedPropertyId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a property" />
                </SelectTrigger>
                <SelectContent>
                  {activeProperties.map((property) => (
                    <SelectItem key={property.id} value={property.id}>
                      {property.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                className="w-full md:w-auto"
                disabled={!selectedPropertyId || isAnalyzing || properties.isLoading}
                onClick={() => {
                  if (!selectedPropertyId) return;
                  setApprovalResult(null);
                  startAnalyze(async () => {
                    const result = await runYieldSwarmAnalysis({ propertyId: selectedPropertyId });
                    setAnalysisResult(result);
                  });
                }}
              >
                {isAnalyzing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Run Swarm Analysis
              </Button>
            </div>
          </div>

          {properties.isLoading ? (
            <div className="rounded-lg border border-border/50 bg-muted/30 p-4 text-sm text-muted-foreground">
              Loading active property ledger...
            </div>
          ) : null}

          {analysisResult && !analysisResult.ok ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
              {analysisResult.error}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {analysisResult?.ok ? (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Selected Property
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-lg font-semibold">{selectedProperty?.name ?? "Unknown"}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Velocity Score
                </CardTitle>
              </CardHeader>
              <CardContent className="flex items-center gap-2">
                <TrendingDown className="h-4 w-4 text-amber-500" />
                <span className="text-lg font-semibold">
                  {analysisResult.analysis.velocity_score.toFixed(1)}
                </span>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Friction Warning
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Badge
                  variant={analysisResult.analysis.friction_warning ? "destructive" : "secondary"}
                  className="gap-1"
                >
                  {analysisResult.analysis.friction_warning ? (
                    <AlertTriangle className="h-3 w-3" />
                  ) : (
                    <CheckCircle2 className="h-3 w-3" />
                  )}
                  {analysisResult.analysis.friction_warning ? "High Friction" : "Stable"}
                </Badge>
              </CardContent>
            </Card>
          </div>

          <Card className="border-emerald-500/20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-emerald-500" />
                Approval Queue
              </CardTitle>
              <CardDescription>
                Review the swarm recommendation before committing any ledger override.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {analysisResult.analysis.pricing_recommendations.length === 0 ? (
                <div className="rounded-lg border border-border/50 bg-muted/30 p-4 text-sm text-muted-foreground">
                  No rate override is recommended for the current analysis window.
                </div>
              ) : (
                <div className="space-y-3">
                  {analysisResult.analysis.pricing_recommendations.map((recommendation) => (
                    <div
                      key={`${recommendation.start_date}-${recommendation.end_date}-${recommendation.adjustment_percent}`}
                      className="rounded-lg border border-border/50 p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant={
                            recommendation.adjustment_percent < 0 ? "secondary" : "outline"
                          }
                        >
                          {recommendation.adjustment_percent < 0
                            ? "Yield Discount"
                            : "Yield Premium"}
                        </Badge>
                        <span className="font-semibold">
                          {formatPercent(recommendation.adjustment_percent)}
                        </span>
                        <span className="text-sm text-muted-foreground">
                          {recommendation.start_date} to {recommendation.end_date}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {recommendation.rationale}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3">
                <Button
                  className="bg-emerald-600 hover:bg-emerald-700"
                  disabled={!canApprove || isApproving}
                  onClick={() => {
                    if (!analysisResult.ok) return;
                    startApprove(async () => {
                      const result = await approveYieldRecommendations({
                        propertyId: selectedPropertyId,
                        recommendations: analysisResult.analysis.pricing_recommendations,
                      });
                      setApprovalResult(result);
                    });
                  }}
                >
                  {isApproving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Approve &amp; Apply
                </Button>
                <span className="text-xs text-muted-foreground">
                  Approval writes directly to the sovereign `pricing_overrides` ledger.
                </span>
              </div>

              {approvalResult && !approvalResult.ok ? (
                <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
                  {approvalResult.error}
                </div>
              ) : null}

              {approvalResult?.ok ? (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-600">
                  Applied {approvalResult.overrides.length} pricing override
                  {approvalResult.overrides.length === 1 ? "" : "s"} for{" "}
                  {selectedProperty?.name ?? "the selected property"}.
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
