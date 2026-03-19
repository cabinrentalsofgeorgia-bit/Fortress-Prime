"use client";

import { useMemo, useState } from "react";
import { Building2 } from "lucide-react";
import {
  useVrsArrivingToday,
  useVrsDashboardStats,
  useVrsDepartingToday,
  useVrsGuests,
  useModuleMaturity,
  useVrsMessageStats,
  useVrsProperties,
  useVrsReservations,
  useSystemTelemetry,
  useSetDefcon,
} from "@/lib/hooks";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { VrsKpiStrip } from "./vrs-kpi-strip";
import { VrsQuickLinksGrid } from "./vrs-quick-links-grid";
import { VrsArrivalsPanel } from "./vrs-arrivals-panel";
import { VrsDeparturesPanel } from "./vrs-departures-panel";
import { VrsMessagingStatsPanel } from "./vrs-messaging-stats-panel";
import { VrsReservationDetailSheet } from "./vrs-reservation-detail-sheet";
import { VrsDashboardPlusPanels } from "./vrs-dashboard-plus-panels";
import { VrsLegacyGlassGrid } from "./vrs-legacy-glass-grid";
import { StreamlineSyncButton } from "../../system-health/_components/streamline-sync-button";

type DefconMode = "SWARM" | "FORTRESS_LEGAL";

