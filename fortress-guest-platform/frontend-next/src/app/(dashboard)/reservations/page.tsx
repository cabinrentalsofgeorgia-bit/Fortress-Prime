"use client";

import { useState } from "react";
import { useReservations, useProperties } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Search } from "lucide-react";
import { TapeChart } from "@/components/tape-chart";
import { FolioSheet } from "@/components/reservations/FolioSheet";
import type { Reservation } from "@/lib/types";

const statusColor: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  confirmed: "default",
  checked_in: "secondary",
  checked_out: "outline",
  cancelled: "destructive",
  no_show: "destructive",
  pending: "outline",
  on_hold: "outline",
  "on hold": "outline",
};

function normalizeStatus(status?: string | null): string {
  return String(status ?? "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "_");
}

function formatStatusLabel(status?: string | null): string {
  const normalized = normalizeStatus(status);
  if (!normalized) return "unknown";
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatMoney(amount?: number | null): string {
  if (amount == null || Number.isNaN(Number(amount))) return "–";
  return `$${Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function getGuestDisplayName(reservation: Reservation): string {
  const explicit = (reservation.guest_name ?? "").trim();
  if (explicit && explicit.toLowerCase() !== "none none") return explicit;
  const first = (reservation.guest?.first_name ?? "").trim();
  const last = (reservation.guest?.last_name ?? "").trim();
  const combined = `${first} ${last}`.trim();
  return combined || "Unknown Guest";
}

export default function ReservationsPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Reservation | null>(null);

  const { data: reservations, isLoading } = useReservations();
  const { data: properties } = useProperties();

  const propMap = new Map(properties?.map((p) => [p.id, p]) ?? []);

  const filtered = (reservations ?? [])
    .filter((r) => {
      if (statusFilter !== "all" && normalizeStatus(r.status) !== statusFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        const gName = getGuestDisplayName(r).toLowerCase();
        const pName = (r.property_name ?? propMap.get(r.property_id)?.name ?? "").toLowerCase();
        return (
          gName.includes(q) ||
          pName.includes(q) ||
          r.confirmation_code.toLowerCase().includes(q)
        );
      }
      return true;
    })
    .sort((a, b) => new Date(b.check_in_date).getTime() - new Date(a.check_in_date).getTime());

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Reservations</h1>
          <p className="text-muted-foreground">
            {reservations?.length ?? 0} total reservations
          </p>
        </div>
      </div>

      <Tabs defaultValue="list">
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="list">List View</TabsTrigger>
            <TabsTrigger value="calendar">Calendar</TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search guest, property, code..."
                className="w-64 pl-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="confirmed">Confirmed</SelectItem>
                <SelectItem value="checked_in">Checked In</SelectItem>
                <SelectItem value="checked_out">Checked Out</SelectItem>
                  <SelectItem value="on_hold">On Hold</SelectItem>
                  <SelectItem value="no_show">No Show</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <TabsContent value="list" className="mt-4">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Confirmation</TableHead>
                    <TableHead>Guest</TableHead>
                    <TableHead>Property</TableHead>
                    <TableHead>Check-in</TableHead>
                    <TableHead>Check-out</TableHead>
                    <TableHead>Guests</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Amount</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading ? (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                        Loading...
                      </TableCell>
                    </TableRow>
                  ) : filtered.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                        No reservations found
                      </TableCell>
                    </TableRow>
                  ) : (
                    filtered.slice(0, 50).map((r) => (
                      <TableRow
                        key={r.id}
                        className="cursor-pointer hover:bg-muted/50"
                        onClick={() => setSelected(r)}
                      >
                        <TableCell className="font-mono text-xs">
                          {r.confirmation_code}
                        </TableCell>
                        <TableCell>
                          <div>
                            <p className="text-sm font-medium">{getGuestDisplayName(r)}</p>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {r.property_name ?? propMap.get(r.property_id)?.name ?? "–"}
                        </TableCell>
                        <TableCell className="text-sm">{r.check_in_date}</TableCell>
                        <TableCell className="text-sm">{r.check_out_date}</TableCell>
                        <TableCell className="text-sm">{r.num_guests}</TableCell>
                        <TableCell>
                          <Badge variant={statusColor[normalizeStatus(r.status)] ?? "outline"}>
                            {formatStatusLabel(r.status)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm font-medium">
                          {formatMoney(r.total_amount)}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="calendar" className="mt-4">
          <TapeChart
            properties={properties ?? []}
            reservations={reservations ?? []}
            onSelectReservation={setSelected}
          />
        </TabsContent>
      </Tabs>

      <FolioSheet
        reservationId={selected?.id ?? null}
        open={!!selected}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </div>
  );
}
