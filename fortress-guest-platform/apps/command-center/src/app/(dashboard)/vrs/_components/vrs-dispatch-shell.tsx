"use client";

import Link from "next/link";
import { Radio, RefreshCw } from "lucide-react";
import { useFunnelHQ } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function formatPct(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  const pct = value <= 1 ? value * 100 : value;
  return `${pct.toFixed(1)}%`;
}

export function VrsDispatchShell() {
  const { data, isLoading, isError, error, refetch, isFetching } = useFunnelHQ();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Radio className="h-7 w-7 text-primary" />
            Dispatch Radar
          </h1>
          <p className="text-muted-foreground max-w-2xl text-sm">
            Live funnel edges and recovery queue from{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              GET /api/telemetry/funnel-hq
            </code>
            . Use linked ops surfaces to act on stalled sessions.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isFetching}
          onClick={() => void refetch()}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Quick links</CardTitle>
            <CardDescription>Operational dispatch lanes</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <Link className="text-primary underline-offset-4 hover:underline" href="/messages">
              Messages
            </Link>
            <Link className="text-primary underline-offset-4 hover:underline" href="/email-intake">
              Email intake
            </Link>
            <Link className="text-primary underline-offset-4 hover:underline" href="/vrs/quotes">
              VRS quotes
            </Link>
            <Link className="text-primary underline-offset-4 hover:underline" href="/reservations">
              Reservations
            </Link>
          </CardContent>
        </Card>
        <Card className="md:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Funnel window</CardTitle>
            <CardDescription>
              {data
                ? `${data.window_hours}h window · ${data.distinct_sessions_in_window} sessions · updated ${new Date(data.generated_at).toLocaleString()}`
                : isLoading
                  ? "Loading telemetry…"
                  : isError
                    ? (error instanceof Error ? error.message : "Failed to load funnel HQ")
                    : "No data"}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-3 text-sm">
            <div>
              <p className="text-muted-foreground">Ledger ready</p>
              <p className="font-medium">{data ? (data.ledger_ready ? "Yes" : "No") : "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Min stale (minutes)</p>
              <p className="font-medium">{data?.min_stale_minutes ?? "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">SMS enticer</p>
              <p className="font-medium">
                {data?.enticement_forge?.sms_enabled ? "Enabled" : "Off"}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Funnel edges</CardTitle>
          <CardDescription>Stage-to-stage retention and leakage</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : isError ? (
            <p className="text-destructive text-sm">
              {error instanceof Error ? error.message : "Could not load funnel edges"}
            </p>
          ) : !data?.edges?.length ? (
            <p className="text-muted-foreground text-sm">No edges in this window.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>From → To</TableHead>
                  <TableHead className="text-right">Counts</TableHead>
                  <TableHead className="text-right">Retention</TableHead>
                  <TableHead className="text-right">Leakage</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.edges.map((edge) => (
                  <TableRow key={`${edge.from_stage}-${edge.to_stage}`}>
                    <TableCell className="font-medium">
                      {edge.from_label} → {edge.to_label}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {edge.from_count} → {edge.to_count}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatPct(edge.retention_pct)}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatPct(edge.leakage_pct)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recovery queue</CardTitle>
          <CardDescription>Sessions eligible for re-engagement</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : isError ? null : !data?.recovery?.length ? (
            <p className="text-muted-foreground text-sm">No recovery rows.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Drop-off</TableHead>
                  <TableHead>Friction</TableHead>
                  <TableHead>Guest</TableHead>
                  <TableHead>Property</TableHead>
                  <TableHead>Last seen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.recovery.map((row) => (
                  <TableRow key={row.session_fp}>
                    <TableCell className="max-w-[200px] truncate font-mono text-xs">
                      {row.drop_off_point_label || row.drop_off_point}
                    </TableCell>
                    <TableCell>{row.friction_label}</TableCell>
                    <TableCell className="max-w-[180px] truncate text-sm">
                      {row.guest_display_name || row.guest_email || row.guest_phone || "—"}
                    </TableCell>
                    <TableCell className="max-w-[140px] truncate text-sm">
                      {row.property_slug ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(row.last_seen_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
