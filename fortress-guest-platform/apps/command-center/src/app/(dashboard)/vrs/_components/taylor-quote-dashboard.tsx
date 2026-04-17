"use client";

import { useState } from "react";
import {
  BedDouble,
  CheckCircle2,
  Clock,
  Loader2,
  Mail,
  SendHorizonal,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  useApproveTaylorQuote,
  useCreateTaylorQuoteRequest,
  useTaylorPendingQuotes,
  type TaylorPropertyOption,
  type TaylorQuoteRequestRecord,
} from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function formatCurrency(amount: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

function formatDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ─── Property Option Card ─────────────────────────────────────────────────────

function PropertyOptionCard({ opt }: { opt: TaylorPropertyOption }) {
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      {opt.hero_image_url && (
        <img
          src={opt.hero_image_url}
          alt={opt.property_name}
          className="w-full h-36 object-cover"
        />
      )}
      <div className="p-3 space-y-2">
        <p className="font-semibold text-sm leading-tight">{opt.property_name}</p>
        <p className="text-xs text-muted-foreground flex items-center gap-1">
          <BedDouble className="h-3 w-3" />
          {opt.bedrooms} bed · {opt.bathrooms} bath · {opt.max_guests} guests max
        </p>
        <div className="text-xs space-y-0.5 border-t pt-2">
          <div className="flex justify-between text-muted-foreground">
            <span>Base rent</span><span>{formatCurrency(opt.base_rent)}</span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Fees</span><span>{formatCurrency(opt.fees)}</span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Taxes</span><span>{formatCurrency(opt.taxes)}</span>
          </div>
          <div className="flex justify-between font-semibold text-foreground border-t pt-1 mt-1">
            <span>Total</span><span>{formatCurrency(opt.total_amount)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Pending Quote Row ────────────────────────────────────────────────────────

function PendingQuoteRow({ record }: { record: TaylorQuoteRequestRecord }) {
  const [expanded, setExpanded] = useState(false);
  const approve = useApproveTaylorQuote();

  const isSent = record.status === "sent";
  const guestLabel = [
    `${record.adults} adult${record.adults !== 1 ? "s" : ""}`,
    record.children ? `${record.children} child${record.children !== 1 ? "ren" : ""}` : null,
    record.pets ? `${record.pets} pet${record.pets !== 1 ? "s" : ""}` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className={`rounded-xl border ${isSent ? "bg-muted/20 border-border/50" : "bg-card"}`}>
      <div className="p-4 flex items-start gap-4">
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">{record.guest_email}</span>
            <Badge variant={isSent ? "secondary" : "outline"} className="text-[11px]">
              {isSent ? (
                <><CheckCircle2 className="h-3 w-3 mr-1" />Sent</>
              ) : (
                <><Clock className="h-3 w-3 mr-1" />Pending</>
              )}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            {formatDate(record.check_in)} → {formatDate(record.check_out)}
            {" · "}{record.nights} night{record.nights !== 1 ? "s" : ""}
            {" · "}{guestLabel}
          </p>
          <p className="text-xs text-muted-foreground">
            {record.available_property_count} cabin{record.available_property_count !== 1 ? "s" : ""} available
            {" · "}{relativeTime(record.created_at)}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Collapse" : "Preview"}
          </Button>
          {!isSent && (
            <Button
              size="sm"
              disabled={approve.isPending || record.available_property_count === 0}
              onClick={() => approve.mutate({ requestId: record.id })}
            >
              {approve.isPending ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" />Sending...</>
              ) : (
                <><SendHorizonal className="h-3.5 w-3.5" />Approve &amp; Send</>
              )}
            </Button>
          )}
          {isSent && record.approved_by && (
            <span className="text-xs text-muted-foreground">by {record.approved_by}</span>
          )}
        </div>
      </div>

      {expanded && record.property_options.length > 0 && (
        <div className="px-4 pb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 border-t pt-4">
          {record.property_options.map((opt) => (
            <PropertyOptionCard key={opt.property_id} opt={opt} />
          ))}
        </div>
      )}

      {expanded && record.property_options.length === 0 && (
        <p className="px-4 pb-4 text-sm text-muted-foreground">
          No available properties were found for these dates.
        </p>
      )}
    </div>
  );
}

// ─── New Quote Request Form ───────────────────────────────────────────────────

function buildDefaultDate(daysFromNow: number) {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString().slice(0, 10);
}

function QuoteRequestForm() {
  const [email, setEmail] = useState("");
  const [checkIn, setCheckIn] = useState(buildDefaultDate(30));
  const [checkOut, setCheckOut] = useState(buildDefaultDate(35));
  const [adults, setAdults] = useState("2");
  const [children, setChildren] = useState("0");
  const [pets, setPets] = useState("0");

  const create = useCreateTaylorQuoteRequest();

  const canSubmit =
    email.trim() &&
    checkIn &&
    checkOut &&
    checkOut > checkIn &&
    Number(adults) >= 1 &&
    !create.isPending;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      await create.mutateAsync({
        guest_email: email.trim(),
        check_in: checkIn,
        check_out: checkOut,
        adults: Number(adults),
        children: Number(children),
        pets: Number(pets),
      });
      // Keep form values — Taylor may send multiple quotes
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Request failed";
      toast.error(message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Mail className="h-4 w-4 text-primary" />
          New Quote Request
        </CardTitle>
        <CardDescription>
          Enter the guest&apos;s dates, party size, and email. The system will check all
          14 properties against live Streamline availability and price each one.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="tq-email">Guest Email</Label>
          <Input
            id="tq-email"
            type="email"
            placeholder="guest@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={create.isPending}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tq-checkin">Check-in</Label>
          <Input
            id="tq-checkin"
            type="date"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
            disabled={create.isPending}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tq-checkout">Check-out</Label>
          <Input
            id="tq-checkout"
            type="date"
            value={checkOut}
            onChange={(e) => setCheckOut(e.target.value)}
            disabled={create.isPending}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tq-adults">Adults</Label>
          <Input
            id="tq-adults"
            type="number"
            min="1"
            max="24"
            value={adults}
            onChange={(e) => setAdults(e.target.value)}
            disabled={create.isPending}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tq-children">Children</Label>
          <Input
            id="tq-children"
            type="number"
            min="0"
            max="24"
            value={children}
            onChange={(e) => setChildren(e.target.value)}
            disabled={create.isPending}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="tq-pets">Pets</Label>
          <Input
            id="tq-pets"
            type="number"
            min="0"
            max="12"
            value={pets}
            onChange={(e) => setPets(e.target.value)}
            disabled={create.isPending}
          />
        </div>
      </CardContent>
      <CardFooter className="border-t">
        <Button
          type="button"
          disabled={!canSubmit}
          onClick={handleSubmit}
          className="w-full sm:w-auto"
        >
          {create.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Checking all 14 properties...
            </>
          ) : (
            <>
              <Users className="h-4 w-4" />
              Check Availability &amp; Generate Quote
            </>
          )}
        </Button>
      </CardFooter>
    </Card>
  );
}

// ─── Approval Queue ───────────────────────────────────────────────────────────

function ApprovalQueue() {
  const { data, isLoading } = useTaylorPendingQuotes();
  const requests = data?.requests ?? [];
  const pending = requests.filter((r) => r.status === "pending_approval");
  const sent = requests.filter((r) => r.status === "sent");

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading quote requests...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {pending.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-sm">Pending Approval</h3>
            <Badge variant="destructive" className="text-[11px]">{pending.length}</Badge>
          </div>
          {pending.map((r) => <PendingQuoteRow key={r.id} record={r} />)}
        </div>
      )}

      {sent.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold text-sm text-muted-foreground">Recently Sent</h3>
          {sent.slice(0, 10).map((r) => <PendingQuoteRow key={r.id} record={r} />)}
        </div>
      )}

      {requests.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No quote requests yet. Use the form above to create one.
        </div>
      )}
    </div>
  );
}

// ─── Main Export ─────────────────────────────────────────────────────────────

export function TaylorQuoteDashboard() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Taylor Quote Tool</h1>
        <p className="text-muted-foreground">
          Enter guest details → system checks all 14 properties → review available options →
          approve with one click to send a professional quote email.
        </p>
      </div>

      <QuoteRequestForm />
      <ApprovalQueue />
    </div>
  );
}
