"use client";

import Link from "next/link";
import { ArrowUpRight, Mail, Scale, ShieldAlert, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import type { BridgeStatusResponse, LegalOverviewResponse } from "@/lib/types";

interface CommandCenterServicesGridProps {
  bridge?: BridgeStatusResponse;
  legal?: LegalOverviewResponse;
}

const serviceCards = [
  {
    title: "Legal Command Center",
    description: "Cases, deadlines, evidence, and correspondence governance.",
    href: "/damage-claims",
    icon: Scale,
  },
  {
    title: "Email Intake",
    description: "Escalation queue, quarantine, and auto-routing controls.",
    href: "/email-intake",
    icon: Mail,
  },
  {
    title: "Mission Control",
    description: "Council interface for orchestration and strategic ops.",
    href: "/ai-engine",
    icon: Workflow,
  },
  {
    title: "System Health",
    description: "Cluster telemetry, services, and runtime health monitors.",
    href: "/system-health",
    icon: ShieldAlert,
  },
];

export function CommandCenterServicesGrid({ bridge, legal }: CommandCenterServicesGridProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {serviceCards.map((card) => (
        <Link key={card.title} href={card.href}>
          <Card className="h-full transition-colors hover:border-primary/30 hover:bg-accent/40">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <card.icon className="h-4 w-4 text-primary" />
                  {card.title}
                </CardTitle>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
              </div>
              <CardDescription>{card.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex gap-2">
              {card.title === "Legal Command Center" && (
                <Badge variant="outline">{legal?.total_cases ?? 0} cases</Badge>
              )}
              {card.title === "Email Intake" && (
                <Badge variant="outline">{bridge?.last_24h ?? "-"} last 24h</Badge>
              )}
            </CardContent>
            <CardFooter className="text-xs text-muted-foreground">
              Open service panel
            </CardFooter>
          </Card>
        </Link>
      ))}
    </div>
  );
}
