"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Reservation } from "@/lib/types";

type Props = {
  reservations?: Reservation[];
  onOpenReservation: (reservationId: string) => void;
};

export function VrsArrivalsPanel({ reservations, onOpenReservation }: Props) {
  const items = reservations ?? [];

  return (
    <Card id="arrivals-section">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Arriving Today</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{items.length}</Badge>
          <Link href="/reservations?filter=arriving" className="text-xs text-primary hover:underline">
            View all
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">No arrivals today</p>
        ) : (
          items.map((res) => (
            <button
              key={res.id}
              className="w-full rounded-md border p-3 text-left transition-colors hover:bg-accent"
              onClick={() => onOpenReservation(res.id)}
            >
              <p className="text-sm font-medium">{res.property_name || "Property"}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {res.num_guests ?? "-"} guests • {res.guest_name || "Guest"} • {res.check_in_date} → {res.check_out_date}
              </p>
            </button>
          ))
        )}
      </CardContent>
    </Card>
  );
}

