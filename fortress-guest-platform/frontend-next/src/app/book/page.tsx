"use client";

import { Suspense, useEffect, useMemo, useState, useTransition } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { getFastQuote, type QuoteActionState } from "@/app/actions/quote";
import { api } from "@/lib/api";
import { DirectBookingPayPanel } from "@/components/booking/direct-booking-pay-panel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  ArrowRight,
  Bath,
  Bed,
  Calendar,
  Check,
  CreditCard,
  Mountain,
  Shield,
  Star,
  Users,
} from "lucide-react";

type AvailabilityResult = {
  check_in: string;
  check_out: string;
  guests: number;
  results: AvailabilityProperty[];
};

type AvailabilityProperty = {
  id: string;
  name: string;
  slug: string;
  property_type: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string | null;
  pricing: {
    nightly_rate: number;
    nights: number;
    subtotal: number;
    cleaning_fee: number;
    service_fee: number;
    tax: number;
    total: number;
  };
};

type CatalogProperty = {
  id: string;
  name: string;
  slug: string;
  property_type: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string | null;
  is_active: boolean;
  source: string;
};

type PropertyCatalogResponse = {
  properties: CatalogProperty[];
};

type HoldBookingResponse = {
  hold_id: string;
  expires_at: string;
  total_amount: number;
  payment: { client_secret: string; payment_intent_id: string };
  reservation_id: string | null;
  confirmation_code: string | null;
};

type ConfirmationResult = {
  reservation_id: string;
  confirmation_code: string;
  total_amount: number;
};

type BookingConfig = { stripe_publishable_key: string };

type BookingStep = "search" | "results" | "details" | "pay" | "confirmed";

