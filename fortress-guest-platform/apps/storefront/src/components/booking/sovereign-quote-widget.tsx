"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import { CalendarDays, LoaderCircle, ReceiptText, ShieldCheck, Users } from "lucide-react";
import {
  getFastQuote,
  type QuoteActionState,
  type QuoteLineItemType,
} from "@/app/actions/quote";
import {
  SovereignAvailabilityCalendar,
  type PropertyCalendarPayload,
} from "@/components/booking/sovereign-availability-calendar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { postStorefrontIntentEvent } from "@/lib/storefront-intent";

interface SovereignQuoteWidgetProps {
  propertyId: string;
  propertySlug: string;
  propertyName: string;
  maxGuests: number;
  initialCalendar: PropertyCalendarPayload | null;
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

function countNights(checkIn: string, checkOut: string): number | null {
  if (!checkIn || !checkOut) {
    return null;
  }

  const start = new Date(`${checkIn}T00:00:00Z`);
  const end = new Date(`${checkOut}T00:00:00Z`);
  const diffMs = end.getTime() - start.getTime();

  if (!Number.isFinite(diffMs) || diffMs <= 0) {
    return null;
  }

  return Math.round(diffMs / 86_400_000);
}

export function SovereignQuoteWidget({
  propertyId,
  propertySlug,
  propertyName,
  maxGuests,
  initialCalendar,
}: SovereignQuoteWidgetProps) {
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [adults, setAdults] = useState(Math.min(2, maxGuests));
  const [children, setChildren] = useState(0);
  const [pets, setPets] = useState(0);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [quoteState, setQuoteState] = useState<QuoteActionState | null>(null);
  const [isPending, startTransition] = useTransition();

  const nights = countNights(checkIn, checkOut);
  const totalGuests = adults + children;

  const continueHref =
    quoteState?.quote && quoteState.ok && checkIn && checkOut
      ? `/book?propertyId=${encodeURIComponent(propertyId)}&checkIn=${encodeURIComponent(checkIn)}&checkOut=${encodeURIComponent(checkOut)}&guests=${encodeURIComponent(String(totalGuests))}&adults=${encodeURIComponent(String(adults))}&children=${encodeURIComponent(String(children))}&pets=${encodeURIComponent(String(pets))}`
      : "/book";
  const lineItems = quoteState?.quote?.line_items ?? [];
  const quoteIntentKey = useMemo(() => {
    if (!quoteState?.ok || !checkIn || !checkOut) {
      return null;
    }
    return ["quote_open", propertySlug, checkIn, checkOut, adults, children, pets].join(":");
  }, [adults, checkIn, checkOut, children, pets, propertySlug, quoteState?.ok]);

  useEffect(() => {
    const hasDates = Boolean(checkIn) && Boolean(checkOut);
    if (!hasDates) {
      setQuoteState(null);
      setValidationError("Select arrival and departure dates.");
      return;
    }

    if (checkOut <= checkIn) {
      setQuoteState(null);
      setValidationError("Departure must be after arrival.");
      return;
    }

    if (totalGuests < 1) {
      setQuoteState(null);
      setValidationError("At least one guest is required.");
      return;
    }

    if (totalGuests > maxGuests) {
      setQuoteState(null);
      setValidationError(`Selected party exceeds the ${maxGuests}-guest limit.`);
      return;
    }

    setValidationError(null);
    const timeoutId = window.setTimeout(() => {
      startTransition(async () => {
        const nextState = await getFastQuote({
          propertyId,
          checkIn,
          checkOut,
          adults,
          children,
          pets,
        });
        setQuoteState(nextState);
        if (!nextState.ok) {
          setValidationError(nextState.error);
        }
      });
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [adults, checkIn, checkOut, children, maxGuests, pets, propertyId, totalGuests]);

  useEffect(() => {
    if (!quoteIntentKey || !quoteState?.ok || !checkIn || !checkOut) {
      return;
    }
    void postStorefrontIntentEvent({
      eventType: "quote_open",
      propertySlug,
      dedupeKey: quoteIntentKey,
      meta: {
        check_in: checkIn,
        check_out: checkOut,
        adults,
        children,
        pets,
      },
    });
  }, [adults, checkIn, checkOut, children, pets, propertySlug, quoteIntentKey, quoteState?.ok]);

  return (
    <section
      data-testid="sovereign-quote-widget"
      className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm sm:p-8"
    >
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-600">
          <ReceiptText className="h-3.5 w-3.5" />
          Sovereign Quote Widget
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
          Price your stay at {propertyName}
        </h2>
        <p className="text-sm leading-7 text-slate-600">
          Live quote math is calculated from the sovereign ledger through a secure server action
          to{" "}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">
            POST /api/direct-booking/quote
          </code>
          , without exposing internal auth to the browser.
        </p>
      </div>

      <div className="mt-6 space-y-5">
        {initialCalendar ? (
          <SovereignAvailabilityCalendar
            propertySlug={propertySlug}
            initialCalendar={initialCalendar}
            checkIn={checkIn}
            checkOut={checkOut}
            onDatesChange={({ checkIn: nextCheckIn, checkOut: nextCheckOut }) => {
              setCheckIn(nextCheckIn);
              setCheckOut(nextCheckOut);
            }}
          />
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="quote-check-in" className="text-slate-800">
              <CalendarDays className="h-4 w-4" />
              Arrival
            </Label>
            <Input
              id="quote-check-in"
              data-testid="quote-check-in"
              type="date"
              min={today}
              value={checkIn}
              onChange={(event) => setCheckIn(event.target.value)}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="quote-check-out" className="text-slate-800">
              <CalendarDays className="h-4 w-4" />
              Departure
            </Label>
            <Input
              id="quote-check-out"
              data-testid="quote-check-out"
              type="date"
              min={checkIn || today}
              value={checkOut}
              onChange={(event) => setCheckOut(event.target.value)}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="quote-adults" className="text-slate-800">
              <Users className="h-4 w-4" />
              Adults
            </Label>
            <Input
              id="quote-adults"
              type="number"
              min={1}
              max={maxGuests}
              value={adults}
              onChange={(event) => setAdults(Number(event.target.value))}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="quote-children" className="text-slate-800">
            <Users className="h-4 w-4" />
              Children
          </Label>
            <Input
              id="quote-children"
              type="number"
              min={0}
              max={maxGuests}
              value={children}
              onChange={(event) => setChildren(Number(event.target.value))}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="quote-pets" className="text-slate-800">
              <ShieldCheck className="h-4 w-4" />
              Pets
            </Label>
            <Input
              id="quote-pets"
              type="number"
              min={0}
              value={pets}
              onChange={(event) => setPets(Number(event.target.value))}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>
        </div>

        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
          Sleeps up to {maxGuests} guests total. Quote refreshes automatically as inputs change.
        </p>
      </div>

      {validationError ? (
        <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {validationError}
        </p>
      ) : null}

      <div
        data-testid="live-quote-panel"
        className="relative mt-6 rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5"
      >
        {isPending ? (
          <div
            data-testid="live-quote-loading"
            className="absolute inset-0 z-10 flex items-center justify-center rounded-[1.5rem] bg-white/75 backdrop-blur-[1px]"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Calculating live quote
            </div>
          </div>
        ) : null}

        {quoteState?.quote ? (
          <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium uppercase tracking-[0.18em] text-slate-500">
                Live Quote
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {nights ? `${nights} night${nights === 1 ? "" : "s"}` : "Selected stay"} for{" "}
                {totalGuests} guest{totalGuests === 1 ? "" : "s"}
              </p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-700">
              <ShieldCheck className="h-3.5 w-3.5" />
              {quoteState.ok ? "Ledger verified" : "Review selection"}
            </div>
          </div>

          <div data-testid="live-quote-line-items" className="space-y-3 text-sm text-slate-700">
            {lineItems.map((item: QuoteLineItemType) => (
              <div
                key={`${item.type}-${item.description}`}
                data-testid="live-quote-line-item"
                className="flex items-center justify-between"
              >
                <span>{item.description}</span>
                <span>{formatCurrency(item.amount)}</span>
              </div>
            ))}
            <div className="h-px bg-slate-200" />
            <div
              data-testid="live-quote-total"
              className="flex items-center justify-between text-base font-semibold text-slate-900"
            >
              <span>Total</span>
              <span>{formatCurrency(quoteState.quote.total_amount)}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button
              asChild
              size="lg"
              disabled={isPending || !quoteState.ok}
              className="rounded-sm bg-slate-900 text-white hover:bg-black"
            >
              <Link data-testid="quote-book-now" href={continueHref}>
                {quoteState.ok ? "Book Now" : "Not Bookable"}
              </Link>
            </Button>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
              Quote output: itemized rent, fees, taxes, and total
            </p>
          </div>
          </div>
        ) : (
          <div className="space-y-2 text-sm text-slate-600">
            <p className="font-medium uppercase tracking-[0.18em] text-slate-500">Live Quote</p>
            <p>Choose dates and party size to render sovereign pricing in real time.</p>
          </div>
        )}
      </div>
    </section>
  );
}
