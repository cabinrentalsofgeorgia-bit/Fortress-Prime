"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useGuests } from "@/lib/hooks";
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
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { Search, Users, Phone, Mail, Calendar, MessageSquare, Star } from "lucide-react";
import type { Guest } from "@/lib/types";

function getGuestDisplayName(guest: Guest): string {
  const fullName = guest.full_name?.trim();
  if (fullName) return fullName;
  const combined = `${guest.first_name ?? ""} ${guest.last_name ?? ""}`.trim();
  return combined || "Guest";
}

function getGuestInitials(guest: Guest): string {
  const displayName = getGuestDisplayName(guest);
  const parts = displayName.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "G";
  if (parts.length === 1) return parts[0][0]?.toUpperCase() ?? "G";
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase() || "G";
}

export default function GuestsPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Guest | null>(null);
  const { data: guests, isLoading } = useGuests();

  const filtered = (guests ?? []).filter((g) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      getGuestDisplayName(g).toLowerCase().includes(q) ||
      (g.email ?? "").toLowerCase().includes(q) ||
      g.phone_number.includes(q)
    );
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Guest Hub</h1>
          <p className="text-muted-foreground">{guests?.length ?? 0} guests</p>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search name, email, phone..."
            className="w-72 pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Stays</TableHead>
                <TableHead>Last Stay</TableHead>
                <TableHead>Tags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    Loading...
                  </TableCell>
                </TableRow>
              ) : filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    No guests found
                  </TableCell>
                </TableRow>
              ) : (
                filtered.slice(0, 100).map((g) => (
                  <TableRow
                    key={g.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => router.push(`/guests/${g.id}`)}
                  >
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-medium">
                          {getGuestInitials(g)}
                        </div>
                        <p className="text-sm font-medium">
                          {getGuestDisplayName(g)}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{g.phone_number}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{g.email ?? "–"}</TableCell>
                    <TableCell className="text-sm">{g.total_stays}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {g.last_stay_date ?? "–"}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        {(g.tags ?? []).map((t) => (
                          <Badge key={t} variant="outline" className="text-[10px]">
                            {t}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Sheet open={!!selected} onOpenChange={() => setSelected(null)}>
        <SheetContent className="w-[480px] sm:max-w-[480px]">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle>
                  {getGuestDisplayName(selected)}
                </SheetTitle>
              </SheetHeader>
              <div className="mt-6 space-y-6">
                <div className="flex items-center gap-4">
                  <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-lg font-semibold">
                    {getGuestInitials(selected)}
                  </div>
                  <div>
                    <p className="text-lg font-semibold">
                      {getGuestDisplayName(selected)}
                    </p>
                    <div className="flex gap-1 mt-1">
                      {(selected.tags ?? []).map((t) => (
                        <Badge key={t} variant="secondary" className="text-xs">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>

                <Separator />

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border p-3">
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Phone className="h-3 w-3" />
                      Phone
                    </p>
                    <p className="text-sm font-medium mt-1">{selected.phone_number}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Mail className="h-3 w-3" />
                      Email
                    </p>
                    <p className="text-sm font-medium mt-1">{selected.email ?? "–"}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Star className="h-3 w-3" />
                      Total Stays
                    </p>
                    <p className="text-sm font-medium mt-1">{selected.total_stays}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Calendar className="h-3 w-3" />
                      Last Stay
                    </p>
                    <p className="text-sm font-medium mt-1">{selected.last_stay_date ?? "–"}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <MessageSquare className="h-3 w-3" />
                      Messages Sent
                    </p>
                    <p className="text-sm font-medium mt-1">{selected.total_messages_sent ?? 0}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Users className="h-3 w-3" />
                      Language
                    </p>
                    <p className="text-sm font-medium mt-1">{selected.language_preference}</p>
                  </div>
                </div>

                <Separator />

                <div className="space-y-2">
                  <h3 className="text-sm font-semibold">Preferences</h3>
                  <div className="flex gap-3">
                    <Badge variant={selected.opt_in_marketing ? "default" : "outline"}>
                      {selected.opt_in_marketing ? "Marketing Opt-In" : "Marketing Opt-Out"}
                    </Badge>
                    <Badge variant="outline">
                      Prefers {selected.preferred_contact_method ?? "sms"}
                    </Badge>
                  </div>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
