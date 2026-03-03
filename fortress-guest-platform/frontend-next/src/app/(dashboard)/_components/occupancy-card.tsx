"use client";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Home } from "lucide-react";
import type { DashboardStats } from "@/lib/types";

interface Props {
  stats?: DashboardStats;
}

export function OccupancyCard({ stats }: Props) {
  const rate = stats?.occupancy_rate ?? 0;
  const total = stats?.total_properties ?? 14;
  const occupied = stats ? Math.round((rate / 100) * total) : 0;
  const available = total - occupied;

  const circumference = 2 * Math.PI * 40;
  const strokeDash = (rate / 100) * circumference;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Home className="h-5 w-5 text-emerald-500" />
          Occupancy
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-4">
        <div className="relative h-28 w-28">
          <svg className="h-28 w-28 -rotate-90" viewBox="0 0 100 100">
            <circle
              cx="50"
              cy="50"
              r="40"
              stroke="currentColor"
              strokeWidth="8"
              fill="none"
              className="text-muted/30"
            />
            <circle
              cx="50"
              cy="50"
              r="40"
              stroke="currentColor"
              strokeWidth="8"
              fill="none"
              strokeDasharray={`${strokeDash} ${circumference}`}
              strokeLinecap="round"
              className="text-emerald-500 transition-all duration-700"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-2xl font-bold">{Math.round(rate)}%</span>
          </div>
        </div>
        <div className="flex gap-6 text-sm">
          <div className="text-center">
            <p className="font-semibold">{occupied}</p>
            <p className="text-xs text-muted-foreground">Occupied</p>
          </div>
          <div className="text-center">
            <p className="font-semibold">{available}</p>
            <p className="text-xs text-muted-foreground">Available</p>
          </div>
          <div className="text-center">
            <p className="font-semibold">{total}</p>
            <p className="text-xs text-muted-foreground">Total</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