export function VrsHubShell() {
  const [selectedReservationId, setSelectedReservationId] = useState<string | null>(null);
  const [defconTarget, setDefconTarget] = useState<DefconMode | null>(null);
  const [confirmInput, setConfirmInput] = useState("");

  const { data: telemetry } = useSystemTelemetry();
  const { data: moduleMaturity } = useModuleMaturity();
  const defconMutation = useSetDefcon();
  const { isLoading: propertiesLoading } = useVrsProperties();
  const { isLoading: reservationsLoading } = useVrsReservations();
  const { data: arrivals, isLoading: arrivalsLoading } = useVrsArrivingToday();
  const { data: departures, isLoading: departuresLoading } = useVrsDepartingToday();
  const { isLoading: guestsLoading } = useVrsGuests();
  const { data: messageStats, isLoading: messageStatsLoading } = useVrsMessageStats();
  const { data: dashboardStats, isLoading: dashboardStatsLoading } = useVrsDashboardStats();

  const loading =
    propertiesLoading ||
    reservationsLoading ||
    arrivalsLoading ||
    departuresLoading ||
    guestsLoading ||
    messageStatsLoading ||
    dashboardStatsLoading;

  const lastUpdated = new Date().toLocaleTimeString();

  const requiredLaunchPhrase = defconTarget ? `ENGAGE ${defconTarget}` : "";
  const isLaunchAuthorized = confirmInput.trim() === requiredLaunchPhrase;
  const moduleHealth = useMemo(() => {
    const map: Record<string, { status?: "up" | "down"; http_status?: number | null; latency_ms?: number | null }> = {};
    for (const moduleEntry of moduleMaturity?.modules ?? []) {
      map[moduleEntry.legacy_path] = moduleEntry.legacy;
    }
    return map;
  }, [moduleMaturity?.modules]);
  const moduleMaturityByPath = useMemo(() => {
    const map: Record<
      string,
      {
        native_route_ready: boolean;
        native_data_live: boolean;
        maturity_reason?: string | null;
      }
    > = {};
    for (const moduleEntry of moduleMaturity?.modules ?? []) {
      map[moduleEntry.legacy_path] = {
        native_route_ready: moduleEntry.native?.status === "up",
        native_data_live: moduleEntry.maturity === "data_live",
        maturity_reason: moduleEntry.maturity_reason,
      };
    }
    return map;
  }, [moduleMaturity?.modules]);
  const legacyModulesUp = moduleMaturity?.summary.legacy_routes_up ?? 0;
  const legacyModulesTotal = moduleMaturity?.summary.total_modules ?? 0;
  const nativeCoverageReady = moduleMaturity?.summary.native_routes_ready ?? 0;
  const nativeCoverageTotal = moduleMaturity?.summary.total_modules ?? 0;
  const nativeDataLiveCoverage = moduleMaturity?.summary.native_data_live ?? 0;
  const maturityReasonSummary = useMemo(() => {
    const counts = new Map<string, number>();
    for (const moduleEntry of moduleMaturity?.modules ?? []) {
      if (moduleEntry.maturity === "data_live" || !moduleEntry.maturity_reason) continue;
      const key = moduleEntry.maturity_reason;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => ({ reason, count }));
  }, [moduleMaturity?.modules]);

  const blockerReasonClass = (reason: string) => {
    if (reason === "auth_required") {
      return "border-amber-500/40 bg-amber-500/10 text-amber-400";
    }
    if (reason === "upstream_5xx") {
      return "border-red-500/40 bg-red-500/10 text-red-400";
    }
    if (reason === "timeout" || reason === "network_failure") {
      return "border-orange-500/40 bg-orange-500/10 text-orange-400";
    }
    if (reason === "client_error" || reason === "not_found") {
      return "border-slate-500/40 bg-slate-500/10 text-slate-300";
    }
    return "border-muted bg-muted/20 text-muted-foreground";
  };

  const closeDefconModal = () => {
    setDefconTarget(null);
    setConfirmInput("");
  };

  const authorizeDefconSwitch = () => {
    if (!defconTarget || !isLaunchAuthorized) {
      return;
    }

    defconMutation.mutate({
      mode: defconTarget.toLowerCase(),
      override_authorization: true,
    });
    closeDefconModal();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Building2 className="h-6 w-6 text-primary" />
            CROG-VRS
          </h1>
          <p className="text-muted-foreground">Vacation Rental Software hub for Cabin Rentals of Georgia.</p>
        </div>
        <div className="flex items-center gap-3">
          <StreamlineSyncButton />
          <span className="text-xs text-muted-foreground">
            {loading ? "Refreshing..." : `Updated ${lastUpdated}`}
          </span>
        </div>
      </div>

      <VrsKpiStrip
        propertiesCount={dashboardStats?.total_properties ?? 0}
        reservationsCount={dashboardStats?.total_reservations ?? 0}
        arrivalsCount={dashboardStats?.arriving_today ?? 0}
        departuresCount={dashboardStats?.departing_today ?? 0}
        guestsCount={dashboardStats?.total_guests ?? 0}
        messagesCount={dashboardStats?.total_messages ?? 0}
        automationRate={messageStats?.automation_rate}
      />

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Quick Access</h2>
        <VrsQuickLinksGrid />
      </section>

      {/* ── Fortress Intelligence Telemetry ── */}
      {telemetry && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold">Fortress Intelligence</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border bg-card p-4 space-y-2">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">DEFCON Mode</p>
              <div className="flex items-center gap-2">
                {(["SWARM", "FORTRESS_LEGAL"] as const).map((mode) => {
                  const active = telemetry.defcon_mode === mode;
                  const color = mode === "SWARM" ? "emerald" : "orange";
                  return (
                    <button
                      key={mode}
                      disabled={defconMutation.isPending || active}
                      onClick={() => {
                        setDefconTarget(mode);
                        setConfirmInput("");
                      }}
                      className={`px-2.5 py-1 rounded text-xs font-bold uppercase tracking-wider transition-all ${
                        active
                          ? `bg-${color}-500/20 text-${color}-500 border border-${color}-500/50 cursor-default`
                          : `border border-muted text-muted-foreground hover:text-foreground hover:border-foreground/30 ${defconMutation.isPending ? "opacity-50 cursor-wait" : ""}`
                      }`}
                    >
                      {defconMutation.isPending && !active ? "..." : mode === "FORTRESS_LEGAL" ? "LEGAL" : mode}
                    </button>
                  );
                })}
              </div>
              {defconMutation.isPending && (
                <p className="text-[10px] text-yellow-500 animate-pulse">Switching infrastructure...</p>
              )}
            </div>
            <div className="rounded-lg border bg-card p-4 space-y-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Vault Gamma Vectors</p>
              <p className="text-lg font-bold">{telemetry.vault_gamma.total_vectors.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border bg-card p-4 space-y-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Omega Training Rows</p>
              <p className="text-lg font-bold">{telemetry.vault_omega.training_rows.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border bg-card p-4 space-y-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Ingestion Queue</p>
              <p className={`text-lg font-bold ${telemetry.ingestion.queue_depth > 0 ? "text-yellow-500" : "text-emerald-500"}`}>
                {telemetry.ingestion.queue_depth > 0 ? `${telemetry.ingestion.queue_depth.toLocaleString()} pending` : "Drained"}
              </p>
              <p className="text-[10px] text-muted-foreground">{telemetry.ingestion.processed.toLocaleString()} processed / {telemetry.ingestion.errors.toLocaleString()} errors</p>
            </div>
            <div className="rounded-lg border bg-card p-4 space-y-1 sm:col-span-2 lg:col-span-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Streamline Bridge Failure Telemetry</p>
              <p className="text-sm font-semibold">
                Latest Class: {telemetry.streamline_bridge?.latest_event?.failure_class ?? "none"}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {telemetry.streamline_bridge?.retries_last_24h ?? 0} retries / {telemetry.streamline_bridge?.failures_last_24h ?? 0} failures (24h)
              </p>
              <p className="text-[10px] text-muted-foreground">
                Legacy modules: {legacyModulesUp}/{legacyModulesTotal || 0} route probes healthy
              </p>
              <p className="text-[10px] text-muted-foreground">
                Native coverage: {nativeCoverageReady}/{nativeCoverageTotal} adapter modules have native routes
              </p>
              <p className="text-[10px] text-muted-foreground">
                Native data-live: {nativeDataLiveCoverage}/{nativeCoverageReady || 0} native modules are bound to live API data
              </p>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">Maturity blockers:</p>
                <div className="flex flex-wrap gap-1.5">
                  {maturityReasonSummary.length === 0 ? (
                    <span className="inline-flex items-center rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                      none
                    </span>
                  ) : (
                    maturityReasonSummary.map(({ reason, count }) => (
                      <span
                        key={reason}
                        className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${blockerReasonClass(reason)}`}
                      >
                        {count} {reason.replace(/_/g, " ")}
                      </span>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
          {Object.keys(telemetry.vault_gamma.partitions).filter(k => k !== "unpartitioned").length > 0 && (
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Case Partitions</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(telemetry.vault_gamma.partitions)
                  .filter(([k]) => k !== "unpartitioned")
                  .sort(([, a], [, b]) => b - a)
                  .map(([name, count]) => (
                    <span key={name} className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium">
                      <span className={`h-1.5 w-1.5 rounded-full ${name.includes("behavioral") ? "bg-orange-500" : "bg-emerald-500"}`} />
                      {name} <span className="text-muted-foreground">({count.toLocaleString()})</span>
                    </span>
                  ))}
              </div>
            </div>
          )}
          {telemetry.threat_reports > 0 && (
            <p className="text-[10px] text-muted-foreground">{telemetry.threat_reports} threat report(s) on file</p>
          )}
        </section>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <VrsArrivalsPanel
            reservations={arrivals}
            onOpenReservation={(id) => setSelectedReservationId(id)}
          />
          <VrsDeparturesPanel
            reservations={departures}
            onOpenReservation={(id) => setSelectedReservationId(id)}
          />
        </div>
        <VrsMessagingStatsPanel stats={messageStats} />
      </div>

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Operations Plus</h2>
        <VrsDashboardPlusPanels />
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Gate C - Legacy Glass Adapter</h2>
        <p className="text-xs text-muted-foreground">
          Strangler adapter links into the existing Command Center `/vrs/*` static modules while Next.js surfaces stay active.
        </p>
        <VrsLegacyGlassGrid moduleHealth={moduleHealth} moduleMaturityByPath={moduleMaturityByPath} />
      </section>

      <VrsReservationDetailSheet
        open={!!selectedReservationId}
        reservationId={selectedReservationId}
        onOpenChange={(open) => !open && setSelectedReservationId(null)}
      />

      <DefconConfirmModal
        mode={defconTarget}
        confirmInput={confirmInput}
        onConfirmInputChange={setConfirmInput}
        requiredLaunchPhrase={requiredLaunchPhrase}
        isAuthorized={isLaunchAuthorized}
        isPending={defconMutation.isPending}
        onCancel={closeDefconModal}
        onAuthorize={authorizeDefconSwitch}
      />
    </div>
  );
}

interface DefconConfirmModalProps {
  mode: DefconMode | null;
  confirmInput: string;
  onConfirmInputChange: (value: string) => void;
  requiredLaunchPhrase: string;
  isAuthorized: boolean;
  isPending: boolean;
  onCancel: () => void;
  onAuthorize: () => void;
}

function DefconConfirmModal({
  mode,
  confirmInput,
  onConfirmInputChange,
  requiredLaunchPhrase,
  isAuthorized,
  isPending,
  onCancel,
  onAuthorize,
}: DefconConfirmModalProps) {
  return (
    <AlertDialog
      open={Boolean(mode)}
      onOpenChange={(open) => {
        if (!open) {
          onCancel();
        }
      }}
    >
      <AlertDialogContent className="border-red-500/60">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-red-500">ARTICLE II AUTHORIZATION REQUIRED</AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            <span className="block text-red-400 font-medium">
              WARNING: Rerouting the Swarm to {mode ?? "this mode"} will cause 5-15 seconds of inference downtime.
              Active Twilio SMS and VRS pipelines will hang. This is a destructive infrastructure operation.
            </span>
            <span className="block text-muted-foreground">
              Type <strong>{requiredLaunchPhrase || "ENGAGE [MODE]"}</strong> to unlock execution.
            </span>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <Input
          value={confirmInput}
          onChange={(event) => onConfirmInputChange(event.target.value)}
          placeholder={requiredLaunchPhrase || "ENGAGE [MODE]"}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="characters"
          spellCheck={false}
        />

        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <Button
            type="button"
            variant="destructive"
            disabled={!isAuthorized || isPending}
            onClick={onAuthorize}
          >
            {isPending ? "Authorizing..." : "Authorize Subprocess"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
