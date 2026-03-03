"use client";

import { useMemo, useState } from "react";
import { Building2 } from "lucide-react";
import {
  useVrsArrivingToday,
  useVrsDashboardStats,
  useVrsDepartingToday,
  useVrsGuests,
  useVrsMessageStats,
  useVrsProperties,
  useVrsReservations,
} from "@/lib/hooks";
import { VrsKpiStrip } from "./vrs-kpi-strip";
import { VrsQuickLinksGrid } from "./vrs-quick-links-grid";
import { VrsArrivalsPanel } from "./vrs-arrivals-panel";
import { VrsDeparturesPanel } from "./vrs-departures-panel";
import { VrsMessagingStatsPanel } from "./vrs-messaging-stats-panel";
import { VrsReservationDetailSheet } from "./vrs-reservation-detail-sheet";
import { VrsDashboardPlusPanels } from "./vrs-dashboard-plus-panels";

export function VrsHubShell() {
  const [selectedReservationId, setSelectedReservationId] = useState<string | null>(null);

  const { data: properties, isLoading: propertiesLoading } = useVrsProperties();
  const { data: reservations, isLoading: reservationsLoading } = useVrsReservations();
  const { data: arrivals, isLoading: arrivalsLoading } = useVrsArrivingToday();
  const { data: departures, isLoading: departuresLoading } = useVrsDepartingToday();
  const { data: guests, isLoading: guestsLoading } = useVrsGuests();
  const { data: messageStats, isLoading: messageStatsLoading } = useVrsMessageStats();
  const { data: dashboardStats, isLoading: dashboardStatsLoading } = useVrsDashboardStats();

  const loading =
    propertiesLoading ||
    reservationsLoading ||
    arrivalsLoading ||
    departuresLoading ||
    guestsLoading ||
    messageStatsLoading ||
    dashboardStatsLoading;

  const lastUpdated = useMemo(() => new Date().toLocaleTimeString(), [
    properties?.length,
    reservations?.length,
    arrivals?.length,
    departures?.length,
    guests?.length,
    messageStats?.total_messages,
  ]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Building2 className="h-6 w-6 text-primary" />
            CROG-VRS
          </h1>
          <p className="text-muted-foreground">Vacation Rental Software hub for Cabin Rentals of Georgia.</p>
        </div>
        <div className="text-xs text-muted-foreground">
          {loading ? "Refreshing..." : `Updated ${lastUpdated}`}
        </div>
      </div>

      <VrsKpiStrip
        propertiesCount={dashboardStats?.total_properties ?? 0}
        reservationsCount={dashboardStats?.total_reservations ?? 0}
        arrivalsCount={dashboardStats?.arriving_today ?? 0}
        departuresCount={dashboardStats?.departing_today ?? 0}
        guestsCount={dashboardStats?.total_guests ?? 0}
        messagesCount={dashboardStats?.total_messages ?? 0}
        automationRate={messageStats?.automation_rate}
      />

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Quick Access</h2>
        <VrsQuickLinksGrid />
      </section>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <VrsArrivalsPanel
            reservations={arrivals}
            onOpenReservation={(id) => setSelectedReservationId(id)}
          />
          <VrsDeparturesPanel
            reservations={departures}
            onOpenReservation={(id) => setSelectedReservationId(id)}
          />
        </div>
        <VrsMessagingStatsPanel stats={messageStats} />
      </div>

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Operations Plus</h2>
        <VrsDashboardPlusPanels />
      </section>

      <VrsReservationDetailSheet
        open={!!selectedReservationId}
        reservationId={selectedReservationId}
        onOpenChange={(open) => !open && setSelectedReservationId(null)}
      />
    </div>
  );
}

