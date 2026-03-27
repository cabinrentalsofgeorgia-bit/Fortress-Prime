"use client";

import Link from "next/link";
import { useVrsReservationFull } from "@/lib/hooks";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  CalendarDays,
  User,
  DollarSign,
  Building2,
  ExternalLink,
} from "lucide-react";

interface Props {
  open: boolean;
  reservationId: string | null;
  onOpenChange: (open: boolean) => void;
}

export function VrsReservationDetailSheet({
  open,
  reservationId,
  onOpenChange,
}: Props) {
  const { data, isLoading } = useVrsReservationFull(reservationId ?? undefined);

  const r: Record<string, unknown> | undefined =
    data && "reservation" in data
      ? (data as unknown as { reservation: Record<string, unknown> }).reservation
      : (data as unknown as Record<string, unknown> | undefined);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Reservation Detail</SheetTitle>
        </SheetHeader>

        {isLoading && (
          <div className="space-y-3 mt-4">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {r && !isLoading && (
          <div className="space-y-4 mt-4">
            <div className="flex items-center justify-between">
              <Badge variant="outline">
                {String((r as Record<string, unknown>).confirmation_code ?? (r as Record<string, unknown>).id)}
              </Badge>
              <Badge
                variant={
                  (r as Record<string, unknown>).status === "confirmed"
                    ? "secondary"
                    : "outline"
                }
              >
                {String((r as Record<string, unknown>).status ?? "—")}
              </Badge>
            </div>

            <Separator />

            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <User className="h-4 w-4 text-muted-foreground" />
                <span>
                  {String((r as Record<string, unknown>).guest_name ?? "—")}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Building2 className="h-4 w-4 text-muted-foreground" />
                <span>
                  {String((r as Record<string, unknown>).property_name ?? "—")}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <CalendarDays className="h-4 w-4 text-muted-foreground" />
                <span>
                  {String((r as Record<string, unknown>).check_in_date ?? "—")} →{" "}
                  {String((r as Record<string, unknown>).check_out_date ?? "—")}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <DollarSign className="h-4 w-4 text-muted-foreground" />
                <span>
                  ${Number((r as Record<string, unknown>).total_amount ?? 0).toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                  })}
                </span>
              </div>
            </div>

            {reservationId && (
              <>
                <Separator />
                <Link href={`/reservations`}>
                  <Button className="w-full gap-2" variant="outline">
                    Open Full Reservation
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </Link>
              </>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
