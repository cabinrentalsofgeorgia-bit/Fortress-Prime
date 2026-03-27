"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";

type Props = {
  propertiesCount: number;
  reservationsCount: number;
  arrivalsCount: number;
  departuresCount: number;
  guestsCount: number;
  messagesCount: number;
  automationRate?: number;
};

export function VrsKpiStrip({
  propertiesCount,
  reservationsCount,
  arrivalsCount,
  departuresCount,
  guestsCount,
  messagesCount,
  automationRate,
}: Props) {
  const cards = [
    { href: "/properties", label: "Properties", value: propertiesCount, sub: `${propertiesCount} active cabins` },
    { href: "/reservations", label: "Reservations", value: reservationsCount, sub: "Total bookings" },
    { href: "#arrivals-section", label: "Arrivals Today", value: arrivalsCount, sub: "Check-ins pending" },
    { href: "#departures-section", label: "Departures Today", value: departuresCount, sub: "Check-outs due" },
    { href: "/guests", label: "Total Guests", value: guestsCount, sub: `${guestsCount} in CRM` },
    {
      href: "/messages",
      label: "Messages",
      value: messagesCount,
      sub: `${Math.round(automationRate ?? 0)}% automated`,
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
      {cards.map((card) => {
        const content = (
          <Card className="h-full transition-colors hover:border-primary/30 hover:bg-accent/50">
            <CardContent className="pt-4">
              <p className="text-2xl font-bold">{card.value.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">{card.label}</p>
              <p className="text-[11px] text-muted-foreground mt-1">{card.sub}</p>
            </CardContent>
          </Card>
        );
        return card.href.startsWith("#") ? (
          <a key={card.label} href={card.href}>
            {content}
          </a>
        ) : (
          <Link key={card.label} href={card.href}>
            {content}
          </Link>
        );
      })}
    </div>
  );
}

