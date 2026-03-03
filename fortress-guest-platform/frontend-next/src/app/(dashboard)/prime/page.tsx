"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { usePrimeSnapshot } from "@/lib/hooks";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  Activity,
  Banknote,
  DollarSign,
  Landmark,
  ShieldAlert,
  Terminal,
  TrendingUp,
  Zap,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface TelemetryEvent {
  type: string;
  topic?: string;
  partition?: number;
  offset?: number;
  ts?: string;
  event?: Record<string, unknown>;
}

interface AccountInfo {
  name: string;
  balance: number;
  total_debit: number;
  total_credit: number;
}

interface TimelineEntry {
  day: string | null;
  pm_commission: number;
  rental_revenue: number;
  cash_inflow: number;
}

interface JournalEntry {
  id: number;
  date: string | null;
  description: string;
  reference_type: string;
  property_id: string;
  posted_by: string;
  lines: Array<{
    account_code: string;
    account_name: string;
    debit: number;
    credit: number;
  }>;
}

interface PrimeSnapshot {
  accounts: Record<string, AccountInfo>;
  revenue_timeline: TimelineEntry[];
  recent_journals: JournalEntry[];
  payout_summary: Record<string, { count: number; total: number }>;
  system_pulse: {
    journal_entries_today: number;
    total_properties: number;
    active_reservations: number;
  };
}

const TOPIC_COLORS: Record<string, string> = {
  "trust.revenue.staged": "text-emerald-400",
  "trust.payout.staged": "text-blue-400",
  "trust.accounting.staged": "text-amber-400",
  "enterprise.inbox.raw": "text-slate-400",
};

