"use client";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Wrench } from "lucide-react";
import type { WorkOrder } from "@/lib/types";

const priorityColor: Record<string, string> = {
  urgent: "destructive",
  high: "destructive",
  medium: "default",
  low: "secondary",
};

interface Props {
  workOrders?: WorkOrder[];
}

export function WorkOrdersCard({ workOrders }: Props) {
  const items = (workOrders ?? []).slice(0, 5);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <Wrench className="h-5 w-5 text-orange-500" />
          Open Work Orders
        </CardTitle>
        <Badge variant="secondary">{workOrders?.length ?? 0}</Badge>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            No open work orders
          </p>
        ) : (
          <div className="space-y-3">
            {items.map((wo) => (
              <div
                key={wo.id}
                className="flex items-center justify-between rounded-lg border p-3"
              >
                <div className="space-y-1">
                  <p className="text-sm font-medium">{wo.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {wo.property?.name ?? wo.ticket_number}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Badge
                    variant={
                      (priorityColor[wo.priority] as "destructive" | "default" | "secondary") ??
                      "secondary"
                    }
                    className="text-[10px]"
                  >
                    {wo.priority}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {wo.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
