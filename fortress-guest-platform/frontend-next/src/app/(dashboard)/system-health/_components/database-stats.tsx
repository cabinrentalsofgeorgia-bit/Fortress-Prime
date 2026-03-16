"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { SystemHealthDatabases } from "@/lib/types";
import { Database, Layers } from "lucide-react";

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

interface DatabaseStatsProps {
  databases: SystemHealthDatabases;
}

export function DatabaseStats({ databases }: DatabaseStatsProps) {
  if (!databases) return null;
  const pgTables = Object.entries(databases.postgres ?? {});
  const qdrantColls = Object.entries(databases.qdrant ?? {});

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Postgres */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            PostgreSQL
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {pgTables.map(([table, rows]) => (
              <div key={table} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground font-mono">{table}</span>
                <span className="tabular-nums font-medium">{formatNumber(rows)} rows</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Qdrant */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" />
            Qdrant Vector DB
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {qdrantColls.map(([name, info]) => (
              <div key={name} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground font-mono">{name}</span>
                <div className="flex items-center gap-2">
                  <span className="tabular-nums font-medium">{formatNumber(info.points)} pts</span>
                  <Badge
                    variant={info.status === "green" ? "default" : "destructive"}
                    className="text-[9px] px-1 py-0"
                  >
                    {info.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
