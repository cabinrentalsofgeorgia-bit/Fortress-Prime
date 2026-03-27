"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Check,
  Copy,
  CreditCard,
  Cpu,
  Flame,
  Gavel,
  RefreshCw,
  Server,
  ShieldCheck,
  ThermometerSun,
  Wand2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useFunnelHQ, useSovereignPulse, useSystemHealth } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { MobileC2Panel } from "../_components/mobile-c2-panel";

type NormalizedRecoveryRow = {
  sessionFp: string;
  sessionFpSuffix: string;
  guestDisplayName: string | null;
  guestEmail: string | null;
  guestPhone: string | null;
  dropOffPoint: string;
  dropOffPointLabel: string;
  frictionLabel: string;
  lastEventType: string;
  intentScoreEstimate: string;
  propertySlug: string | null;
  linkedGuestId: string | null;
  lastSeenAt: string;
};

type NormalizedEnticementForge = {
  smsEnabled: boolean;
  cooldownHours: string;
  bookUrl: string;
  templateRaw: string;
  sampleRenderedBody: string;
  twilioConfigured: boolean;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function optionalString(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || null;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

function displayString(value: unknown, fallback = "—"): string {
  return optionalString(value) ?? fallback;
}

function optionalNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return null;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatScore(value: unknown): string {
  const numeric = optionalNumber(value);
  return numeric == null ? "—" : numeric.toFixed(2);
}

function formatDateTime(value: unknown): string {
  const raw = optionalString(value);
  if (!raw) {
    return "—";
  }
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
}

function normalizeRecoveryRows(value: unknown): NormalizedRecoveryRow[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((entry, index) => {
    const row = asRecord(entry) ?? {};
    const sessionFp = displayString(row.session_fp, `session-${index + 1}`);
    return {
      sessionFp,
      sessionFpSuffix: displayString(row.session_fp_suffix, sessionFp.slice(-8) || sessionFp),
      guestDisplayName: optionalString(row.guest_display_name),
      guestEmail: optionalString(row.guest_email),
      guestPhone: optionalString(row.guest_phone),
      dropOffPoint: displayString(row.drop_off_point),
      dropOffPointLabel: displayString(row.drop_off_point_label),
      frictionLabel: displayString(row.friction_label),
      lastEventType: displayString(row.last_event_type),
      intentScoreEstimate: formatScore(row.intent_score_estimate),
      propertySlug: optionalString(row.property_slug),
      linkedGuestId: optionalString(row.linked_guest_id),
      lastSeenAt: formatDateTime(row.last_seen_at),
    };
  });
}

function normalizeEnticementForge(value: unknown): NormalizedEnticementForge | null {
  const forge = asRecord(value);
  if (!forge) {
    return null;
  }
  return {
    smsEnabled: Boolean(forge.sms_enabled),
    cooldownHours: displayString(forge.cooldown_hours),
    bookUrl: displayString(forge.book_url, "Not configured"),
    templateRaw: displayString(forge.template_raw, "Template unavailable."),
    sampleRenderedBody: displayString(forge.sample_rendered_body, "Forge preview unavailable."),
    twilioConfigured: Boolean(forge.twilio_configured),
  };
}

function CopySessionFp({ fingerprint }: { fingerprint: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(fingerprint);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard failures in locked browsers.
    }
  }, [fingerprint]);
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-7 gap-1 px-2 text-xs text-zinc-400 hover:text-zinc-100"
      onClick={() => void onCopy()}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "Copied" : "Copy FP"}
    </Button>
  );
}

function Kpi({
  label,
  value,
  hint,
  variant = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  variant?: "default" | "success" | "warning" | "danger";
}) {
  const border =
    variant === "success"
      ? "border-emerald-500/30"
      : variant === "warning"
        ? "border-amber-500/30"
        : variant === "danger"
          ? "border-rose-500/40"
          : "border-zinc-800";
  return (
    <div className={cn("rounded-xl border bg-zinc-900/70 px-4 py-3", border)}>
      <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-50">{value}</p>
      {hint ? <p className="mt-1 text-xs text-zinc-500">{hint}</p> : null}
    </div>
  );
}

