import Link from "next/link";
import { ArrowRight, Gauge, Scale, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const statusCards = [
  {
    label: "Fortress Legal",
    value: "NOT_READY",
    detail: "Legal/operator decisions remain pending; fail-closed readiness is expected.",
  },
  {
    label: "Backend Safety",
    value: "PASS",
    detail: "Dry-run, reconciliation, and privilege gates remain constrained.",
  },
  {
    label: "Production",
    value: "BLOCKED",
    detail: "Production certification stays separate from staging UI verification.",
  },
];

export default function DashboardPage() {
  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <Gauge className="h-5 w-5 text-cyan-400" />
            <Badge variant="outline" className="border-cyan-500/30 bg-cyan-500/10 text-cyan-200">
              Staging command surface
            </Badge>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Command Dashboard</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Read-only operational view for authenticated staging certification.
          </p>
        </div>
        <Link
          href="/legal"
          className="inline-flex items-center gap-2 rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-cyan-700"
        >
          Open Fortress Legal
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {statusCards.map((card) => (
          <Card key={card.label} className="border-border bg-card">
            <CardHeader className="space-y-1">
              <CardDescription>{card.label}</CardDescription>
              <CardTitle className="text-xl">{card.value}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{card.detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-amber-500/30 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-5 w-5 text-amber-300" />
            Legal Readiness Boundary
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Fortress Legal is intentionally constrained: no evidence ingest, promotion,
            privilege clearance, DB writes, Qdrant writes, or NAS changes are part of this UI surface.
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">Readiness: NOT_READY</Badge>
            <Badge variant="secondary">Backend safety: PASS</Badge>
            <Badge variant="secondary">Production: BLOCKED</Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Scale className="h-5 w-5 text-primary" />
            Fortress Legal Entry
          </CardTitle>
          <CardDescription>
            Review active dockets and the current fail-closed legal status.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/legal" className="text-sm font-medium text-primary hover:underline">
            Go to Legal Command Center
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
