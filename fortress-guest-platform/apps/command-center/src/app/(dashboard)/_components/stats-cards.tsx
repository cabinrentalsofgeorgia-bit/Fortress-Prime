"use client";

import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  CalendarDays,
  Users,
  MessageSquare,
  Bot,
  Wrench,
  DollarSign,
  Home,
  TrendingUp,
  Workflow,
} from "lucide-react";
import type { DashboardStats } from "@/lib/types";

interface Props {
  stats?: DashboardStats;
}

export function StatsCards({ stats }: Props) {
  const cards = [
    {
      title: "Active Reservations",
      value: stats?.active_reservations ?? "–",
      sub: `${stats?.arriving_today ?? 0} arriving · ${stats?.departing_today ?? 0} departing`,
      icon: CalendarDays,
      color: "text-blue-500",
      href: "/reservations",
    },
    {
      title: "Current Guests",
      value: stats?.current_guests ?? "–",
      sub: `${stats?.total_properties ?? 0} properties`,
      icon: Users,
      color: "text-green-500",
      href: "/guests",
    },
    {
      title: "Messages Today",
      value: stats?.messages_today ?? "–",
      sub: `${stats?.unread_messages ?? 0} unread`,
      icon: MessageSquare,
      color: "text-violet-500",
      href: "/messages",
    },
    {
      title: "AI Automation",
      value: stats ? `${Math.round(stats.ai_automation_rate)}%` : "–",
      sub: "Auto-response rate",
      icon: Bot,
      color: "text-amber-500",
      href: "/ai-engine",
    },
    {
      title: "Occupancy Rate",
      value: stats ? `${Math.round(stats.occupancy_rate)}%` : "–",
      sub: "Current period",
      icon: Home,
      color: "text-emerald-500",
      href: "/analytics",
    },
    {
      title: "Revenue MTD",
      value: stats?.total_revenue_mtd
        ? `$${stats.total_revenue_mtd.toLocaleString()}`
        : "–",
      sub: "Month to date",
      icon: DollarSign,
      color: "text-green-600",
      href: "/analytics",
    },
    {
      title: "Open Work Orders",
      value: stats?.open_work_orders ?? "–",
      sub: "Needs attention",
      icon: Wrench,
      color: stats && stats.open_work_orders > 5 ? "text-red-500" : "text-orange-500",
      href: "/work-orders",
    },
    {
      title: "Properties Active",
      value: stats?.total_properties ?? "–",
      sub: "Managed portfolio",
      icon: TrendingUp,
      color: "text-cyan-500",
      href: "/properties",
    },
    {
      title: "Smart Workflows",
      value: "Active",
      sub: "Workflows and templates",
      icon: Workflow,
      color: "text-indigo-500",
      href: "/automations",
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {cards.map((c) => (
        <Link key={c.title} href={c.href}>
          <Card className="transition-colors hover:border-primary/30 hover:bg-accent/50 cursor-pointer h-full">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {c.title}
              </CardTitle>
              <c.icon className={`h-4 w-4 ${c.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{c.value}</div>
              <p className="text-xs text-muted-foreground">{c.sub}</p>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  );
}
