"use client";

import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Cpu,
  Gavel,
  LifeBuoy,
  Radar,
  Satellite,
  Scale,
  SearchCode,
  Server,
  Shield,
  Timer,
  TrendingUp,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useFunnelHQ,
  useParityDashboard,
  useSovereignPulse,
  useSystemHealth,
} from "@/lib/hooks";
import { MobileC2Panel } from "./_components/mobile-c2-panel";
import { MarketIntelligenceFeed } from "./parity/_components/market-intelligence-feed";
import { RecoveryDraftParity } from "./parity/_components/recovery-draft-parity";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return "--";
  const normalized = value <= 1 ? value * 100 : value;
  return `${normalized.toFixed(1)}%`;
}

function formatUptime(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return "--";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function statusTone(status: string): string {
  switch (status) {
    case "healthy":
    case "active":
    case "enabled":
    case "succeeded":
    case "online":
    case "MATCH":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "degraded":
    case "warning":
    case "queued":
    case "running":
    case "processing":
    case "MINOR_DRIFT":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "failed":
    case "offline":
    case "alert":
    case "error":
    case "CRITICAL_MISMATCH":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    default:
      return "border-zinc-700 bg-zinc-900/80 text-zinc-300";
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function TacticalStat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-zinc-100">{value}</p>
      <p className="mt-1 text-xs text-zinc-400">{detail}</p>
    </div>
  );
}

function OpsStatusRow({
  label,
  value,
  tone,
  detail,
}: {
  label: string;
  value: string;
  tone: string;
  detail: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
      <div>
        <p className="text-sm font-medium text-zinc-100">{label}</p>
        <p className="text-xs text-zinc-500">{detail}</p>
      </div>
      <span
        className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${tone}`}
      >
        {value}
      </span>
    </div>
  );
}

export default function CommandCenterPage() {
  const parity = useParityDashboard();
  const pulse = useSovereignPulse();
  const funnel = useFunnelHQ();
  const health = useSystemHealth();

  const parityData = parity.data;
  const pulseData = pulse.data;
  const funnelData = funnel.data;
  const healthData = health.data;

  const nodes = healthData?.nodes ? Object.values(healthData.nodes) : [];
  const onlineNodes = nodes.filter((node) => node.online);
  const avgGpuTemp =
    onlineNodes.length > 0
      ? Math.round(
          onlineNodes.reduce((sum, node) => sum + (node.gpu?.temp_c ?? 0), 0) / onlineNodes.length,
        )
      : 0;
  const postgresTables = Object.entries(healthData?.databases?.postgres ?? {});
  const qdrantCollections = Object.entries(healthData?.databases?.qdrant ?? {});
  const blockers = [
    !parityData && parity.error ? errorMessage(parity.error, "Parity telemetry unavailable.") : null,
    !pulseData && pulse.error ? errorMessage(pulse.error, "Sovereign Pulse unavailable.") : null,
    !funnelData && funnel.error ? errorMessage(funnel.error, "Funnel HQ unavailable.") : null,
    !healthData && health.error ? errorMessage(health.error, "System Health unavailable.") : null,
  ].filter(Boolean) as string[];

  if (
    !parityData &&
    !pulseData &&
    !funnelData &&
    !healthData &&
    (parity.isLoading || pulse.isLoading || funnel.isLoading || health.isLoading)
  ) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-emerald-200">
            <Radar className="h-3.5 w-3.5" />
            Sovereign Glass
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-emerald-fortress">Fortress Prime</h1>
        </div>
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="pt-6 text-sm text-zinc-400">
            Arming the sovereign dashboard from live VRS, SEO, OPS, and LEGAL telemetry...
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-emerald-200">
          <Radar className="h-3.5 w-3.5" />
          Sovereign Glass
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-emerald-fortress">Fortress Prime</h1>
            <p className="mt-1 max-w-4xl text-sm text-zinc-400">
              The sovereign dashboard fuses VRS recovery, SEO observation, system posture, and legal
              control into one high-fidelity command surface.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild className="bg-cyan-700 text-white hover:bg-cyan-600">
              <Link href="/command/sovereign-pulse">
                VRS Recovery
                <Satellite className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button asChild className="bg-fuchsia-700 text-white hover:bg-fuchsia-600">
              <Link href="/command/parity">
                SEO Fidelity
                <SearchCode className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/system-health">
                System Health
                <Server className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/legal">
                Legal Council
                <Gavel className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </div>

      {blockers.length > 0 ? (
        <Card className="border-amber-500/30 bg-amber-950/10">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-amber-100">
              <AlertTriangle className="h-5 w-5" />
              Degraded Telemetry Inputs
            </CardTitle>
            <CardDescription className="text-amber-200/80">
              The surface is rendering only authoritative feeds that responded. No preview or mock
              data is injected.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-amber-100">
            {blockers.map((blocker) => (
              <p key={blocker}>{blocker}</p>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-4">
        <Card className="border-cyan-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Satellite className="h-5 w-5 text-cyan-300" />
              VRS Recovery
            </CardTitle>
            <CardDescription>Recovery queue, hold pressure, and guest-intent convergence.</CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <div className="text-4xl font-semibold tracking-tight text-zinc-50">
              {funnelData?.recovery.length ?? 0}
            </div>
            <p className="mt-2 text-sm text-zinc-400">
              High-intent recovery candidates. Active holds {pulseData?.handshake.holds_active ?? "--"}.
            </p>
          </CardContent>
        </Card>

        <Card className="border-fuchsia-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <SearchCode className="h-5 w-5 text-fuchsia-300" />
              SEO Fidelity
            </CardTitle>
            <CardDescription>Market intelligence plus OTA and parity audit telemetry.</CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <div className="text-4xl font-semibold tracking-tight text-zinc-50">
              {parityData?.market_intelligence_feed.length ?? 0}
            </div>
            <p className="mt-2 text-sm text-zinc-400">
              Intelligence findings armed. Pending human queue {pulseData?.seo_queue.pending_human ?? "--"}.
            </p>
          </CardContent>
        </Card>

        <Card className="border-emerald-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Shield className="h-5 w-5 text-emerald-300" />
              System Health
            </CardTitle>
            <CardDescription>Cluster health, service posture, and command uptime.</CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <div className="text-4xl font-semibold tracking-tight text-zinc-50">
              {healthData?.status ?? "unknown"}
            </div>
            <p className="mt-2 text-sm text-zinc-400">
              Uptime {formatUptime(healthData?.uptime_seconds)}. Nodes online {onlineNodes.length}/
              {nodes.length}.
            </p>
          </CardContent>
        </Card>

        <Card className="border-amber-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Scale className="h-5 w-5 text-amber-300" />
              Legal Council
            </CardTitle>
            <CardDescription>Council, discovery, and case-control quick access.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pt-6">
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/legal">Open Legal Desk</Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/legal/council">Open Council</Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 2xl:grid-cols-[1.15fr_1.15fr_0.9fr]">
        <div className="space-y-6">
          <Card className="border-cyan-500/20 bg-zinc-950/90">
            <CardHeader className="border-b border-zinc-800/80">
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <LifeBuoy className="h-5 w-5 text-cyan-300" />
                VRS Command Board
              </CardTitle>
              <CardDescription>
                Recovery parity is now anchored inside the VRS recovery lane alongside live conversion-funnel
                mechanics.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 pt-6 md:grid-cols-2">
              <TacticalStat
                label="Recovery Queue"
                value={funnelData?.recovery.length ?? 0}
                detail={`Last funnel refresh ${
                  funnel.dataUpdatedAt ? new Date(funnel.dataUpdatedAt).toLocaleTimeString() : "--"
                }`}
              />
              <TacticalStat
                label="Distinct Sessions"
                value={funnelData?.distinct_sessions_in_window ?? 0}
                detail={`${funnelData?.window_hours ?? "--"}h observation window`}
              />
              <TacticalStat
                label="Direct Holds"
                value={pulseData?.handshake.holds_active ?? 0}
                detail={`${pulseData?.handshake.holds_converted_last_24h ?? 0} converted in the last 24h`}
              />
              <TacticalStat
                label="Recovery Ghosts"
                value={parityData?.recovery_ghosts.total_resurrections ?? 0}
                detail={`${parityData?.recovery_ghosts.soft_landed_losses ?? 0} soft-landed losses`}
              />
            </CardContent>
          </Card>

          {parityData ? (
            <RecoveryDraftParity
              observer={parityData.concierge_observer}
              comparisons={parityData.recovery_comparisons}
            />
          ) : (
            <Card className="border-zinc-800 bg-zinc-950/90">
              <CardContent className="pt-6 text-sm text-zinc-400">
                VRS recovery parity feed is unavailable.
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card className="border-fuchsia-500/20 bg-zinc-950/90">
            <CardHeader className="border-b border-zinc-800/80">
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <SearchCode className="h-5 w-5 text-fuchsia-300" />
                SEO Command Board
              </CardTitle>
              <CardDescription>
                Intelligence feed and OTA fidelity audit now converge in one sovereign SEO lane.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 pt-6 md:grid-cols-2">
              <TacticalStat
                label="Observed Pages"
                value={parityData?.seo_parity.observed_count ?? 0}
                detail={`Status ${parityData?.seo_parity.status ?? "unknown"}`}
              />
              <TacticalStat
                label="Avg Uplift"
                value={parityData ? parityData.seo_parity.avg_uplift_pct_points.toFixed(1) : "--"}
                detail="Legacy versus sovereign score delta"
              />
              <TacticalStat
                label="Pending Human"
                value={pulseData?.seo_queue.pending_human ?? 0}
                detail={`${pulseData?.seo_queue.deployed ?? 0} deployed`}
              />
              <TacticalStat
                label="Quote Match"
                value={parityData ? formatPercent(parityData.quote_parity.accuracy_rate) : "--"}
                detail={`Last drift ${parityData?.quote_observer.last_drift_status ?? "unknown"}`}
              />
            </CardContent>
          </Card>

          {parityData ? (
            <MarketIntelligenceFeed
              items={parityData.market_intelligence_feed}
              observer={parityData.scout_observer}
              alpha={parityData.scout_alpha_conversion}
            />
          ) : (
            <Card className="border-zinc-800 bg-zinc-950/90">
              <CardContent className="pt-6 text-sm text-zinc-400">
                SEO market intelligence feed is unavailable.
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card className="border-emerald-500/20 bg-zinc-950/90">
            <CardHeader className="border-b border-zinc-800/80">
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <Server className="h-5 w-5 text-emerald-300" />
                System Health
              </CardTitle>
              <CardDescription>
                Hardware metrics, observer lanes, and hardening posture now centralize here.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 pt-6">
              <div className="grid gap-3 sm:grid-cols-2">
                <TacticalStat
                  label="Nodes Online"
                  value={`${onlineNodes.length}/${nodes.length}`}
                  detail="DGX Spark cluster"
                />
                <TacticalStat
                  label="Avg GPU Temp"
                  value={avgGpuTemp ? `${avgGpuTemp}°C` : "--"}
                  detail={`Uptime ${formatUptime(healthData?.uptime_seconds)}`}
                />
              </div>
              <OpsStatusRow
                label="Scout Job"
                value={parityData?.scout_observer.last_job_status ?? "unknown"}
                tone={statusTone(parityData?.scout_observer.last_job_status ?? "unknown")}
                detail={`Last success ${formatTimestamp(parityData?.scout_observer.last_success_at)}`}
              />
              <OpsStatusRow
                label="Concierge Shadow"
                value={parityData?.concierge_observer.last_job_status ?? "unknown"}
                tone={statusTone(parityData?.concierge_observer.last_job_status ?? "unknown")}
                detail={`Last success ${formatTimestamp(parityData?.concierge_observer.last_success_at)}`}
              />
              <OpsStatusRow
                label="SEO Observer"
                value={parityData?.seo_observer.last_job_status ?? "unknown"}
                tone={statusTone(parityData?.seo_observer.last_job_status ?? "unknown")}
                detail={`Last audit ${formatTimestamp(parityData?.seo_observer.last_audit_at)}`}
              />
              <OpsStatusRow
                label="Quote Observer"
                value={parityData?.quote_observer.last_job_status ?? "unknown"}
                tone={statusTone(parityData?.quote_observer.last_job_status ?? "unknown")}
                detail={`Last drift ${parityData?.quote_observer.last_drift_status ?? "unknown"}`}
              />
              <OpsStatusRow
                label="Bcrypt Hardening"
                value="enforced"
                tone="border-cyan-500/30 bg-cyan-500/10 text-cyan-200"
                detail="Password hashing contract is backed by the sovereign auth core."
              />
            </CardContent>
          </Card>

          <Card className="border-zinc-800 bg-zinc-950/90">
            <CardHeader className="border-b border-zinc-800/80">
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <Cpu className="h-5 w-5 text-zinc-300" />
                OPS Data Matrix
              </CardTitle>
              <CardDescription>Database and vector posture sourced from System Health.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-6">
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.24em] text-zinc-500">PostgreSQL</p>
                <div className="space-y-2">
                  {postgresTables.length === 0 ? (
                    <p className="text-sm text-zinc-400">Postgres telemetry unavailable.</p>
                  ) : (
                    postgresTables.slice(0, 4).map(([table, rows]) => (
                      <div key={table} className="flex items-center justify-between text-sm">
                        <span className="text-zinc-300">{table}</span>
                        <span className="text-zinc-500">{rows.toLocaleString()} rows</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.24em] text-zinc-500">Vector DB</p>
                <div className="space-y-2">
                  {qdrantCollections.length === 0 ? (
                    <p className="text-sm text-zinc-400">Qdrant telemetry unavailable.</p>
                  ) : (
                    qdrantCollections.slice(0, 4).map(([collection, info]) => (
                      <div key={collection} className="flex items-center justify-between text-sm">
                        <span className="text-zinc-300">{collection}</span>
                        <span className="text-zinc-500">
                          {info.points.toLocaleString()} pts · {info.status}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

            <MobileC2Panel compact />

          <Card className="border-amber-500/20 bg-zinc-950/90">
            <CardHeader className="border-b border-zinc-800/80">
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <Gavel className="h-5 w-5 text-amber-300" />
                Legal Council
              </CardTitle>
              <CardDescription>Jump directly into council, cases, and discovery lanes.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 pt-6">
              <Button asChild className="w-full bg-amber-600 text-white hover:bg-amber-500">
                <Link href="/legal">
                  Legal Desk
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button
                asChild
                variant="outline"
                className="w-full border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              >
                <Link href="/legal/council">
                  Legal Council
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button
                asChild
                variant="outline"
                className="w-full border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              >
                <Link href="/vault">
                  Discovery Vault
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <TrendingUp className="h-5 w-5 text-cyan-300" />
              Funnel Intent
            </CardTitle>
            <CardDescription>Live VRS leakage signals from Funnel HQ.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {funnelData?.edges.length ? (
              funnelData.edges.slice(0, 4).map((edge) => (
                <div
                  key={`${edge.from_stage}-${edge.to_stage}`}
                  className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm text-zinc-100">
                      {edge.from_label} to {edge.to_label}
                    </p>
                    <span className="text-xs text-zinc-500">
                      {edge.retention_pct == null ? "--" : `${edge.retention_pct.toFixed(1)}%`}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-zinc-400">Funnel edge telemetry unavailable.</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Timer className="h-5 w-5 text-fuchsia-300" />
              SEO Audit Clock
            </CardTitle>
            <CardDescription>Latest observation timestamps across the SEO lane.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6 text-sm">
            <div className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <span className="text-zinc-300">Last SEO observation</span>
              <span className="text-zinc-500">{formatTimestamp(parityData?.seo_parity.last_observed_at)}</span>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <span className="text-zinc-300">Last quote audit</span>
              <span className="text-zinc-500">{formatTimestamp(parityData?.quote_observer.last_audit_at)}</span>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <span className="text-zinc-300">Last scout discovery</span>
              <span className="text-zinc-500">{formatTimestamp(parityData?.scout_observer.last_discovery_at)}</span>
            </div>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Activity className="h-5 w-5 text-emerald-300" />
              Service Pulse
            </CardTitle>
            <CardDescription>OPS service lane summarized from bare-metal health telemetry.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {healthData?.services?.length ? (
              healthData.services.slice(0, 5).map((service) => (
                <div
                  key={service.name}
                  className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3"
                >
                  <p className="text-sm text-zinc-100">{service.name}</p>
                  <span
                    className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(service.status)}`}
                  >
                    {service.status}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-sm text-zinc-400">Service telemetry unavailable.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
