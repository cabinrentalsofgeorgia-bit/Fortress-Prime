"use client";

import { useEffect, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  useGuest,
  useGuestActivity,
  useReservations,
  useMessagesByPhone,
  useStranglerCurrentReservation,
  useStranglerReservationHistory,
} from "@/lib/hooks";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  ArrowLeft,
  Phone,
  Mail,
  CalendarDays,
  MessageSquare,
  Star,
  Home,
  DollarSign,
  User,
  Bot,
  Clock,
} from "lucide-react";
import { DetailSkeleton } from "@/components/skeletons";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";

export default function Guest360Page() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: guest, isLoading } = useGuest(id);
  const { data: activity } = useGuestActivity(id);
  const { data: allReservations } = useReservations();
  const { data: messages } = useMessagesByPhone(guest?.phone_number ?? "");
  const {
    data: currentFromStrangler,
    error: currentStranglerError,
  } = useStranglerCurrentReservation(guest?.phone_number ?? "");
  const {
    data: historyFromStrangler,
    error: historyStranglerError,
    isFetching: isHistoryFetching,
  } = useStranglerReservationHistory(guest?.phone_number ?? "", 5);

  const guestReservations = useMemo(() => {
    const local = (allReservations ?? []).filter((r) => r.guest_id === id);
    const merged = [...local];
    if (currentFromStrangler) merged.push(currentFromStrangler);
    if (Array.isArray(historyFromStrangler)) merged.push(...historyFromStrangler);

    const uniqueByConfirmation = new Map<string, (typeof merged)[number]>();
    for (const reservation of merged) {
      const key = reservation.confirmation_code || reservation.id;
      if (!key) continue;
      if (!uniqueByConfirmation.has(key)) {
        uniqueByConfirmation.set(key, reservation);
      }
    }
    return Array.from(uniqueByConfirmation.values()).sort(
      (a, b) => new Date(b.check_in_date).getTime() - new Date(a.check_in_date).getTime(),
    );
  }, [allReservations, id, currentFromStrangler, historyFromStrangler]);

  const isThrottled =
    (historyStranglerError instanceof ApiError && historyStranglerError.status === 429) ||
    (currentStranglerError instanceof ApiError && currentStranglerError.status === 429);

  useEffect(() => {
    if (isThrottled) {
      toast.warning("Sync Throttled: Retrying...");
    }
  }, [isThrottled]);

  if (isLoading) return <DetailSkeleton />;
  if (!guest) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <p>Guest not found</p>
        <Button variant="link" onClick={() => router.push("/guests")}>Back to Guests</Button>
      </div>
    );
  }

  const initials = `${guest.first_name?.[0] ?? ""}${guest.last_name?.[0] ?? ""}`.toUpperCase();
  const totalSpent = guestReservations.reduce((s, r) => s + (r.total_amount ?? 0), 0);

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" onClick={() => router.push("/guests")}>
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back to Guests
      </Button>

      {/* Profile header */}
      <div className="flex items-start gap-4">
        <Avatar className="h-16 w-16">
          <AvatarFallback className="text-xl">{initials}</AvatarFallback>
        </Avatar>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">{guest.first_name} {guest.last_name}</h1>
            {guest.total_stays > 2 && <Badge className="bg-amber-500">VIP</Badge>}
          </div>
          <div className="flex items-center gap-4 text-sm text-muted-foreground mt-1 flex-wrap">
            {guest.phone_number && (
              <span className="flex items-center gap-1"><Phone className="h-3.5 w-3.5" />{guest.phone_number}</span>
            )}
            {guest.email && (
              <span className="flex items-center gap-1"><Mail className="h-3.5 w-3.5" />{guest.email}</span>
            )}
            <span className="flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" />{guest.total_stays} stays</span>
            {guest.language_preference && guest.language_preference !== "en" && (
              <Badge variant="outline" className="text-xs">{guest.language_preference}</Badge>
            )}
          </div>
        </div>
      </div>

      {/* Quick stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <CalendarDays className="h-8 w-8 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">{guest.total_stays}</p>
              <p className="text-xs text-muted-foreground">Total Stays</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <DollarSign className="h-8 w-8 text-green-500" />
            <div>
              <p className="text-2xl font-bold">${totalSpent.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">Lifetime Value</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <MessageSquare className="h-8 w-8 text-violet-500" />
            <div>
              <p className="text-2xl font-bold">{messages?.length ?? 0}</p>
              <p className="text-xs text-muted-foreground">Messages</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Star className="h-8 w-8 text-amber-500" />
            <div>
              <p className="text-2xl font-bold">
                {guest.last_stay_date ? new Date(guest.last_stay_date).toLocaleDateString("en-US", { month: "short", year: "numeric" }) : "—"}
              </p>
              <p className="text-xs text-muted-foreground">Last Stay</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {isThrottled && (
        <div className="rounded-md border border-yellow-400/30 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-300">
          Sync Throttled: Retrying...
        </div>
      )}

      {/* Tabs */}
      <Tabs defaultValue="timeline">
        <TabsList>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
            <TabsTrigger value="reservations">
            Reservations
            <Badge variant="secondary" className="ml-1.5 text-[10px]">{guestReservations.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="communication">
            Messages
            <Badge variant="secondary" className="ml-1.5 text-[10px]">{messages?.length ?? 0}</Badge>
          </TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
        </TabsList>

        <TabsContent value="timeline" className="mt-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">Activity Timeline</CardTitle></CardHeader>
            <CardContent>
              {Array.isArray(activity) && activity.length > 0 ? (
                <div className="space-y-4">
                  {(activity as Array<{ type: string; description: string; timestamp: string }>).slice(0, 30).map((a, i) => (
                    <div key={i} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <div className={cn(
                          "h-8 w-8 rounded-full flex items-center justify-center text-white",
                          a.type === "reservation" ? "bg-blue-500" :
                          a.type === "message" ? "bg-violet-500" :
                          a.type === "review" ? "bg-amber-500" : "bg-slate-500",
                        )}>
                          {a.type === "reservation" ? <CalendarDays className="h-4 w-4" /> :
                           a.type === "message" ? <MessageSquare className="h-4 w-4" /> :
                           <Star className="h-4 w-4" />}
                        </div>
                        {i < (activity as unknown[]).length - 1 && <div className="w-px flex-1 bg-border mt-1" />}
                      </div>
                      <div className="flex-1 pb-4">
                        <p className="text-sm">{a.description}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {new Date(a.timestamp).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-4">
                  {guestReservations.map((r) => (
                    <div key={r.id} className="flex gap-3">
                      <div className="h-8 w-8 rounded-full bg-blue-500 flex items-center justify-center text-white shrink-0">
                        <CalendarDays className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-sm">
                          <span className="font-medium">{r.property_name ?? "Property"}</span>
                          {" — "}{r.check_in_date} to {r.check_out_date}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {r.status.replace("_", " ")} · {r.confirmation_code}
                          {r.total_amount ? ` · $${r.total_amount.toLocaleString()}` : ""}
                        </p>
                      </div>
                    </div>
                  ))}
                  {guestReservations.length === 0 && !isHistoryFetching && (
                    <p className="text-sm text-muted-foreground text-center py-4">No activity yet</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reservations" className="mt-4">
          <div className="space-y-3">
            {guestReservations.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-muted-foreground">
                  No reservations found for this guest
                </CardContent>
              </Card>
            ) : (
              guestReservations.map((r) => (
                <Card key={r.id} className="cursor-pointer hover:bg-accent/50 transition-colors" onClick={() => router.push("/reservations")}>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="space-y-1">
                        <p className="font-medium flex items-center gap-2">
                          <Home className="h-4 w-4 text-muted-foreground" />
                          {r.property_name ?? "Property"}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          {r.check_in_date} → {r.check_out_date} · {r.num_guests} guests
                        </p>
                      </div>
                      <div className="text-right">
                        <Badge variant={
                          r.status === "checked_in" ? "default" :
                          r.status === "confirmed" ? "secondary" :
                          r.status === "cancelled" ? "destructive" : "outline"
                        }>
                          {r.status.replace("_", " ")}
                        </Badge>
                        {r.total_amount && (
                          <p className="text-sm font-medium mt-1">${r.total_amount.toLocaleString()}</p>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </TabsContent>

        <TabsContent value="communication" className="mt-4">
          <Card>
            <CardContent className="p-4">
              <ScrollArea className="h-[500px]">
                <div className="space-y-3">
                  {[...(messages ?? [])].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()).map((msg) => (
                    <div
                      key={msg.id}
                      className={cn(
                        "flex gap-2 max-w-[80%]",
                        msg.direction === "outbound" ? "ml-auto flex-row-reverse" : "",
                      )}
                    >
                      <Avatar className="h-7 w-7 shrink-0">
                        <AvatarFallback className="text-[10px]">
                          {msg.direction === "inbound" ? <User className="h-3 w-3" /> :
                           msg.is_auto_response ? <Bot className="h-3 w-3" /> : "LK"}
                        </AvatarFallback>
                      </Avatar>
                      <div className={cn(
                        "rounded-lg px-3 py-2 text-sm",
                        msg.direction === "outbound"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted",
                      )}>
                        <p>{msg.body}</p>
                        <p className="text-[10px] opacity-60 mt-1">
                          {new Date(msg.created_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  ))}
                  {(!messages || messages.length === 0) && (
                    <p className="text-center py-8 text-muted-foreground text-sm">No messages yet</p>
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="preferences" className="mt-4">
          <Card>
            <CardContent className="p-4 space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Language</p>
                  <p className="text-sm font-medium">{guest.language_preference || "English"}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Contact Method</p>
                  <p className="text-sm font-medium">{guest.preferred_contact_method || "SMS"}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Marketing Opt-in</p>
                  <p className="text-sm font-medium">{guest.opt_in_marketing ? "Yes" : "No"}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Member Since</p>
                  <p className="text-sm font-medium">{new Date(guest.created_at).toLocaleDateString()}</p>
                </div>
              </div>

              {guest.tags && guest.tags.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-2">Tags</p>
                  <div className="flex flex-wrap gap-1.5">
                    {guest.tags.map((t) => (
                      <Badge key={t} variant="secondary">{t}</Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