function clampGuests(rawValue: string | null): number {
  const parsed = Number.parseInt(rawValue || "2", 10);
  if (Number.isNaN(parsed)) {
    return 2;
  }
  return Math.max(1, Math.min(parsed, 20));
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

function StorefrontBookPageContent() {
  const searchParams = useSearchParams();
  const handoffPropertyId = searchParams.get("propertyId")?.trim() || "";
  const handoffCheckIn = searchParams.get("checkIn")?.trim() || "";
  const handoffCheckOut = searchParams.get("checkOut")?.trim() || "";
  const handoffGuests = clampGuests(searchParams.get("guests"));
  const hasHandoff = Boolean(handoffPropertyId && handoffCheckIn && handoffCheckOut);

  const [step, setStep] = useState<BookingStep>("search");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [guests, setGuests] = useState(2);
  const [selectedProperty, setSelectedProperty] = useState("");
  const [searchRequested, setSearchRequested] = useState(false);
  const [guestInfo, setGuestInfo] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    requests: "",
  });
  const [checkoutHold, setCheckoutHold] = useState<HoldBookingResponse | null>(null);
  const [confirmation, setConfirmation] = useState<ConfirmationResult | null>(null);
  const [quoteState, setQuoteState] = useState<QuoteActionState | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quotePending, startQuoteTransition] = useTransition();

  useEffect(() => {
    if (!handoffPropertyId || !handoffCheckIn || !handoffCheckOut) {
      return;
    }

    setCheckIn(handoffCheckIn);
    setCheckOut(handoffCheckOut);
    setGuests(handoffGuests);
    setSelectedProperty(handoffPropertyId);
    setSearchRequested(false);
    setCheckoutHold(null);
    setConfirmation(null);
    setQuoteState(null);
    setQuoteError(null);
    setStep("details");
  }, [handoffCheckIn, handoffCheckOut, handoffGuests, handoffPropertyId]);

  const availability = useQuery<AvailabilityResult>({
    queryKey: ["availability", checkIn, checkOut, guests],
    queryFn: () =>
      api.get("/api/direct-booking/availability", {
        check_in: checkIn,
        check_out: checkOut,
        guests,
      }),
    enabled: searchRequested && Boolean(checkIn) && Boolean(checkOut) && checkOut > checkIn,
  });

  const handoffCatalog = useQuery<PropertyCatalogResponse>({
    queryKey: ["quote-property-catalog"],
    queryFn: () => api.get<PropertyCatalogResponse>("/api/quotes/streamline/properties"),
    enabled: hasHandoff,
    staleTime: 60_000,
  });

  const bookingConfig = useQuery<BookingConfig>({
    queryKey: ["direct-booking-config"],
    queryFn: () => api.get<BookingConfig>("/api/direct-booking/config"),
    enabled: step === "pay",
    staleTime: 60_000,
  });

  const bookMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post<HoldBookingResponse>("/api/direct-booking/book", data),
    onSuccess: (data) => {
      setCheckoutHold(data);
      setStep("pay");
    },
  });

  const selected = useMemo(() => {
    return (
      availability.data?.results.find((property) => property.id === selectedProperty) ??
      handoffCatalog.data?.properties.find((property) => property.id === selectedProperty) ??
      null
    );
  }, [availability.data?.results, handoffCatalog.data?.properties, selectedProperty]);

  useEffect(() => {
    if (step !== "results" || !selectedProperty || !availability.data) {
      return;
    }

    if (availability.data.results.some((property) => property.id === selectedProperty)) {
      setStep("details");
    }
  }, [availability.data, selectedProperty, step]);

  const prefillMissedSelection =
    step === "results" &&
    Boolean(handoffPropertyId) &&
    availability.isSuccess &&
    !selected &&
    availability.data.results.length > 0;

  function resetFlow(nextStep: BookingStep) {
    setStep(nextStep);
    setCheckoutHold(null);
    setConfirmation(null);
    setQuoteState(null);
    setQuoteError(null);
  }

  function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearchRequested(true);
    setSelectedProperty("");
    resetFlow("results");
  }

  function handlePropertySelection(propertyId: string) {
    setSelectedProperty(propertyId);
    setCheckoutHold(null);
    setConfirmation(null);
    setQuoteState(null);
    setQuoteError(null);
    setStep("details");
  }

  function handleBook(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProperty) {
      return;
    }

    bookMutation.mutate({
      property_id: selectedProperty,
      check_in: checkIn,
      check_out: checkOut,
      num_guests: guests,
      guest_first_name: guestInfo.first_name,
      guest_last_name: guestInfo.last_name,
      guest_email: guestInfo.email,
      guest_phone: guestInfo.phone,
      special_requests: guestInfo.requests || undefined,
    });
  }

  useEffect(() => {
    if (
      step !== "details" ||
      !selectedProperty ||
      !checkIn ||
      !checkOut ||
      checkOut <= checkIn
    ) {
      return;
    }

    setQuoteError(null);
    const timeoutId = window.setTimeout(() => {
      startQuoteTransition(async () => {
        const nextState = await getFastQuote({
          propertyId: selectedProperty,
          checkIn,
          checkOut,
          adults: guests,
          children: 0,
          pets: 0,
        });
        setQuoteState(nextState);
        if (!nextState.ok) {
          setQuoteError(nextState.error);
        }
      });
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [checkIn, checkOut, guests, selectedProperty, startQuoteTransition, step]);

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <section className="border-b border-slate-200 bg-slate-50">
        <div className="mx-auto max-w-6xl px-6 py-12">
          <div className="flex items-center gap-3">
            <div className="rounded-full border border-slate-200 bg-white p-2">
              <Mountain className="h-5 w-5 text-slate-600" />
            </div>
            <div>
              <h1 className="text-3xl font-light tracking-tight">Direct Booking Checkout</h1>
              <p className="mt-1 text-sm uppercase tracking-[0.18em] text-slate-500">
                Secure guest checkout with live sovereign pricing
              </p>
            </div>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {step === "details" && !selected && hasHandoff && handoffCatalog.isLoading && (
          <section className="mx-auto max-w-2xl rounded-[2rem] border border-slate-200 bg-white px-8 py-12 text-center text-slate-600 shadow-sm">
            Loading cabin details...
          </section>
        )}

        {step === "details" && !selected && hasHandoff && handoffCatalog.isError && (
          <section className="mx-auto max-w-2xl rounded-[2rem] border border-rose-200 bg-rose-50 px-8 py-12 text-center text-rose-700 shadow-sm">
            Cabin details could not be loaded for this booking handoff.
          </section>
        )}

        {step === "search" && (
          <section className="mx-auto max-w-2xl rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">
            <div className="space-y-3 text-center">
              <h2 className="text-2xl font-semibold tracking-tight">Find your dates</h2>
              <p className="text-slate-600">
                Search live availability and continue into a clean, direct guest checkout.
              </p>
            </div>

            <form onSubmit={handleSearch} className="mt-8 space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="book-check-in" className="text-slate-800">
                    <Calendar className="h-4 w-4" />
                    Check-in
                  </Label>
                  <Input
                    id="book-check-in"
                    type="date"
                    value={checkIn}
                    onChange={(event) => setCheckIn(event.target.value)}
                    min={new Date().toISOString().slice(0, 10)}
                    className="border-slate-300 bg-white text-slate-900"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="book-check-out" className="text-slate-800">
                    <Calendar className="h-4 w-4" />
                    Check-out
                  </Label>
                  <Input
                    id="book-check-out"
                    type="date"
                    value={checkOut}
                    onChange={(event) => setCheckOut(event.target.value)}
                    min={checkIn || new Date().toISOString().slice(0, 10)}
                    className="border-slate-300 bg-white text-slate-900"
                    required
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="book-guests" className="text-slate-800">
                  <Users className="h-4 w-4" />
                  Guests
                </Label>
                <Input
                  id="book-guests"
                  type="number"
                  min={1}
                  max={20}
                  value={guests}
                  onChange={(event) => setGuests(Number(event.target.value))}
                  className="border-slate-300 bg-white text-slate-900"
                  required
                />
              </div>

              <button
                type="submit"
                className="inline-flex w-full items-center justify-center gap-2 rounded-sm bg-slate-900 px-6 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-black"
              >
                Search Availability
                <ArrowRight className="h-4 w-4" />
              </button>

              <div className="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs uppercase tracking-[0.14em] text-slate-500">
                <span className="inline-flex items-center gap-1.5">
                  <Shield className="h-3.5 w-3.5" />
                  Secure booking
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Star className="h-3.5 w-3.5" />
                  Live ledger pricing
                </span>
              </div>
            </form>
          </section>
        )}

        {step === "results" && (
          <section className="space-y-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-2xl font-semibold tracking-tight">Available Cabins</h2>
                <p className="mt-1 text-slate-600">
                  {checkIn} to {checkOut} for {guests} guest{guests === 1 ? "" : "s"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => resetFlow("search")}
                className="inline-flex items-center justify-center rounded-sm border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
              >
                Change Dates
              </button>
            </div>

            {availability.isLoading ? (
              <div className="rounded-[2rem] border border-slate-200 bg-white px-6 py-12 text-center text-slate-600 shadow-sm">
                Searching live inventory...
              </div>
            ) : availability.isError ? (
              <div className="rounded-[2rem] border border-rose-200 bg-rose-50 px-6 py-6 text-sm text-rose-700">
                Availability could not be loaded. Retry in a moment.
              </div>
            ) : (availability.data?.results ?? []).length === 0 ? (
              <div className="rounded-[2rem] border border-slate-200 bg-white px-6 py-12 text-center text-slate-600 shadow-sm">
                No cabins are available for those dates.
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {(availability.data?.results ?? []).map((property) => (
                  <button
                    key={property.id}
                    type="button"
                    onClick={() => handlePropertySelection(property.id)}
                    className="rounded-[2rem] border border-slate-200 bg-white p-6 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
                  >
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <h3 className="text-xl font-semibold tracking-tight text-slate-900">
                          {property.name}
                        </h3>
                        <div className="flex flex-wrap gap-3 text-sm text-slate-600">
                          <span className="inline-flex items-center gap-1.5">
                            <Bed className="h-4 w-4" />
                            {property.bedrooms} BR
                          </span>
                          <span className="inline-flex items-center gap-1.5">
                            <Bath className="h-4 w-4" />
                            {property.bathrooms} BA
                          </span>
                          <span className="inline-flex items-center gap-1.5">
                            <Users className="h-4 w-4" />
                            Sleeps {property.max_guests}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-end justify-between gap-4">
                        <div>
                          <p className="text-2xl font-semibold text-slate-900">
                            {formatCurrency(property.pricing.nightly_rate)}
                            <span className="ml-1 text-sm font-normal text-slate-500">/night</span>
                          </p>
                          <p className="text-sm text-slate-600">
                            {formatCurrency(property.pricing.total)} total for {property.pricing.nights}{" "}
                            night{property.pricing.nights === 1 ? "" : "s"}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-2 rounded-sm bg-slate-900 px-4 py-2 text-sm font-semibold text-white">
                          Reserve Now
                          <ArrowRight className="h-4 w-4" />
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {prefillMissedSelection ? (
              <div className="rounded-[2rem] border border-amber-200 bg-amber-50 px-6 py-4 text-sm text-amber-800">
                The cabin passed from the quote widget is not currently returned for these dates.
                Select another available stay or adjust the date range.
              </div>
            ) : null}
          </section>
        )}

        {step === "details" && selected && (
          <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">
              <div className="space-y-3">
                <h2 className="text-2xl font-semibold tracking-tight">Complete Your Booking</h2>
                <p className="text-slate-600">
                  {selected.name} · {checkIn} to {checkOut}
                </p>
              </div>

              <form onSubmit={handleBook} className="mt-8 space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="guest-first-name" className="text-slate-800">
                      First Name
                    </Label>
                    <Input
                      id="guest-first-name"
                      value={guestInfo.first_name}
                      onChange={(event) =>
                        setGuestInfo({ ...guestInfo, first_name: event.target.value })
                      }
                      className="border-slate-300 bg-white text-slate-900"
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="guest-last-name" className="text-slate-800">
                      Last Name
                    </Label>
                    <Input
                      id="guest-last-name"
                      value={guestInfo.last_name}
                      onChange={(event) =>
                        setGuestInfo({ ...guestInfo, last_name: event.target.value })
                      }
                      className="border-slate-300 bg-white text-slate-900"
                      required
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="guest-email" className="text-slate-800">
                    Email
                  </Label>
                  <Input
                    id="guest-email"
                    type="email"
                    value={guestInfo.email}
                    onChange={(event) => setGuestInfo({ ...guestInfo, email: event.target.value })}
                    className="border-slate-300 bg-white text-slate-900"
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="guest-phone" className="text-slate-800">
                    Phone
                  </Label>
                  <Input
                    id="guest-phone"
                    type="tel"
                    value={guestInfo.phone}
                    onChange={(event) => setGuestInfo({ ...guestInfo, phone: event.target.value })}
                    className="border-slate-300 bg-white text-slate-900"
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="guest-requests" className="text-slate-800">
                    Special Requests
                  </Label>
                  <Textarea
                    id="guest-requests"
                    value={guestInfo.requests}
                    onChange={(event) =>
                      setGuestInfo({ ...guestInfo, requests: event.target.value })
                    }
                    className="min-h-28 border-slate-300 bg-white text-slate-900"
                  />
                </div>

                <button
                  type="submit"
                  disabled={
                    bookMutation.isPending ||
                    quotePending ||
                    !Boolean(quoteState?.quote) ||
                    !quoteState?.ok
                  }
                  className="inline-flex w-full items-center justify-center gap-2 rounded-sm bg-slate-900 px-6 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <CreditCard className="h-4 w-4" />
                  {bookMutation.isPending
                    ? "Securing Your Hold"
                    : `Continue to Payment ${formatCurrency(
                        quoteState?.quote?.total_amount ??
                          ("pricing" in selected ? selected.pricing.total : 0),
                      )}`}
                </button>

                {quoteError ? (
                  <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {quoteError}
                  </p>
                ) : null}
              </form>
            </div>

            <aside className="rounded-[2rem] border border-slate-200 bg-slate-50 p-8 shadow-sm">
              <div className="space-y-2">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                  Live Quote Verification
                </p>
                <h3 className="text-xl font-semibold tracking-tight text-slate-900">
                  Sovereign ledger check
                </h3>
                <p className="text-sm leading-7 text-slate-600">
                  This checkout step revalidates pricing through a secure{" "}
                  <code className="rounded bg-white px-1.5 py-0.5 text-xs text-slate-700">
                    Server Action -&gt; POST /api/quote
                  </code>{" "}
                  before any payment hold is created.
                </p>
              </div>

              <div className="mt-6 space-y-3 rounded-[1.5rem] border border-slate-200 bg-white p-5">
                {quotePending ? (
                  <p className="text-sm text-slate-600">Re-verifying live pricing...</p>
                ) : quoteError ? (
                  <p className="text-sm text-rose-700">{quoteError}</p>
                ) : quoteState?.quote ? (
                  <>
                    {quoteState.quote.line_items.map((item) => (
                      <div
                        key={`${item.type}-${item.description}`}
                        className="flex items-center justify-between text-sm text-slate-700"
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
                  </>
                ) : (
                  <p className="text-sm text-slate-600">Choose a property to verify pricing.</p>
                )}
              </div>

              <div className="mt-5 rounded-[1.5rem] border border-slate-200 bg-white p-5">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                  Stay Summary
                </p>
                <div className="mt-3 space-y-2 text-sm text-slate-700">
                  <p>{selected.name}</p>
                  <p>
                    {selected.bedrooms} bedrooms · {selected.bathrooms} bathrooms · Sleeps{" "}
                    {selected.max_guests}
                  </p>
                  <p>
                    {checkIn} to {checkOut} · {guests} guest{guests === 1 ? "" : "s"}
                  </p>
                </div>
              </div>
            </aside>
          </section>
        )}

        {step === "pay" && checkoutHold && selected && (
          <section className="mx-auto max-w-2xl rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">
            <div className="space-y-3">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                Secure Payment
              </p>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                Complete your reservation
              </h2>
              <p className="text-slate-600">
                {selected.name} · Hold expires {new Date(checkoutHold.expires_at).toLocaleString()}
              </p>
            </div>

            <div className="mt-8 rounded-[1.5rem] border border-slate-200 bg-slate-50 p-6">
              {bookingConfig.isLoading ? (
                <p className="text-sm text-slate-600">Loading payment form...</p>
              ) : (
                <DirectBookingPayPanel
                  publishableKey={bookingConfig.data?.stripe_publishable_key ?? ""}
                  clientSecret={checkoutHold.payment.client_secret}
                  holdId={checkoutHold.hold_id}
                  totalAmount={checkoutHold.total_amount}
                  defaultCardholderName={`${guestInfo.first_name} ${guestInfo.last_name}`.trim()}
                  onConfirmed={(result) => {
                    setConfirmation(result);
                    setCheckoutHold(null);
                    setStep("confirmed");
                  }}
                />
              )}
            </div>
          </section>
        )}

        {step === "confirmed" && confirmation && (
          <section className="mx-auto max-w-2xl rounded-[2rem] border border-slate-200 bg-white p-10 text-center shadow-sm">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-50">
              <Check className="h-8 w-8 text-emerald-600" />
            </div>
            <h2 className="mt-6 text-3xl font-semibold tracking-tight text-slate-900">
              Booking Confirmed
            </h2>
            <p className="mt-3 text-slate-600">Your confirmation code is below.</p>
            <div className="mt-6 inline-flex rounded-sm border border-slate-300 bg-slate-50 px-5 py-3 text-lg font-semibold uppercase tracking-[0.2em] text-slate-900">
              {confirmation.confirmation_code}
            </div>
            <p className="mt-6 text-sm text-slate-600">
              A confirmation email has been sent with arrival details and reservation records.
            </p>
            <button
              type="button"
              onClick={() => {
                setStep("search");
                setConfirmation(null);
                setSelectedProperty("");
                setSearchRequested(false);
              }}
              className="mt-8 inline-flex items-center justify-center rounded-sm border border-slate-300 bg-white px-5 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
            >
              Book Another Stay
            </button>
          </section>
        )}
      </main>
    </div>
  );
}

export default function StorefrontBookPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-white text-slate-900">
          <section className="border-b border-slate-200 bg-slate-50">
            <div className="mx-auto max-w-6xl px-6 py-12">
              <div className="flex items-center gap-3">
                <div className="rounded-full border border-slate-200 bg-white p-2">
                  <Mountain className="h-5 w-5 text-slate-600" />
                </div>
                <div>
                  <h1 className="text-3xl font-light tracking-tight">Direct Booking Checkout</h1>
                  <p className="mt-1 text-sm uppercase tracking-[0.18em] text-slate-500">
                    Secure guest checkout with live sovereign pricing
                  </p>
                </div>
              </div>
            </div>
          </section>
          <main className="mx-auto max-w-6xl px-6 py-10">
            <div className="mx-auto max-w-2xl rounded-[2rem] border border-slate-200 bg-white px-8 py-12 text-center text-slate-600 shadow-sm">
              Loading checkout...
            </div>
          </main>
        </div>
      }
    >
      <StorefrontBookPageContent />
    </Suspense>
  );
}
