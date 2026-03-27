"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  RefreshCw,
  RotateCcw,
  Shield,
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
  useCommandC2Pulse,
  useCommandC2Root,
  useRestartCommandC2Service,
  useVerifyCommandC2,
} from "@/lib/hooks";

function toneForService(status: string | undefined): string {
  switch (status) {
    case "running":
    case "online":
    case "success":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "down":
    case "error":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    default:
      return "border-zinc-700 bg-zinc-900/80 text-zinc-300";
  }
}

function formatPercent(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value.toFixed(1)}%`;
}

export function MobileC2Panel({ compact = false }: { compact?: boolean }) {
  const root = useCommandC2Root();
  const pulse = useCommandC2Pulse();
  const verify = useVerifyCommandC2();
  const restart = useRestartCommandC2Service();
  const [reportOpen, setReportOpen] = useState(false);

  const report = verify.data?.report ?? "";
  const rootData = root.data;
  const pulseData = pulse.data;
  const pulseError =
    pulse.error instanceof Error ? pulse.error.message : root.error instanceof Error ? root.error.message : null;

  const serviceRows = useMemo(
    () => Object.entries(pulseData?.services ?? {}).slice(0, compact ? 2 : 4),
    [compact, pulseData?.services],
  );

  const verificationTone =
    verify.data?.status === "success"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
      : verify.data?.status === "error"
        ? "border-rose-500/30 bg-rose-500/10 text-rose-200"
        : "border-cyan-500/30 bg-cyan-500/10 text-cyan-200";

  const headerStatus =
    rootData?.status === "online" && !pulseError
      ? "Stable"
      : root.isLoading || pulse.isLoading
        ? "Arming"
        : "Degraded";

  return (
    <>
      <Card className="border-cyan-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <Shield className="h-5 w-5 text-cyan-300" />
                Sovereign Link
              </CardTitle>
              <CardDescription>
                Mobile C2 telemetry for Captain plus hardened verification and restart actions.
              </CardDescription>
            </div>
            <span
              className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${verificationTone}`}
            >
              {headerStatus}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 pt-6">
          <div className={`grid gap-3 ${compact ? "sm:grid-cols-2" : "sm:grid-cols-2 xl:grid-cols-4"}`}>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Host</p>
              <p className="mt-1 text-lg font-semibold text-zinc-50">{pulseData?.host ?? rootData?.host ?? "--"}</p>
              <p className="mt-1 text-xs text-zinc-500">{pulseData?.node_name ?? rootData?.node_name ?? "--"}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">CPU / RAM</p>
              <p className="mt-1 text-lg font-semibold text-zinc-50">
                {formatPercent(pulseData?.cpu_load)} / {formatPercent(pulseData?.system.ram_percent)}
              </p>
              <p className="mt-1 text-xs text-zinc-500">{pulseData?.uptime ?? "Awaiting uptime telemetry"}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">GPU</p>
              <p className="mt-1 text-lg font-semibold text-zinc-50">
                {pulseData?.gpu?.error ? "Offline" : `${formatPercent(pulseData?.gpu?.vram_percent)} VRAM`}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {pulseData?.gpu?.error
                  ? pulseData.gpu.error
                  : `${pulseData?.gpu?.temp ?? "--"}°C · ${pulseData?.gpu?.utilization ?? "--"}% util`}
              </p>
            </div>
            {!compact ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Verification</p>
                <p className="mt-1 text-lg font-semibold text-zinc-50">
                  {verify.data?.status === "success" ? "Passed" : verify.data?.status === "error" ? "Failed" : "Idle"}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  {verify.isPending ? "Running live tunnel smoke..." : "Run Captain cloudflared smoke on demand."}
                </p>
              </div>
            ) : null}
          </div>

          {serviceRows.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {serviceRows.map(([service, status]) => (
                <div
                  key={service}
                  className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3"
                >
                  <span className="text-sm text-zinc-200">{service}</span>
                  <span
                    className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${toneForService(status)}`}
                  >
                    {status}
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          {pulseError ? (
            <div className="rounded-xl border border-amber-500/30 bg-amber-950/10 px-4 py-3 text-sm text-amber-100">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4" />
                <span>{pulseError}</span>
              </div>
            </div>
          ) : null}

          <div className={`flex flex-wrap gap-2 ${compact ? "" : "sm:justify-end"}`}>
            <Button
              type="button"
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => {
                void root.refetch();
                void pulse.refetch();
              }}
              disabled={root.isFetching || pulse.isFetching}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh Link
            </Button>
            <Button
              type="button"
              className="bg-cyan-700 text-white hover:bg-cyan-600"
              onClick={() =>
                verify.mutate(undefined, {
                  onSuccess: () => setReportOpen(true),
                })
              }
              disabled={verify.isPending}
            >
              {verify.isPending ? <Activity className="mr-2 h-4 w-4 animate-pulse" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
              Verify Link
            </Button>
            <Button
              type="button"
              variant="outline"
              className="border-amber-500/30 bg-amber-950/10 text-amber-100 hover:bg-amber-950/30"
              onClick={() => restart.mutate({ service: "cloudflared" })}
              disabled={restart.isPending}
            >
              {restart.isPending ? <Cpu className="mr-2 h-4 w-4 animate-pulse" /> : <RotateCcw className="mr-2 h-4 w-4" />}
              Restart Tunnel
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogContent className="max-w-3xl border-zinc-800 bg-zinc-950 text-zinc-100">
          <DialogHeader>
            <DialogTitle>Captain Verification Report</DialogTitle>
            <DialogDescription>
              Hardened output from `verify_captain_cloudflared.sh`.
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-lg border border-zinc-800 bg-black/40 p-4 text-xs text-zinc-300 whitespace-pre-wrap">
            {report || "No report captured."}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
