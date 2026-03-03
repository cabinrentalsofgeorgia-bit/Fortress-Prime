"use client";

import Link from "next/link";
import { AlertTriangle, Clock, ChevronRight, Bot } from "lucide-react";
import { useLegalCases } from "@/lib/legal-hooks";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { LegalCase } from "@/lib/legal-types";

function riskBadge(score: number | null | undefined) {
  if (score === null || score === undefined) return null;
  const cls =
    score >= 4
      ? "bg-red-500/10 text-red-500 border-red-500/30"
      : score >= 3
        ? "bg-amber-500/10 text-amber-500 border-amber-500/30"
        : "bg-green-500/10 text-green-500 border-green-500/30";
  return (
    <Badge variant="outline" className={cls}>
      Risk {score}/5
    </Badge>
  );
}

export function LegalCasesTable() {
  const { data, isLoading, error } = useLegalCases();

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
        <div>
          <p className="font-medium text-sm text-destructive">
            Failed to load legal cases
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {error?.message ?? "Unknown error"} — Check BFF proxy logs for
            auth details.
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (!data?.cases || !Array.isArray(data.cases) || data.cases.length === 0) {
    return (
      <p className="text-muted-foreground text-sm py-8 text-center">
        No legal cases registered.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {data.cases.map((c: LegalCase) => (
        <Link key={c.case_slug} href={`/legal/cases/${c.case_slug}`}>
          <Card className="hover:bg-accent/50 transition-colors cursor-pointer">
            <CardContent className="p-4 flex items-center justify-between gap-4">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-sm truncate">
                    {c.case_name}
                  </span>
                  {riskBadge(c.risk_score)}
                  <Badge variant="outline" className="text-xs">
                    {c.case_type}
                  </Badge>
                  <Badge variant="secondary" className="text-xs">
                    {c.our_role}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {c.case_number} &middot; {c.court}
                </p>
                {c.critical_date && (
                  <p className="text-xs flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    Critical: {c.critical_date}
                    {c.critical_note && (
                      <span className="text-muted-foreground ml-1">
                        — {c.critical_note}
                      </span>
                    )}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {c.live_ai_status ? (
                  <div className="text-right space-y-0.5">
                    <Badge
                      variant="outline"
                      className="bg-indigo-500/10 text-indigo-400 border-indigo-500/30 text-[11px] gap-1"
                    >
                      <Bot className="h-3 w-3" />
                      {c.live_ai_status}
                    </Badge>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                      {c.latest_action?.replace(/_/g, " ") ?? ""}
                      {c.last_ai_review && (
                        <span className="ml-1">
                          &middot; {new Date(c.last_ai_review).toLocaleDateString()}
                        </span>
                      )}
                    </p>
                  </div>
                ) : (
                  <Badge
                    variant="outline"
                    className="bg-muted/50 text-muted-foreground border-muted text-[10px]"
                  >
                    Awaiting AI Review
                  </Badge>
                )}
                <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" />
              </div>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  );
}