function fmt(n: number | undefined): string {
  if (n == null) return "0.00";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default function FortressPrimeDashboard() {
  const { data: snapshot } = usePrimeSnapshot();
  const prime = snapshot as PrimeSnapshot | undefined;

  const [telemetryLogs, setTelemetryLogs] = useState<TelemetryEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const addEvent = useCallback((evt: TelemetryEvent) => {
    setTelemetryLogs((prev) => {
      const next = [...prev, evt];
      return next.length > 200 ? next.slice(-200) : next;
    });
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource("/api/admin/prime/stream");

      es.onopen = () => setConnected(true);

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as TelemetryEvent;
          if (data.type === "heartbeat") return;
          addEvent(data);
        } catch {
          /* ignore malformed */
        }
      };

      es.onerror = () => {
        setConnected(false);
        es?.close();
        retryTimeout = setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      es?.close();
      clearTimeout(retryTimeout);
    };
  }, [addEvent]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [telemetryLogs]);

  const acct4100 = prime?.accounts?.["4100"];
  const acct1010 = prime?.accounts?.["1010"];
  const acct2000 = prime?.accounts?.["2000"];
  const acct2100 = prime?.accounts?.["2100"];
  const pulse = prime?.system_pulse;

  const chartData = (prime?.revenue_timeline ?? []).map((d) => ({
    day: d.day ? new Date(d.day).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "",
    pm_commission: d.pm_commission,
    rental_revenue: d.rental_revenue,
    cash_inflow: d.cash_inflow,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Activity className="h-6 w-6 text-emerald-500" />
            Fortress Prime
          </h1>
          <p className="text-muted-foreground text-sm">
            Global Command & Telemetry Center
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono">
          <Badge
            variant={connected ? "default" : "destructive"}
            className="gap-1"
          >
            <span className="relative flex h-1.5 w-1.5">
              {connected && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span
                className={`relative inline-flex rounded-full h-1.5 w-1.5 ${connected ? "bg-emerald-500" : "bg-red-500"}`}
              />
            </span>
            {connected ? "Swarms Online" : "Reconnecting..."}
          </Badge>
        </div>
      </div>

      {/* KPI Strip */}
      <div className="grid gap-3 md:grid-cols-5">
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">PM Revenue (4100)</p>
              <DollarSign className="h-3.5 w-3.5 text-emerald-500" />
            </div>
            <p className="text-xl font-bold font-mono text-emerald-500">
              ${fmt(acct4100?.balance)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Cash - Trust (1010)</p>
              <Landmark className="h-3.5 w-3.5 text-blue-400" />
            </div>
            <p className="text-xl font-bold font-mono">
              ${fmt(acct1010?.balance)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Owner Liability (2000)</p>
              <Banknote className="h-3.5 w-3.5 text-amber-400" />
            </div>
            <p className="text-xl font-bold font-mono">
              ${fmt(acct2000?.balance)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Accounts Payable</p>
              <ShieldAlert className="h-3.5 w-3.5 text-red-400" />
            </div>
            <p className="text-xl font-bold font-mono text-amber-400">
              ${fmt(acct2100?.balance)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Journals Today</p>
              <Zap className="h-3.5 w-3.5 text-violet-400" />
            </div>
            <p className="text-xl font-bold font-mono">
              {pulse?.journal_entries_today ?? 0}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {pulse?.total_properties ?? 0} properties | {pulse?.active_reservations ?? 0} active res.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Chart + Terminal */}
      <div className="grid gap-4 md:grid-cols-5">
        {/* Revenue Timeline */}
        <Card className="md:col-span-3">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <TrendingUp className="h-4 w-4 text-emerald-500" />
              Sovereign Treasury — 30 Day Revenue
            </CardTitle>
            <CardDescription>
              PM Commission (4100), Rental Revenue (4000+4010), and Cash Inflow
              (1010)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[280px] w-full">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient
                        id="pmGrad"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="5%"
                          stopColor="#10b981"
                          stopOpacity={0.3}
                        />
                        <stop
                          offset="95%"
                          stopColor="#10b981"
                          stopOpacity={0}
                        />
                      </linearGradient>
                      <linearGradient
                        id="revGrad"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="5%"
                          stopColor="#3b82f6"
                          stopOpacity={0.3}
                        />
                        <stop
                          offset="95%"
                          stopColor="#3b82f6"
                          stopOpacity={0}
                        />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      className="stroke-border"
                    />
                    <XAxis
                      dataKey="day"
                      className="text-muted-foreground"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      className="text-muted-foreground"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(v) => `$${v}`}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        borderColor: "hsl(var(--border))",
                        borderRadius: 8,
                      }}
                      labelStyle={{ color: "hsl(var(--foreground))" }}
                      formatter={(
                        value: number | undefined,
                        name: string | undefined,
                      ) => [
                        `$${fmt(value ?? 0)}`,
                        name === "pm_commission"
                          ? "PM Commission"
                          : name === "rental_revenue"
                            ? "Rental Revenue"
                            : "Cash Inflow",
                      ]}
                    />
                    <Area
                      type="monotone"
                      dataKey="cash_inflow"
                      stroke="#3b82f6"
                      fill="url(#revGrad)"
                      strokeWidth={2}
                    />
                    <Area
                      type="monotone"
                      dataKey="pm_commission"
                      stroke="#10b981"
                      fill="url(#pmGrad)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                  No journal data in the last 30 days
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Live Event Terminal */}
        <Card className="md:col-span-2 font-mono">
          <CardHeader className="pb-2 border-b">
            <CardTitle className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Terminal className="h-3.5 w-3.5" />
              Redpanda Event Broker [Live Feed]
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div
              ref={scrollRef}
              className="h-[310px] overflow-y-auto p-3 space-y-0.5 text-[11px] leading-relaxed"
            >
              {telemetryLogs.length === 0 ? (
                <p className="text-muted-foreground italic">
                  Listening for Swarm telemetry...
                </p>
              ) : (
                telemetryLogs.map((log, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="text-muted-foreground flex-shrink-0">
                      [{log.ts?.split("T")[1]?.slice(0, 8) ?? "??:??:??"}]
                    </span>
                    <span
                      className={`flex-shrink-0 ${TOPIC_COLORS[log.topic ?? ""] ?? "text-muted-foreground"}`}
                    >
                      {log.topic?.split(".").pop() ?? "heartbeat"}
                    </span>
                    <span className="text-foreground/70 truncate">
                      {log.event
                        ? JSON.stringify(log.event).slice(0, 120)
                        : "—"}
                    </span>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent Journal Entries */}
      {prime?.recent_journals && prime.recent_journals.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              Iron Dome — Recent Journal Entries
            </CardTitle>
            <CardDescription>
              Last 30 double-entry commits across the ledger
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {prime.recent_journals.map((je) => {
                const totalDebit = je.lines.reduce(
                  (s, l) => s + (l.debit || 0),
                  0,
                );
                return (
                  <div
                    key={je.id}
                    className="flex items-center justify-between text-xs border-b border-border/50 pb-1"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Badge
                        variant="outline"
                        className="text-[10px] font-mono flex-shrink-0"
                      >
                        JE-{je.id}
                      </Badge>
                      <span className="text-muted-foreground flex-shrink-0">
                        {je.date ?? "—"}
                      </span>
                      <span className="truncate">{je.description}</span>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0 ml-2">
                      <Badge
                        variant="secondary"
                        className="text-[10px] font-mono"
                      >
                        {je.reference_type ?? "—"}
                      </Badge>
                      <span className="font-mono text-emerald-500">
                        ${fmt(totalDebit)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