export default function SovereignPulsePage() {
  const searchParams = useSearchParams();
  const minStaleMinutes = searchParams.get("min_stale_minutes");
  const pulse = useSovereignPulse();
  const funnel = useFunnelHQ({
    min_stale_minutes: minStaleMinutes ?? undefined,
  });
  const health = useSystemHealth();
  const [forgeOpen, setForgeOpen] = useState(false);

  if (!pulse.data && !funnel.data && !health.data && (pulse.isLoading || funnel.isLoading || health.isLoading)) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-cyan-200">
            <Activity className="h-3.5 w-3.5" />
            Sovereign Pulse
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">God&apos;s Eye</h1>
        </div>
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="pt-6 text-sm text-zinc-400">
            Arming live pulse, funnel, and health telemetry...
          </CardContent>
        </Card>
      </div>
    );
  }

  const pulseData = pulse.data;
  const funnelData = funnel.data;
  const healthData = health.data;

  if (!pulseData || !funnelData || !healthData) {
    const blockers = [
      !pulseData ? (pulse.error instanceof Error ? pulse.error.message : "Sovereign Pulse unavailable.") : null,
      !funnelData ? (funnel.error instanceof Error ? funnel.error.message : "Funnel HQ unavailable.") : null,
      !healthData ? (health.error instanceof Error ? health.error.message : "System Health unavailable.") : null,
    ].filter(Boolean) as string[];

    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-amber-200">
            <AlertTriangle className="h-3.5 w-3.5" />
            Sovereign Pulse
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">God&apos;s Eye</h1>
          <p className="max-w-3xl text-sm text-zinc-400">
            Live telemetry is required on this route. Preview fallback has been removed.
          </p>
        </div>
        <Card className="border-amber-500/30 bg-amber-950/10">
          <CardContent className="space-y-2 pt-6 text-sm text-amber-100">
            {blockers.map((blocker) => (
              <p key={blocker}>{blocker}</p>
            ))}
          </CardContent>
        </Card>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900">
            <Link href="/">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Sovereign Dashboard
            </Link>
          </Button>
          <Button
            variant="outline"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            onClick={() => {
              void pulse.refetch();
              void funnel.refetch();
              void health.refetch();
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry telemetry
          </Button>
        </div>
      </div>
    );
  }

  const recoveryRows = normalizeRecoveryRows(funnelData.recovery);
  const enticementForge = normalizeEnticementForge(funnelData.enticement_forge);

  const gpus = healthData.gpus ?? [];
  const headOnline = healthData.postgres_ok ? 1 : 0;
  const avgTemp =
    gpus.length > 0 ? Math.round(gpus.reduce((sum, g) => sum + g.temperature_c, 0) / gpus.length) : 0;
  const vramTotal = gpus.reduce((sum, g) => sum + g.memory_total_mb, 0);
  const vramUsed = gpus.reduce((sum, g) => sum + g.memory_used_mb, 0);
  const vramPct = vramTotal > 0 ? (vramUsed / vramTotal) * 100 : 0;

  const lastPulse = pulse.dataUpdatedAt ? new Date(pulse.dataUpdatedAt).toLocaleTimeString() : "Preview";
  const lastHealth = health.dataUpdatedAt ? new Date(health.dataUpdatedAt).toLocaleTimeString() : "Preview";
  const lastFunnel = funnel.dataUpdatedAt ? new Date(funnel.dataUpdatedAt).toLocaleTimeString() : "Preview";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <Button asChild variant="ghost" size="sm" className="w-fit gap-2 text-zinc-400 hover:text-zinc-100">
            <Link href="/">
              <ArrowLeft className="h-4 w-4" />
              Command Center
            </Link>
          </Button>
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-cyan-200">
            <Activity className="h-3.5 w-3.5" />
            Sovereign Pulse
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">God&apos;s Eye</h1>
          <p className="max-w-3xl text-sm text-zinc-400">
            DGX Swarm throughput, SEO Tribunal (God Head) queue, and Stripe ↔ reservation handshake convergence
            — internal Command Center only (<span className="text-zinc-300">crog-ai.com</span>).
          </p>
          <p className="text-xs text-zinc-500">
            Ledger refresh: {lastPulse} · Funnel HQ: {lastFunnel} · Cluster telemetry: {lastHealth}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm" className="border-zinc-700 bg-zinc-900 text-zinc-200">
            <Link href="/system-health">
              <Server className="mr-2 h-4 w-4" />
              Full System Health
            </Link>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-900 text-zinc-200"
            onClick={() => {
              void pulse.refetch();
              void funnel.refetch();
              void health.refetch();
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh now
          </Button>
        </div>
      </div>

      <Card className="border-zinc-800 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80 pb-4">
          <CardTitle className="flex items-center gap-2 text-lg text-zinc-50">
            <Cpu className="h-5 w-5 text-sky-400" />
            DGX Spark — live strip
          </CardTitle>
          <CardDescription>
            Same source as System Health; polls every ~30s with the pulse ledger (~20s).
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              label="Head node"
              value={`${headOnline}/1`}
              variant={headOnline === 1 ? "success" : "warning"}
            />
            <Kpi
              label="Avg GPU temp"
              value={`${avgTemp}°C`}
              hint="Across NVML GPUs"
              variant={avgTemp >= 80 ? "danger" : avgTemp >= 65 ? "warning" : "success"}
            />
            <Kpi
              label="VRAM"
              value={`${(vramUsed / 1024).toFixed(0)} / ${(vramTotal / 1024).toFixed(0)} GB`}
              hint={`${vramPct.toFixed(1)}% allocated`}
              variant={vramPct >= 90 ? "danger" : vramPct >= 75 ? "warning" : "default"}
            />
            <Kpi
              label="Service posture"
              value={healthData.status}
              variant={
                healthData.status === "NOMINAL"
                  ? "success"
                  : healthData.status === "WARNING"
                    ? "warning"
                    : "danger"
              }
            />
          </div>
        </CardContent>
      </Card>

      <MobileC2Panel />

      <div className="grid gap-4 xl:grid-cols-1">
        <Card className="border-orange-500/25 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Flame className="h-5 w-5 text-orange-400" />
              Funnel heatmap &amp; leakage
            </CardTitle>
            <CardDescription>
              Rolling {funnelData.window_hours}h window · {funnelData.distinct_sessions_in_window} distinct
              sessions with intent events. Retention = share of prior-stage sessions that also reached the
              next stage.
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto pt-4">
            {!funnelData.ledger_ready ? (
              <p className="text-sm text-amber-300">
                Intent ledger not ready — run <code className="text-xs">alembic upgrade head</code>.
              </p>
            ) : funnelData.edges.length === 0 ? (
              <p className="text-sm text-zinc-500">No funnel edges yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="border-zinc-800 hover:bg-transparent">
                    <TableHead className="text-zinc-400">From → To</TableHead>
                    <TableHead className="text-right text-zinc-400">At &quot;From&quot;</TableHead>
                    <TableHead className="text-right text-zinc-400">Reached &quot;To&quot;</TableHead>
                    <TableHead className="text-right text-zinc-400">Retention</TableHead>
                    <TableHead className="text-right text-zinc-400">Leakage</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {funnelData.edges.map((edge) => (
                    <TableRow key={`${edge.from_stage}-${edge.to_stage}`} className="border-zinc-800">
                      <TableCell className="text-zinc-200">
                        <span className="text-xs text-zinc-500">{edge.from_label}</span>
                        <span className="mx-1 text-zinc-600">→</span>
                        <span className="text-xs text-zinc-300">{edge.to_label}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-zinc-300">{edge.from_count}</TableCell>
                      <TableCell className="text-right tabular-nums text-zinc-300">{edge.to_count}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {edge.retention_pct != null ? (
                          <span className="text-emerald-400">{edge.retention_pct.toFixed(1)}%</span>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {edge.leakage_pct != null ? (
                          <span
                            className={cn(
                              "font-medium",
                              edge.leakage_pct >= 50 ? "text-rose-400" : "text-amber-300",
                            )}
                          >
                            {edge.leakage_pct.toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="border-sky-500/25 bg-zinc-950/90">
          <CardHeader className="flex flex-col gap-3 border-b border-zinc-800/80 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <CardTitle className="text-zinc-50">Recovery HQ</CardTitle>
              <CardDescription>
                High-intent sessions (quote or checkout) with no hold, quiet ≥2h. When the guest opts into
                Concierge or completes a hold, <strong>PII surfaces here</strong> for Command Center recovery
                (internal only). <strong>Drop-off</strong> = furthest stage reached; <strong>Last touch</strong>{" "}
                = final intent event.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="shrink-0 border-violet-500/40 bg-violet-950/40 text-violet-100 hover:bg-violet-900/50"
              onClick={() => setForgeOpen(true)}
              disabled={!enticementForge}
            >
              <Wand2 className="mr-2 h-4 w-4" />
              Enticement Forge
            </Button>
          </CardHeader>
          <CardContent className="overflow-x-auto pt-4">
            {!funnelData.ledger_ready ? (
              <p className="text-sm text-amber-300">
                Intent ledger not ready — run <code className="text-xs">alembic upgrade head</code>.
              </p>
            ) : recoveryRows.length === 0 ? (
              <p className="text-sm text-zinc-500">No cold high-intent sessions in this window.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="border-zinc-800 hover:bg-transparent">
                    <TableHead className="text-zinc-400">FP</TableHead>
                    <TableHead className="text-zinc-400">Guest</TableHead>
                    <TableHead className="text-zinc-400">Email</TableHead>
                    <TableHead className="text-zinc-400">Phone</TableHead>
                    <TableHead className="text-zinc-400">Drop-off</TableHead>
                    <TableHead className="text-zinc-400">Last touch</TableHead>
                    <TableHead className="text-right text-zinc-400">Score</TableHead>
                    <TableHead className="text-zinc-400">Cabin</TableHead>
                    <TableHead className="text-zinc-400">Ledger</TableHead>
                    <TableHead className="text-zinc-400">Seen</TableHead>
                    <TableHead className="w-[100px] text-zinc-400" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recoveryRows.map((row) => (
                    <TableRow key={row.sessionFp} className="border-zinc-800">
                      <TableCell className="font-mono text-xs text-zinc-300">{row.sessionFpSuffix}</TableCell>
                      <TableCell className="max-w-[140px] text-sm text-zinc-200">
                        {row.guestDisplayName ? row.guestDisplayName : <span className="text-zinc-600">—</span>}
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-xs text-zinc-300">
                        {row.guestEmail ? row.guestEmail : <span className="text-zinc-600">—</span>}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-zinc-300">
                        {row.guestPhone ? row.guestPhone : <span className="text-zinc-600">—</span>}
                      </TableCell>
                      <TableCell className="max-w-[160px]">
                        <div className="font-mono text-[11px] text-cyan-300/90">{row.dropOffPoint}</div>
                        <div className="text-[11px] text-zinc-500">{row.dropOffPointLabel}</div>
                        <div className="text-[11px] text-amber-200/80">{row.frictionLabel}</div>
                      </TableCell>
                      <TableCell className="text-xs text-zinc-400">{row.lastEventType}</TableCell>
                      <TableCell className="text-right tabular-nums text-zinc-200">{row.intentScoreEstimate}</TableCell>
                      <TableCell className="text-xs text-zinc-500">{row.propertySlug ?? "—"}</TableCell>
                      <TableCell className="text-xs">
                        {row.linkedGuestId ? (
                          <Link className="text-sky-400 hover:underline" href={`/guests/${row.linkedGuestId}`}>
                            Open
                          </Link>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-zinc-500">{row.lastSeenAt}</TableCell>
                      <TableCell>
                        <CopySessionFp fingerprint={row.sessionFp} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Dialog open={forgeOpen} onOpenChange={setForgeOpen}>
          <DialogContent className="max-w-lg border-zinc-800 bg-zinc-950 text-zinc-100">
            <DialogHeader>
              <DialogTitle className="text-zinc-50">Enticement Forge</DialogTitle>
              <DialogDescription className="text-zinc-400">
                Preview the Enticer Swarm SMS body before enabling{" "}
                <code className="text-xs text-violet-300">CONCIERGE_RECOVERY_SMS_ENABLED</code>. Template
                variables: <code className="text-xs">{"{book_url}"}</code>,{" "}
                <code className="text-xs">{"{first_name}"}</code>.
              </DialogDescription>
            </DialogHeader>
            {enticementForge ? (
              <div className="space-y-4 text-sm">
                <div className="grid gap-2 sm:grid-cols-2">
                  <Kpi
                    label="Swarm armed"
                    value={enticementForge.smsEnabled ? "ON" : "OFF"}
                    variant={enticementForge.smsEnabled ? "warning" : "success"}
                  />
                  <Kpi
                    label="Twilio configured"
                    value={enticementForge.twilioConfigured ? "Yes" : "No"}
                    variant={enticementForge.twilioConfigured ? "success" : "danger"}
                  />
                  <Kpi label="Cooldown (h)" value={enticementForge.cooldownHours} hint="Per guest + template" />
                  <Kpi
                    label="Book URL"
                    value={enticementForge.bookUrl === "Not configured" ? "Missing" : "Set"}
                    hint={enticementForge.bookUrl}
                  />
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">Sample send</p>
                  <p className="mt-2 rounded-lg border border-zinc-800 bg-zinc-900/80 p-3 text-sm leading-relaxed text-zinc-200">
                    {enticementForge.sampleRenderedBody}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">Uses first_name=&quot;Jordan&quot; for preview.</p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">Raw template</p>
                  <pre className="mt-2 max-h-32 overflow-auto rounded-lg border border-zinc-800 bg-black/40 p-3 text-xs text-zinc-400 whitespace-pre-wrap">
                    {enticementForge.templateRaw}
                  </pre>
                </div>
              </div>
            ) : (
              <p className="text-sm text-zinc-500">Forge preview unavailable.</p>
            )}
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-emerald-500/25 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <ShieldCheck className="h-5 w-5 text-emerald-400" />
              Handshake convergence
            </CardTitle>
            <CardDescription>
              Direct-booking holds ↔ Stripe ↔ reservations. Orphan risk = expired active hold still holding a
              PaymentIntent.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 pt-4 sm:grid-cols-2">
            <Kpi label="Active holds" value={pulseData.handshake.holds_active} />
            <Kpi label="Converted holds (24h)" value={pulseData.handshake.holds_converted_last_24h} />
            <Kpi label="Direct reservations (24h)" value={pulseData.handshake.direct_reservations_last_24h} />
            <Kpi
              label="Orphan risk holds"
              value={pulseData.handshake.orphan_risk_holds}
              variant={pulseData.handshake.orphan_risk_holds > 0 ? "warning" : "success"}
              hint="Review in Reservations / payments lane"
            />
            <Kpi
              label="Converted + reservation FK"
              value={pulseData.handshake.holds_with_conversion_fk}
              hint="Hardened handshake path"
            />
            <Kpi
              label="Legacy converted (no FK)"
              value={pulseData.handshake.holds_converted_legacy_no_fk}
              variant={pulseData.handshake.holds_converted_legacy_no_fk > 0 ? "warning" : "default"}
            />
          </CardContent>
        </Card>

        <Card className="border-violet-500/25 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Gavel className="h-5 w-5 text-violet-400" />
              Tribunal — God Head
            </CardTitle>
            <CardDescription>
              Fleet re-ingest target: {pulseData.tribunal.fleet_target_properties} properties. Pass threshold ={" "}
              {pulseData.tribunal.godhead_pass_threshold.toFixed(2)} (
              <code className="text-xs">SEO_GODHEAD_MIN_SCORE</code>).
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 pt-4 sm:grid-cols-2">
            <Kpi
              label="pending_human ≥ threshold"
              value={pulseData.tribunal.pending_human_at_or_above_threshold}
              variant="success"
              hint="Ready for human sign-off"
            />
            <Kpi
              label="pending_human &lt; threshold"
              value={pulseData.tribunal.pending_human_below_threshold}
              variant="warning"
              hint="Structural / rubric gaps"
            />
            <Kpi label="Score unknown" value={pulseData.tribunal.pending_human_score_unknown} />
            <Kpi label="Total queue (all statuses)" value={pulseData.seo_queue.total} />
          </CardContent>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-zinc-950/90">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 border-b border-zinc-800/80">
          <div>
            <CardTitle className="text-zinc-50">SEO queue density</CardTitle>
            <CardDescription>Swarm pipeline states</CardDescription>
          </div>
          <Button asChild size="sm" className="bg-fuchsia-600 text-white hover:bg-fuchsia-500">
            <Link href="/seo-review?status=pending_human">Open SEO Review</Link>
          </Button>
        </CardHeader>
        <CardContent className="grid gap-3 pt-4 sm:grid-cols-5">
          <Kpi label="Drafted" value={pulseData.seo_queue.drafted} />
          <Kpi label="Needs rewrite" value={pulseData.seo_queue.needs_rewrite} />
          <Kpi label="Pending human" value={pulseData.seo_queue.pending_human} />
          <Kpi label="Deployed" value={pulseData.seo_queue.deployed} />
          <Kpi label="Rejected" value={pulseData.seo_queue.rejected} />
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <ThermometerSun className="h-5 w-5 text-amber-400" />
            Recent Tribunal queue (pending_human)
          </CardTitle>
          <CardDescription>
            Newest first. <strong>Media gallery</strong> column is heuristic (God Head feedback / snapshot hints)
            — not a DB guarantee.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto pt-4">
          {pulseData.tribunal.recent_pending_human.length === 0 ? (
            <p className="text-sm text-zinc-500">No rows in pending_human right now.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="text-zinc-400">Property</TableHead>
                  <TableHead className="text-zinc-400">Path</TableHead>
                  <TableHead className="text-right text-zinc-400">Score</TableHead>
                  <TableHead className="text-zinc-400">Model</TableHead>
                  <TableHead className="text-zinc-400">Media ctx</TableHead>
                  <TableHead className="text-zinc-400">Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pulseData.tribunal.recent_pending_human.map((row) => (
                  <TableRow key={row.patch_id} className="border-zinc-800">
                    <TableCell className="text-zinc-200">
                      <div className="font-medium">{row.property_name ?? "—"}</div>
                      <div className="text-xs text-zinc-500">{row.property_slug ?? "—"}</div>
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate text-xs text-zinc-400">{row.page_path}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.godhead_score != null ? (
                        <span
                          className={cn(
                            "font-medium",
                            row.godhead_score >= pulseData.tribunal.godhead_pass_threshold
                              ? "text-emerald-400"
                              : "text-amber-300",
                          )}
                        >
                          {row.godhead_score.toFixed(3)}
                        </span>
                      ) : (
                        <span className="text-zinc-500">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-zinc-500">{row.godhead_model ?? "—"}</TableCell>
                    <TableCell>
                      {row.media_gallery_in_source ? (
                        <span className="text-xs text-emerald-400">Likely</span>
                      ) : (
                        <span className="text-xs text-zinc-600">—</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-zinc-500">
                      {new Date(row.updated_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="border border-dashed border-zinc-700 bg-zinc-950/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
            <CreditCard className="h-4 w-4" />
            Next strike — Redirect Vanguard
          </CardTitle>
          <CardDescription className="text-zinc-500">
            When Tribunal scores stabilize and handshake metrics stay clean, route the{" "}
            {pulseData.tribunal.fleet_target_properties} cabins via Cloudflare Worker from Drupal to the
            sovereign Next.js storefront (preserve 4,530 legacy 301s per doctrine).
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
