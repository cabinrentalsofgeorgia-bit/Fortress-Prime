"use client";

import Link from "next/link";
import { Scale, ChevronRight, Clock } from "lucide-react";
import { useLegalCases } from "@/lib/legal-hooks";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { LegalCase } from "@/lib/legal-types";

function riskBadge(score: number | null) {
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

export function LegalCasesShell() {
  const { data, isLoading, error } = useLegalCases();

  if (error) {
    return (
      <div className="p-6">
        <p className="text-destructive text-sm">
          Failed to load legal cases: {error.message}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Scale className="h-6 w-6 text-primary" />
            Legal Command Center
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Active litigation, deadlines, and AI extraction intelligence.
          </p>
        </div>
        <Link
          href="/legal/council"
          className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 transition-colors"
        >
          Council of 9
          <ChevronRight className="h-4 w-4" />
        </Link>
      </div>

      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-lg" />
          ))}
        </div>
      )}

      {data?.cases && data.cases.length === 0 && (
        <p className="text-muted-foreground text-sm py-8 text-center">
          No legal cases registered.
        </p>
      )}

      <div className="space-y-3">
        {data?.cases?.map((c: LegalCase) => (
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
                <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" />
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
