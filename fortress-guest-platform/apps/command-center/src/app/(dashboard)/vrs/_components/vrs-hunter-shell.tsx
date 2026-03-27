"use client";

import Link from "next/link";
import { Activity, Crosshair, Shield, Workflow } from "lucide-react";
import { useHunterHealth } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { HunterOpsQueue } from "./hunter-ops-queue";
import { MatrixTerminal } from "./matrix-terminal";

export function VrsHunterShell() {
  const health = useHunterHealth();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Crosshair className="h-7 w-7 text-primary" />
            Hunter Ops & Execution Terminal
          </h1>
          <p className="text-muted-foreground max-w-2xl text-sm">
            Recovery operations, AI draft review, and direct matrix dispatch converge here on the
            sovereign FastAPI Hunter and Agent routes.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={health.isFetching}
            onClick={() => {
              void health.refetch();
            }}
          >
            Refresh Health
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
          <div className="mb-3 flex items-center gap-2 border-b border-zinc-800 pb-2">
            <Activity className="h-4 w-4 text-emerald-400" />
            <h2 className="font-bold tracking-wide text-white">SYSTEM HEALTH STRIP</h2>
          </div>
          {health.isLoading ? (
            <p className="text-zinc-400">CHECKING HUNTER SERVICE...</p>
          ) : health.isError ? (
            <p className="text-rose-400">
              {health.error instanceof Error ? health.error.message : "Health check failed"}
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">STATUS</p>
                <p className="mt-2 text-lg font-bold text-emerald-400">{health.data?.status?.toUpperCase()}</p>
              </div>
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">SERVICE</p>
                <p className="mt-2 text-lg font-bold text-white">{health.data?.service?.toUpperCase()}</p>
              </div>
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">BOUNDARY</p>
                <p className="mt-2 text-lg font-bold text-cyan-400">SOVEREIGN</p>
              </div>
            </div>
          )}
        </div>

        <div className="rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
          <div className="mb-3 flex items-center gap-2 border-b border-zinc-800 pb-2">
            <Shield className="h-4 w-4 text-amber-400" />
            <h2 className="font-bold tracking-wide text-white">COMMAND LINKS</h2>
          </div>
          <div className="grid gap-2 text-sm">
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/vrs/quotes">
              /vrs/quotes
            </Link>
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/command/sovereign-pulse">
              /command/sovereign-pulse
            </Link>
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/guests">
              /guests
            </Link>
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/messages">
              /messages
            </Link>
          </div>
          <div className="mt-4 flex items-start gap-2 border border-zinc-800 bg-[#050505] p-3 text-xs text-zinc-400">
            <Workflow className="mt-0.5 h-4 w-4 shrink-0 text-cyan-400" />
            <p>
              Queue review and direct matrix override now operate on the same authenticated FastAPI
              surfaces verified in production.
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <HunterOpsQueue />
        <MatrixTerminal />
      </div>
    </div>
  );
}
