"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EmailIntakeLearningResponse } from "@/lib/types";

type Props = {
  data?: EmailIntakeLearningResponse;
  isLoading: boolean;
};

export function LearningTab({ data, isLoading }: Props) {
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading learning metrics...</div>;
  if (!data) return <div className="text-sm text-muted-foreground">No learning data.</div>;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Total Reviewed</p>
            <p className="text-2xl font-bold">{data.total_reviewed.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Total Reclassified</p>
            <p className="text-2xl font-bold">{data.total_reclassified.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Avg Grade</p>
            <p className="text-2xl font-bold">{data.avg_grade}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Total Dismissed</p>
            <p className="text-2xl font-bold">{data.total_dismissed.toLocaleString()}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Grade Distribution</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-5">
          {data.grade_distribution.map((row) => (
            <div key={row.grade} className="rounded-md border p-3 text-center">
              <p className="text-xs text-muted-foreground">{row.grade}/5</p>
              <p className="text-lg font-semibold">{row.count}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Activity</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {data.recent.map((row, idx) => (
            <div key={`${row.actor}-${row.created_at}-${idx}`} className="rounded-md border p-2">
              <p className="text-sm font-medium">
                {row.actor} · {row.action_type}
              </p>
              <p className="text-xs text-muted-foreground">
                {row.old_division || "-"} → {row.new_division || "-"} ·{" "}
                {new Date(row.created_at).toLocaleString()}
              </p>
              {row.subject && <p className="text-sm mt-1">{row.subject}</p>}
            </div>
          ))}
          {data.recent.length === 0 && (
            <p className="text-sm text-muted-foreground">No learning activity yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

