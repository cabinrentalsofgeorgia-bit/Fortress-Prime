"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";

const QUICK_LINKS = [
  { href: "/properties", label: "Properties", sub: "Manage all cabins", icon: "🏠" },
  { href: "/reservations", label: "Reservations", sub: "Calendar & bookings", icon: "📅" },
  { href: "/guests", label: "Guest CRM", sub: "360° guest profiles", icon: "👤" },
  { href: "/housekeeping", label: "Housekeeping", sub: "Turnovers & dispatch", icon: "🧹" },
  { href: "/messages", label: "Messages", sub: "AI communication", icon: "💬" },
  { href: "/work-orders", label: "Work Orders", sub: "Maintenance & repairs", icon: "🔧" },
  { href: "/damage-claims", label: "Damage Claims", sub: "Post-stay inspections", icon: "🚨" },
  { href: "/agreements", label: "Agreements", sub: "E-sign agreements", icon: "📝" },
  { href: "/analytics", label: "Analytics", sub: "Revenue & performance", icon: "📈" },
];

export function VrsQuickLinksGrid() {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {QUICK_LINKS.map((link) => (
        <Link key={link.href} href={link.href}>
          <Card className="h-full transition-colors hover:border-primary/30 hover:bg-accent/50">
            <CardContent className="pt-4">
              <p className="text-xl">{link.icon}</p>
              <p className="text-sm font-semibold mt-2">{link.label}</p>
              <p className="text-xs text-muted-foreground mt-1">{link.sub}</p>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  );
}

