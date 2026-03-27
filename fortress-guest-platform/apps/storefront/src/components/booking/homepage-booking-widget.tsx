"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import { CalendarDays, LoaderCircle, MapPinned, ReceiptText, Users } from "lucide-react";

import { getFastQuote, type QuoteActionState } from "@/app/actions/quote";
import type { StorefrontPropertySummary } from "@/lib/storefront-home";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface HomepageBookingWidgetProps {
  properties: StorefrontPropertySummary[];
  variant?: "modern" | "legacy";
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

export function HomepageBookingWidget({
  properties,
  variant = "modern",
}: HomepageBookingWidgetProps) {
  const [selectedPropertyId, setSelectedPropertyId] = useState<string>(properties[0]?.id ?? "");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [guests, setGuests] = useState<number>(2);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [quoteState, setQuoteState] = useState<QuoteActionState | null>(null);
  const [isPending, startTransition] = useTransition();

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const selectedProperty = useMemo(
    () => properties.find((property) => property.id === selectedPropertyId) ?? null,
    [properties, selectedPropertyId],
  );
  const nights = countNights(checkIn, checkOut);

  useEffect(() => {
    if (!selectedProperty) {
      return;
    }
    setGuests((current) => Math.min(Math.max(current, 1), selectedProperty.max_guests));
  }, [selectedProperty]);

  const continueHref =
    quoteState?.quote && quoteState.ok && selectedProperty
      ? `/book?propertyId=${encodeURIComponent(selectedProperty.id)}&checkIn=${encodeURIComponent(checkIn)}&checkOut=${encodeURIComponent(checkOut)}&guests=${encodeURIComponent(String(guests))}`
      : "/book";

  useEffect(() => {
    if (!selectedProperty) {
      setQuoteState(null);
      setValidationError("Select a cabin to price your stay.");
      return;
    }
    if (!checkIn || !checkOut) {
      setQuoteState(null);
      setValidationError("Select arrival and departure dates.");
      return;
    }
    if (checkOut <= checkIn) {
      setQuoteState(null);
      setValidationError("Departure must be after arrival.");
      return;
    }
    if (guests > selectedProperty.max_guests) {
      setQuoteState(null);
      setValidationError(`Guest count exceeds ${selectedProperty.name}'s maximum occupancy.`);
      return;
    }

    setValidationError(null);
    const timeoutId = window.setTimeout(() => {
      startTransition(async () => {
        const nextState = await getFastQuote({
          propertyId: selectedProperty.id,
          checkIn,
          checkOut,
          adults: guests,
          children: 0,
          pets: 0,
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
  }, [checkIn, checkOut, guests, selectedProperty, startTransition]);

  if (variant === "legacy") {
    return (
      <div className="content legacy-booking-widget">
        <form action="/" method="post" id="crog-search-cabins-form" acceptCharset="UTF-8">
          <div>
            <h2 className="pm-tab">
              <a href="/your-home-vacation-prosperity">Manage Your Property With Us</a>
            </h2>
            <h1 className="pm-title">Your Home for Vacation &amp; Prosperity</h1>
            <div id="select-cabin-name">
              <div className="form-item form-type-select form-item-cabin-name">
                <label htmlFor="edit-cabin-name">Cabin Name </label>
                <select
                  id="edit-cabin-name"
                  name="propertyId"
                  className="form-select"
                  value={selectedPropertyId}
                  onChange={(event) => setSelectedPropertyId(event.target.value)}
                  required
                >
                  <option value="" disabled>
                    - Select -
                  </option>
                  {properties.map((property) => (
                    <option key={property.id} value={property.id}>
                      {property.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div id="arrival-date-popup" className="date-wrapper">
              <div className="container-inline-date">
                <div className="form-item form-type-date-popup form-item-arrival">
                  <label htmlFor="edit-arrival-datepicker-popup-0">Arrival </label>
                  <div id="edit-arrival" className="date-padding clearfix">
                    <div className="form-item form-type-textfield form-item-arrival-date">
                      <input
                        type="date"
                        id="edit-arrival-datepicker-popup-0"
                        name="checkIn"
                        value={checkIn}
                        min={today}
                        onChange={(event) => setCheckIn(event.target.value)}
                        className="form-text"
                        required
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div id="departure-date-popup" className="date-wrapper">
              <div className="container-inline-date">
                <div className="form-item form-type-date-popup form-item-departure">
                  <label htmlFor="edit-departure-datepicker-popup-0">Departure </label>
                  <div id="edit-departure" className="date-padding clearfix">
                    <div className="form-item form-type-textfield form-item-departure-date">
                      <input
                        type="date"
                        id="edit-departure-datepicker-popup-0"
                        name="checkOut"
                        value={checkOut}
                        min={checkIn || today}
                        onChange={(event) => setCheckOut(event.target.value)}
                        className="form-text"
                        required
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div id="guest-count-popup" className="date-wrapper guest-count-wrapper">
              <div className="container-inline-date">
                <div className="form-item form-type-textfield form-item-guests">
                  <label htmlFor="edit-guests">Guests </label>
                  <div id="edit-guests-wrapper" className="date-padding clearfix">
                    <div className="form-item form-type-textfield form-item-guests-value">
                      <input
                        id="edit-guests"
                        type="number"
                        name="guests"
                        min={1}
                        max={selectedProperty?.max_guests ?? 20}
                        value={guests}
                        onChange={(event) => setGuests(Number(event.target.value))}
                        className="form-text"
                        required
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <input className="difference" type="hidden" name="difference" value="172800000" />
            <input type="hidden" name="dest" value="node" />
            <input className="search-by-field" type="hidden" name="search_by" value="name" />
            <input
              type="button"
              id="edit-submit"
              name="op"
              value={isPending ? "Searching..." : "Search"}
              className="form-submit"
              disabled
              aria-disabled="true"
            />
            <a href="/availability" className="availability-button" title="View a master availability calendar showing all cabins">
              <img
                src="https://media.cabin-rentals-of-georgia.com/sites/all/themes/crog/images/btn_master_calendar.png"
                alt="Check All Cabin Availability"
              />
            </a>
            <a href="/your-home-vacation-prosperity" className="property-management-link">
              Property
              <br />
              Management
            </a>
            {selectedProperty?.address ? (
              <div className="legacy-search-meta">{selectedProperty.address}</div>
            ) : null}
            {validationError ? (
              <div className="legacy-search-feedback legacy-search-feedback-error">{validationError}</div>
            ) : null}
            {quoteState?.quote && selectedProperty ? (
              <div className="legacy-search-feedback legacy-search-feedback-success">
                <strong>{selectedProperty.name}</strong>
                {nights ? ` · ${nights} night${nights === 1 ? "" : "s"}` : ""}
                <span>
                  Total {formatCurrency(quoteState.quote.total_amount)} for {guests} guest
                  {guests === 1 ? "" : "s"}.
                </span>
                {quoteState.ok ? <Link href={continueHref}>Continue to booking</Link> : null}
              </div>
            ) : null}
          </div>
        </form>
      </div>
    );
  }

  return (
    <section className="rounded-[2rem] border border-amber-200/70 bg-white/95 p-6 shadow-xl shadow-slate-900/5 backdrop-blur sm:p-8">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
          <ReceiptText className="h-3.5 w-3.5" />
          Local Quote Engine
        </div>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
          Check availability and price your stay
        </h2>
        <p className="text-sm leading-7 text-slate-600">
          Quotes are calculated live from the sovereign booking ledger through a secure{" "}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">
            Server Action -&gt; POST /api/quote
          </code>
          .
        </p>
      </div>

      <div className="mt-6 space-y-5">
        <div className="space-y-2">
          <Label htmlFor="home-property" className="text-slate-800">
            Cabin
          </Label>
          <select
            id="home-property"
            value={selectedPropertyId}
            onChange={(event) => setSelectedPropertyId(event.target.value)}
            className="flex h-11 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-0 transition focus:border-slate-900"
            required
          >
            {properties.map((property) => (
              <option key={property.id} value={property.id}>
                {property.name}
              </option>
            ))}
          </select>
          {selectedProperty?.address ? (
            <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-slate-500">
              <MapPinned className="h-3.5 w-3.5" />
              {selectedProperty.address}
            </p>
          ) : null}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="home-check-in" className="text-slate-800">
              <CalendarDays className="h-4 w-4" />
              Arrival
            </Label>
            <Input
              id="home-check-in"
              type="date"
              min={today}
              value={checkIn}
              onChange={(event) => setCheckIn(event.target.value)}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="home-check-out" className="text-slate-800">
              <CalendarDays className="h-4 w-4" />
              Departure
            </Label>
            <Input
              id="home-check-out"
              type="date"
              min={checkIn || today}
              value={checkOut}
              onChange={(event) => setCheckOut(event.target.value)}
              className="border-slate-300 bg-white text-slate-900"
              required
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="home-guests" className="text-slate-800">
            <Users className="h-4 w-4" />
            Guests
          </Label>
          <Input
            id="home-guests"
            type="number"
            min={1}
            max={selectedProperty?.max_guests ?? 20}
            value={guests}
            onChange={(event) => setGuests(Number(event.target.value))}
            className="border-slate-300 bg-white text-slate-900"
            required
          />
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
            Sleeps up to {selectedProperty?.max_guests ?? 20} guests
          </p>
        </div>

        <Button
          type="button"
          size="lg"
          disabled
          className="w-full rounded-sm bg-slate-900 text-white hover:bg-black"
        >
          {isPending ? (
            <>
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Calculating sovereign quote
            </>
          ) : (
            "Quote updates automatically"
          )}
        </Button>
      </div>

      {validationError ? (
        <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {validationError}
        </p>
      ) : null}

      {quoteState?.quote && selectedProperty ? (
        <div className="mt-6 space-y-4 rounded-[1.5rem] border border-slate-200 bg-slate-50 p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium uppercase tracking-[0.18em] text-slate-500">
                Live quote
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {selectedProperty.name}
                {nights ? ` · ${nights} night${nights === 1 ? "" : "s"}` : ""}
              </p>
            </div>
            <p className="text-xs uppercase tracking-[0.18em] text-emerald-700">
              {quoteState.ok ? "Ledger verified" : "Review selection"}
            </p>
          </div>

          <div className="space-y-3 text-sm text-slate-700">
            {quoteState.quote.line_items.map((item) => (
              <div
                key={`${item.type}-${item.description}`}
                className="flex items-center justify-between"
              >
                <span>{item.description}</span>
                <span>{formatCurrency(item.amount)}</span>
              </div>
            ))}
            <div className="h-px bg-slate-200" />
            <div className="flex items-center justify-between text-base font-semibold text-slate-900">
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
              <Link href={continueHref}>{quoteState.ok ? "Continue to booking" : "Not Bookable"}</Link>
            </Button>
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
              Payload: itemized sovereign quote
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
