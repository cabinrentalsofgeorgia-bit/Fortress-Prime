"use client";

import { useState, useMemo } from "react";
import { useDashboardStats, useProperties, useReservations } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  BarChart3,
  TrendingUp,
  Bot,
  DollarSign,
  Download,
  Link2,
  CalendarDays,
  Home,
  Users,
} from "lucide-react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { toast } from "sonner";

const COLORS = [
  "hsl(217, 91%, 60%)",
  "hsl(142, 71%, 45%)",
  "hsl(47, 96%, 53%)",
  "hsl(0, 84%, 60%)",
  "hsl(280, 67%, 55%)",
];

function subtractDays(d: Date, n: number) {
  const r = new Date(d);
  r.setDate(r.getDate() - n);
  return r;
}

export default function AnalyticsPage() {
  const { data: stats } = useDashboardStats();
  const { data: properties } = useProperties();
  const { data: reservations } = useReservations();
  const [range, setRange] = useState("30d");

  const now = new Date();
  const rangeStart = useMemo(() => {
    switch (range) {
      case "7d": return subtractDays(now, 7);
      case "30d": return subtractDays(now, 30);
      case "90d": return subtractDays(now, 90);
      case "365d": return subtractDays(now, 365);
      default: return subtractDays(now, 30);
    }
  }, [range]);

  const filteredRes = useMemo(() =>
    (reservations ?? []).filter((r) => {
      const ci = new Date(r.check_in_date);
      return ci >= rangeStart && ci <= now;
    }),
  [reservations, rangeStart],
  );

  const totalRevenue = filteredRes.reduce((s, r) => s + (r.total_amount ?? 0), 0);
  const avgNightly = filteredRes.length > 0
    ? totalRevenue / filteredRes.reduce((s, r) => {
        const nights = Math.max(1, Math.round((new Date(r.check_out_date).getTime() - new Date(r.check_in_date).getTime()) / 86400000));
        return s + nights;
      }, 0)
    : 0;

  // Revenue trend (monthly)
  const revenueTrend = useMemo(() => {
    const months: Record<string, number> = {};
    for (const r of filteredRes) {
      const m = (r.check_in_date ?? "").slice(0, 7);
      months[m] = (months[m] ?? 0) + (r.total_amount ?? 0);
    }
    return Object.entries(months)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, revenue]) => ({ month, revenue: Math.round(revenue) }));
  }, [filteredRes]);

  // Property bookings
  const propertyBookings = useMemo(() =>
    (properties ?? []).map((p) => ({
      name: p.name.length > 18 ? p.name.slice(0, 18) + "..." : p.name,
      fullName: p.name,
      bookings: filteredRes.filter((r) => r.property_id === p.id && r.status !== "cancelled").length,
      revenue: filteredRes.filter((r) => r.property_id === p.id).reduce((s, r) => s + (r.total_amount ?? 0), 0),
    })).sort((a, b) => b.revenue - a.revenue),
  [properties, filteredRes],
  );

  // Source breakdown
  const sourceData = useMemo(() => {
    const map: Record<string, number> = {};
    for (const r of filteredRes) {
      const src = r.booking_source || "unknown";
      map[src] = (map[src] ?? 0) + 1;
    }
    return Object.entries(map)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 6);
  }, [filteredRes]);

  // Status breakdown
  const statusBreakdown = useMemo(() =>
    ["confirmed", "checked_in", "checked_out", "cancelled"].map((status) => ({
      name: status.replace("_", " "),
      value: filteredRes.filter((r) => r.status === status).length,
    })),
  [filteredRes],
  );

  // Occupancy heatmap data (property x week)
  const heatmapData = useMemo(() => {
    const weeks: string[] = [];
    for (let i = 0; i < 4; i++) {
      const d = subtractDays(now, (3 - i) * 7);
      weeks.push(`W${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`);
    }
    return (properties ?? []).map((p) => {
      const row: Record<string, unknown> = { property: p.name.length > 16 ? p.name.slice(0, 16) + "…" : p.name };
      weeks.forEach((w, i) => {
        const weekStart = subtractDays(now, (3 - i) * 7);
        const weekEnd = subtractDays(now, (2 - i) * 7);
        const booked = filteredRes.filter((r) =>
          r.property_id === p.id &&
          new Date(r.check_in_date) <= weekEnd &&
          new Date(r.check_out_date) >= weekStart &&
          r.status !== "cancelled",
        ).length;
        row[w] = booked > 0 ? 1 : 0;
      });
      return row;
    });
  }, [properties, filteredRes]);

  function exportCsv() {
    const header = "Property,Bookings,Revenue\n";
    const rows = propertyBookings.map((p) => `"${p.fullName}",${p.bookings},${p.revenue}`).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fortress-analytics-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("CSV exported");
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
          <p className="text-muted-foreground">
            Performance metrics and business intelligence
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={range} onValueChange={setRange}>
            <SelectTrigger className="w-36">
              <CalendarDays className="h-4 w-4 mr-2" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">Last 7 days</SelectItem>
              <SelectItem value="30d">Last 30 days</SelectItem>
              <SelectItem value="90d">Last 90 days</SelectItem>
              <SelectItem value="365d">Last year</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={exportCsv}>
            <Download className="h-4 w-4 mr-2" />
            Export CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              navigator.clipboard.writeText(window.location.href);
              toast.success("Dashboard link copied");
            }}
          >
            <Link2 className="h-4 w-4 mr-2" />
            Share
          </Button>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Revenue</p>
            <p className="text-2xl font-bold">${totalRevenue.toLocaleString()}</p>
            <p className="text-xs text-muted-foreground">{filteredRes.length} bookings</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Avg Nightly Rate</p>
            <p className="text-2xl font-bold">${Math.round(avgNightly).toLocaleString()}</p>
            <p className="text-xs text-muted-foreground">Per occupied night</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Occupancy</p>
            <p className="text-2xl font-bold">
              {stats ? `${Math.round(stats.occupancy_rate)}%` : "–"}
            </p>
            <p className="text-xs text-muted-foreground">Current period</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">AI Automation</p>
            <p className="text-2xl font-bold">
              {stats ? `${Math.round(stats.ai_automation_rate)}%` : "–"}
            </p>
            <p className="text-xs text-muted-foreground">Auto-response rate</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Properties</p>
            <p className="text-2xl font-bold">{properties?.length ?? "–"}</p>
            <p className="text-xs text-muted-foreground">{(properties ?? []).filter((p) => p.is_active).length} active</p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="revenue">
        <TabsList>
          <TabsTrigger value="revenue">Revenue</TabsTrigger>
          <TabsTrigger value="bookings">Bookings</TabsTrigger>
          <TabsTrigger value="sources">Sources</TabsTrigger>
          <TabsTrigger value="occupancy">Occupancy</TabsTrigger>
        </TabsList>

        <TabsContent value="revenue" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Revenue Trend</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={revenueTrend}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={(v) => [`$${Number(v).toLocaleString()}`, "Revenue"]} />
                    <Line type="monotone" dataKey="revenue" stroke="hsl(142, 71%, 45%)" strokeWidth={2} dot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="bookings" className="mt-4">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Bookings by Property</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={propertyBookings} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
                      <XAxis type="number" />
                      <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="bookings" fill="hsl(217, 91%, 60%)" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Reservation Status</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-80 flex items-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={statusBreakdown.filter((s) => s.value > 0)}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={100}
                        dataKey="value"
                        label={({ name, value }) => `${name}: ${value}`}
                      >
                        {statusBreakdown.map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="sources" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Booking Sources</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                {sourceData.map((s, i) => {
                  const total = sourceData.reduce((sum, x) => sum + x.value, 0);
                  const pct = total > 0 ? Math.round((s.value / total) * 100) : 0;
                  return (
                    <Card key={s.name}>
                      <CardContent className="pt-4">
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-sm font-medium capitalize">{s.name}</p>
                          <Badge variant="secondary">{pct}%</Badge>
                        </div>
                        <p className="text-2xl font-bold">{s.value}</p>
                        <div className="mt-2 h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{ width: `${pct}%`, backgroundColor: COLORS[i % COLORS.length] }}
                          />
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="occupancy" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Property Occupancy Heatmap</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {heatmapData.map((row, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-36 truncate shrink-0">
                      {row.property as string}
                    </span>
                    <div className="flex gap-1 flex-1">
                      {Object.entries(row)
                        .filter(([k]) => k !== "property")
                        .map(([week, val]) => (
                          <div
                            key={week}
                            className={`flex-1 h-8 rounded text-[10px] flex items-center justify-center ${
                              (val as number) > 0
                                ? "bg-emerald-500/70 text-white"
                                : "bg-muted"
                            }`}
                            title={`${row.property} — ${week}: ${(val as number) > 0 ? "Booked" : "Available"}`}
                          >
                            {week}
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-3 mt-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-emerald-500/70" /> Booked</span>
                <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-muted" /> Available</span>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Revenue by property table */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Revenue by Property</CardTitle>
            <Button variant="ghost" size="sm" onClick={exportCsv}>
              <Download className="h-4 w-4 mr-1" />
              CSV
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {propertyBookings.map((p) => (
              <div key={p.fullName} className="flex items-center justify-between py-2 border-b last:border-0">
                <div className="flex items-center gap-2">
                  <Home className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{p.fullName}</span>
                </div>
                <div className="flex items-center gap-4">
                  <Badge variant="outline" className="text-xs">{p.bookings} bookings</Badge>
                  <span className="text-sm font-bold text-green-600">${p.revenue.toLocaleString()}</span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
