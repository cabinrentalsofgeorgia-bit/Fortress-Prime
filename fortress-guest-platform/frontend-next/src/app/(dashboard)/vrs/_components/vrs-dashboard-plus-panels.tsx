"use client";

import { useDashboardStats, useReviewQueue, useWorkOrders } from "@/lib/hooks";
import { ReviewQueueCard } from "../../_components/review-queue-card";
import { WorkOrdersCard } from "../../_components/work-orders-card";
import { OccupancyCard } from "../../_components/occupancy-card";

export function VrsDashboardPlusPanels() {
  const { data: stats } = useDashboardStats();
  const { data: reviewQueue } = useReviewQueue();
  const { data: workOrders } = useWorkOrders({ status: "open" });

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <ReviewQueueCard items={reviewQueue} />
      <WorkOrdersCard workOrders={workOrders} />
      <OccupancyCard stats={stats} />
    </div>
  );
}

