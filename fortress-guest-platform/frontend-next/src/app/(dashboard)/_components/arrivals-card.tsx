"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CalendarCheck,
  Users,
  Phone,
  Mail,
  MapPin,
  ChevronRight,
  DollarSign,
  MessageSquare,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import type { Reservation } from "@/lib/types";

interface Props {
  reservations?: Reservation[];
}

export function ArrivalsCard({ reservations }: Props) {
  const items = reservations ?? [];
  const [selected, setSelected] = useState<Reservation | null>(null);

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <CalendarCheck className="h-5 w-5 text-green-500" />
            Arriving Today
          </CardTitle>
          <Badge variant="secondary">{items.length}</Badge>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No arrivals today
            </p>
          ) : (
            <div className="space-y-2">
              {items.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setSelected(r)}
                  className="flex w-full items-center justify-between rounded-lg border p-3 text-left transition-colors hover:bg-accent hover:border-primary/30 group"
                >
                  <div className="space-y-1 min-w-0">
                    <p className="text-sm font-medium truncate">
                      {r.guest_name ?? `${r.guest?.first_name ?? ""} ${r.guest?.last_name ?? ""}`}
                    </p>
                    <p className="text-xs text-muted-foreground truncate">
                      {r.property_name ?? r.property?.name ?? "Unknown Property"}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <div className="flex flex-col items-end gap-1">
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Users className="h-3 w-3" />
                        {r.num_guests}
                      </div>
                      <div className="flex gap-1">
                        {r.pre_arrival_sent && (
                          <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600 border-green-500/30">
                            Pre-arrival
                          </Badge>
                        )}
                        {r.access_info_sent && (
                          <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-600 border-blue-500/30">
                            Access
                          </Badge>
                        )}
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Sheet open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          {selected && <ArrivalDetail reservation={selected} />}
        </SheetContent>
      </Sheet>
    </>
  );
}

function ArrivalDetail({ reservation: r }: { reservation: Reservation }) {
  const guestName = r.guest_name ?? `${r.guest?.first_name ?? ""} ${r.guest?.last_name ?? ""}`;
  const propertyName = r.property_name ?? r.property?.name ?? "Unknown Property";
  const phone = r.guest_phone ?? r.guest?.phone_number;
  const email = r.guest_email ?? r.guest?.email;

  const nights = r.nights_count ?? r.nights ?? 0;
  const checklistItems = [
    { label: "Pre-arrival message sent", done: r.pre_arrival_sent },
    { label: "Access info sent", done: r.access_info_sent },
    { label: "Digital guidebook sent", done: r.digital_guide_sent },
  ];
  const allReady = checklistItems.every((c) => c.done);

  return (
    <div className="space-y-6">
      <SheetHeader>
        <div className="flex items-center gap-2">
          <div className={`h-3 w-3 rounded-full ${allReady ? "bg-green-500" : "bg-amber-500"} animate-pulse`} />
          <SheetTitle className="text-lg">Arrival Detail</SheetTitle>
        </div>
      </SheetHeader>

      {/* Guest Info */}
      <div className="rounded-lg border p-4 space-y-3">
        <h3 className="font-semibold text-base">{guestName}</h3>
        <div className="grid gap-2 text-sm">
          {phone && (
            <a href={`tel:${phone}`} className="flex items-center gap-2 text-muted-foreground hover:text-primary transition-colors">
              <Phone className="h-4 w-4" /> {phone}
            </a>
          )}
          {email && (
            <a href={`mailto:${email}`} className="flex items-center gap-2 text-muted-foreground hover:text-primary transition-colors">
              <Mail className="h-4 w-4" /> {email}
            </a>
          )}
          <div className="flex items-center gap-2 text-muted-foreground">
            <Users className="h-4 w-4" /> {r.num_guests} guests
            {r.num_adults && <span>({r.num_adults} adults{r.num_children ? `, ${r.num_children} children` : ""})</span>}
          </div>
        </div>
      </div>

      {/* Property & Stay */}
      <div className="rounded-lg border p-4 space-y-3">
        <div className="flex items-center gap-2">
          <MapPin className="h-4 w-4 text-primary" />
          <h3 className="font-semibold">{propertyName}</h3>
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-muted-foreground text-xs">Check-in</p>
            <p className="font-medium">{r.check_in_date}</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Check-out</p>
            <p className="font-medium">{r.check_out_date}</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Nights</p>
            <p className="font-medium">{nights}</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">Confirmation</p>
            <p className="font-medium">{r.confirmation_code}</p>
          </div>
        </div>
        {r.special_requests && (
          <div className="pt-2 border-t">
            <p className="text-xs text-muted-foreground mb-1">Special Requests</p>
            <p className="text-sm bg-amber-500/10 rounded p-2 text-amber-700 dark:text-amber-300">{r.special_requests}</p>
          </div>
        )}
        {r.access_code && (
          <div className="pt-2 border-t">
            <p className="text-xs text-muted-foreground mb-1">Access Code</p>
            <p className="text-sm font-mono font-bold tracking-widest bg-muted rounded p-2 text-center">{r.access_code}</p>
          </div>
        )}
      </div>

      {/* Financial Summary */}
      {(r.total_amount ?? 0) > 0 && (
        <div className="rounded-lg border p-4 space-y-2">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="h-4 w-4 text-green-600" />
            <h3 className="font-semibold">Payment</h3>
          </div>
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Total</p>
              <p className="font-medium">${r.total_amount?.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Paid</p>
              <p className="font-medium text-green-600">${(r.paid_amount ?? 0).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Balance</p>
              <p className={`font-medium ${(r.balance_due ?? 0) > 0 ? "text-red-500" : "text-green-600"}`}>
                ${(r.balance_due ?? 0).toLocaleString()}
              </p>
            </div>
          </div>
          {(r.balance_due ?? 0) > 0 && (
            <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-500/10 rounded p-2 mt-2">
              <AlertCircle className="h-3.5 w-3.5" />
              Balance due at check-in
            </div>
          )}
        </div>
      )}

      {/* Readiness Checklist */}
      <div className="rounded-lg border p-4 space-y-3">
        <h3 className="font-semibold flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          Arrival Readiness
        </h3>
        <div className="space-y-2">
          {checklistItems.map((item) => (
            <div key={item.label} className="flex items-center gap-2 text-sm">
              {item.done ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30" />
              )}
              <span className={item.done ? "text-muted-foreground" : "font-medium"}>{item.label}</span>
            </div>
          ))}
        </div>
        {!allReady && (
          <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-500/10 rounded p-2">
            <AlertCircle className="h-3.5 w-3.5" />
            Guest has not received all pre-arrival communications
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="flex flex-col gap-2">
        <Link href={`/reservations?highlight=${r.id}`}>
          <Button className="w-full" variant="default">
            Open Full Reservation
          </Button>
        </Link>
        {phone && (
          <a href={`sms:${phone}`}>
            <Button className="w-full" variant="outline">
              <MessageSquare className="h-4 w-4 mr-2" />
              Send Text to Guest
            </Button>
          </a>
        )}
      </div>
    </div>
  );
}
