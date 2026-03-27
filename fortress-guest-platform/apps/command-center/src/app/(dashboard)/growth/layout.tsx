"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowRightLeft,
  Brain,
  FileSearch,
  FlaskConical,
  Megaphone,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

const GROWTH_TABS = [
  {
    label: "Migration Matrix",
    href: "/growth/migration",
    icon: ArrowRightLeft,
  },
  {
    label: "SEO Approval",
    href: "/growth/seo-approval",
    icon: FileSearch,
  },
  {
    label: "Redirect Remaps",
    href: "/growth/redirect-remaps",
    icon: ShieldAlert,
  },
  {
    label: "SEO Co-Pilot",
    href: "/growth/seo-copilot",
    icon: Brain,
  },
  {
    label: "A/B Edge Lab",
    href: "/growth/ab-testing",
    icon: FlaskConical,
  },
  {
    label: "SEM War Room",
    href: "/growth/sem-telemetry",
    icon: Megaphone,
  },
] as const;

export default function GrowthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-emerald-500" />
          Growth &amp; Intelligence Command Deck
        </h1>
        <p className="text-muted-foreground text-sm">
          Level 20 &mdash; SEO, SEM, A/B testing, and legacy migration control
        </p>
      </div>

      <nav className="flex items-center gap-1 rounded-lg bg-muted p-1">
        {GROWTH_TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-all",
                active
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground hover:bg-background/50"
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </Link>
          );
        })}
      </nav>

      {children}
    </div>
  );
}
