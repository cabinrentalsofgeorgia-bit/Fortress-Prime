"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { VrsMessageStats } from "@/lib/types";

type Props = {
  stats?: VrsMessageStats;
};

export function VrsMessagingStatsPanel({ stats }: Props) {
  const total = stats?.total_messages ?? 0;
  const inbound = stats?.inbound ?? 0;
  const outbound = stats?.outbound ?? 0;
  const automationRate = Math.round(stats?.automation_rate ?? 0);
  const confidence = Math.round((stats?.avg_ai_confidence ?? 0) * 100);
  const sentiment = stats?.sentiment_distribution ?? {};
  const sentimentTotal = Object.values(sentiment).reduce((sum, n) => sum + n, 0);
  const positiveSentiment = sentimentTotal > 0 ? Math.round(((sentiment.positive ?? 0) / sentimentTotal) * 100) : 0;

  const cells = [
    { label: "Total Messages", value: total },
    { label: "Inbound", value: inbound },
    { label: "Outbound", value: outbound },
    { label: "Automation Rate", value: `${automationRate}%` },
    { label: "AI Confidence", value: `${confidence}%` },
    { label: "Positive Sentiment", value: sentimentTotal > 0 ? `${positiveSentiment}%` : "N/A" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Guest Communication</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        {cells.map((cell) => (
          <div key={cell.label} className="rounded-md border p-3">
            <p className="text-lg font-semibold">{cell.value}</p>
            <p className="text-xs text-muted-foreground">{cell.label}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

