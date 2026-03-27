"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { getStorefrontSessionId } from "@/lib/storefront-session";
import { postStorefrontIntentEvent } from "@/lib/storefront-intent";
import { useSovereignCheckoutFlow } from "@/components/booking/sovereign-checkout-flow";
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
  Mail,
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

type BookingConfig = {
  stripe_publishable_key: string;
  sovereign_quote_signing_required?: boolean;
};

type BookingStep = "search" | "results" | "details" | "pay" | "confirmed";

function clampGuests(rawValue: string | null): number {
  const parsed = Number.parseInt(rawValue || "2", 10);
  if (Number.isNaN(parsed)) {
    return 2;
  }
  return Math.max(1, Math.min(parsed, 20));
}

function clampPets(rawValue: string | null): number {
  const parsed = Number.parseInt(rawValue || "0", 10);
  if (Number.isNaN(parsed)) {
    return 0;
  }
  return Math.max(0, Math.min(parsed, 12));
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
  const handoffAdultsRaw = searchParams.get("adults");
  const handoffChildrenRaw = searchParams.get("children");
  const handoffPets = clampPets(searchParams.get("pets"));
  const hasHandoff = Boolean(handoffPropertyId && handoffCheckIn && handoffCheckOut);

  const [step, setStep] = useState<BookingStep>("search");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [guests, setGuests] = useState(2);
  const [adults, setAdults] = useState(2);
  const [children, setChildren] = useState(0);
  const [pets, setPets] = useState(0);
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
  const [conciergeRecoveryOptIn, setConciergeRecoveryOptIn] = useState(false);
  const [saveQuoteMessage, setSaveQuoteMessage] = useState<string | null>(null);
  const resolveDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!handoffPropertyId || !handoffCheckIn || !handoffCheckOut) {
      return;
    }

    setCheckIn(handoffCheckIn);
    setCheckOut(handoffCheckOut);
    setSelectedProperty(handoffPropertyId);
    setSearchRequested(false);
    setCheckoutHold(null);
    setConfirmation(null);
    setStep("details");

    const parsedAdults = handoffAdultsRaw !== null ? Number.parseInt(handoffAdultsRaw, 10) : Number.NaN;
    const parsedChildren =
      handoffChildrenRaw !== null ? Number.parseInt(handoffChildrenRaw, 10) : Number.NaN;
    if (
      Number.isFinite(parsedAdults) &&
      Number.isFinite(parsedChildren) &&
      parsedAdults >= 1 &&
      parsedChildren >= 0 &&
      parsedAdults + parsedChildren >= 1
    ) {
      setAdults(parsedAdults);
      setChildren(parsedChildren);
      setGuests(parsedAdults + parsedChildren);
    } else {
      setGuests(handoffGuests);
      setAdults(Math.max(1, handoffGuests));
      setChildren(0);
    }
    setPets(handoffPets);
  }, [
    handoffAdultsRaw,
    handoffCheckIn,
    handoffCheckOut,
    handoffChildrenRaw,
    handoffGuests,
    handoffPets,
    handoffPropertyId,
  ]);

  const sovereignCheckout = useSovereignCheckoutFlow({
    enabled: step === "details" && Boolean(selectedProperty) && Boolean(checkIn) && Boolean(checkOut),
    propertyId: selectedProperty,
    checkIn,
    checkOut,
    guests,
    adults,
    children,
    pets,
  });

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
    enabled: step === "pay" && !sovereignCheckout.config?.stripe_publishable_key,
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
  const checkoutIntentKey = useMemo(() => {
    if (step !== "details" || !selected?.slug || !checkIn || !checkOut) {
      return null;
    }
    return ["checkout_step", selected.slug, checkIn, checkOut, adults, children, pets].join(":");
  }, [adults, checkIn, checkOut, children, pets, selected?.slug, step]);

  useEffect(() => {
    if (!checkoutIntentKey || step !== "details" || !selected?.slug || !checkIn || !checkOut) {
      return;
    }
    void postStorefrontIntentEvent({
      eventType: "checkout_step",
      propertySlug: selected.slug,
      dedupeKey: checkoutIntentKey,
      meta: {
        check_in: checkIn,
        check_out: checkOut,
        adults,
        children,
        pets,
      },
    });
  }, [adults, checkIn, checkOut, checkoutIntentKey, children, pets, selected?.slug, step]);

  const postConciergeResolve = useCallback(
    async (flow: "save_quote" | "booking_field_blur") => {
      const sid = getStorefrontSessionId();
      if (!sid || !conciergeRecoveryOptIn) return;
      try {
        const res = await fetch("/api/storefront/concierge/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            session_id: sid,
            consent_recovery_contact: true,
            flow,
            email: guestInfo.email.trim() || null,
            phone: guestInfo.phone.trim() || null,
            guest_first_name: guestInfo.first_name.trim() || null,
            guest_last_name: guestInfo.last_name.trim() || null,
            property_slug: selected?.slug?.trim() || null,
          }),
        });
        const data = (await res.json()) as {
          linked?: boolean;
          detail?: string;
          created_guest?: boolean;
        };
        if (!res.ok) {
          setSaveQuoteMessage(typeof data.detail === "string" ? data.detail : "Could not save reminders.");
          return;
        }
        if (flow === "save_quote") {
          setSaveQuoteMessage(
            data.linked
              ? data.created_guest
                ? "Profile created — we can reach you if you step away."
                : "You're on file — we'll reach out if you step away."
              : "Add a valid email and name so we can save this quote.",
          );
        }
      } catch {
        setSaveQuoteMessage("Network error saving reminders.");
      }
    },
    [conciergeRecoveryOptIn, guestInfo, selected?.slug],
  );

  const scheduleBlurResolve = useCallback(() => {
    if (!conciergeRecoveryOptIn) return;
    if (resolveDebounce.current) clearTimeout(resolveDebounce.current);
    resolveDebounce.current = setTimeout(() => {
      void postConciergeResolve("booking_field_blur");
    }, 500);
  }, [conciergeRecoveryOptIn, postConciergeResolve]);

  useEffect(() => {
    return () => {
      if (resolveDebounce.current) clearTimeout(resolveDebounce.current);
    };
  }, []);

  const checkoutLedgerError =
    sovereignCheckout.configError ??
    sovereignCheckout.quoteError ??
    sovereignCheckout.signingError ??
    null;

  const checkoutFlowBusy =
    sovereignCheckout.configLoading ||
    sovereignCheckout.quotePending ||
    sovereignCheckout.signingPending;

  const stripePublishableKey =
    sovereignCheckout.config?.stripe_publishable_key ||
    bookingConfig.data?.stripe_publishable_key ||
    "";

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
    setAdults(Math.max(1, guests));
    setChildren(0);
    setPets(0);
    setStep("details");
  }

  function handleBook(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProperty) {
      return;
    }

    const payload: Record<string, unknown> = {
      property_id: selectedProperty,
      check_in: checkIn,
      check_out: checkOut,
      num_guests: guests,
      adults,
      children,
      pets,
      guest_first_name: guestInfo.first_name,
      guest_last_name: guestInfo.last_name,
      guest_email: guestInfo.email,
      guest_phone: guestInfo.phone,
      special_requests: guestInfo.requests || undefined,
    };
    if (
      sovereignCheckout.sovereign_quote_signing_required &&
      sovereignCheckout.signedQuote
    ) {
      payload.signed_quote = sovereignCheckout.signedQuote;
    }
    const intentSid = getStorefrontSessionId();
    if (intentSid) {
      payload.intent_session_id = intentSid;
    }
    bookMutation.mutate(payload);
  }

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
                <div className="rounded-2xl border border-sky-200 bg-sky-50/90 p-5 shadow-sm">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 rounded-full border border-sky-200 bg-white p-2 text-sky-700">
                      <Mail className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-3">
                      <div>
                        <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-sky-900">
                          Sovereign Concierge
                        </h3>
                        <p className="mt-1 text-sm text-sky-950/80">
                          Save this quote and opt in to gentle reminders if you leave without booking.
                        </p>
                      </div>
                      <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-800">
                        <input
                          type="checkbox"
                          className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300"
                          checked={conciergeRecoveryOptIn}
                          onChange={(e) => {
                            setConciergeRecoveryOptIn(e.target.checked);
                            if (!e.target.checked) setSaveQuoteMessage(null);
                          }}
                        />
                        <span>
                          If I don&apos;t finish checkout, you may <strong>email or text me</strong> about{" "}
                          <strong>this trip</strong> (availability, totals, and recovery nudges). Required for
                          save-quote and field linking.
                        </span>
                      </label>
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                        <button
                          type="button"
                          disabled={
                            !conciergeRecoveryOptIn ||
                            !guestInfo.email.trim() ||
                            !guestInfo.first_name.trim() ||
                            !guestInfo.last_name.trim()
                          }
                          onClick={() => void postConciergeResolve("save_quote")}
                          className="inline-flex items-center justify-center rounded-sm border border-sky-700 bg-sky-900 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white transition hover:bg-sky-950 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Save quote &amp; enable recovery
                        </button>
                        <span className="text-xs text-slate-600">
                          Uses the same name, email, and phone as your booking form.
                        </span>
                      </div>
                      {saveQuoteMessage ? (
                        <p className="text-sm text-sky-950">{saveQuoteMessage}</p>
                      ) : null}
                    </div>
                  </div>
                </div>

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
                    onBlur={() => scheduleBlurResolve()}
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
                    onBlur={() => scheduleBlurResolve()}
                    className="border-slate-300 bg-white text-slate-900"
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="checkout-pets" className="text-slate-800">
                    Pets (for pricing / sealed quote)
                  </Label>
                  <Input
                    id="checkout-pets"
                    type="number"
                    min={0}
                    max={12}
                    value={pets}
                    onChange={(event) => setPets(Math.max(0, Math.min(12, Number(event.target.value) || 0)))}
                    className="border-slate-300 bg-white text-slate-900"
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
                    checkoutFlowBusy ||
                    !sovereignCheckout.readyForHold
                  }
                  className="inline-flex w-full items-center justify-center gap-2 rounded-sm bg-slate-900 px-6 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <CreditCard className="h-4 w-4" />
                  {bookMutation.isPending
                    ? "Securing Your Hold"
                    : `Continue to Payment ${formatCurrency(
                        sovereignCheckout.quoteState?.quote?.total_amount ??
                          ("pricing" in selected ? selected.pricing.total : 0),
                      )}`}
                </button>

                {checkoutLedgerError ? (
                  <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {checkoutLedgerError}
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
                  Pricing is loaded from the sovereign ledger via server actions (direct backend{" "}
                  <code className="rounded bg-white px-1.5 py-0.5 text-xs text-slate-700">
                    /api/direct-booking/quote
                  </code>
                  ). When signing is required, the flow acquires{" "}
                  <code className="rounded bg-white px-1.5 py-0.5 text-xs text-slate-700">
                    /api/direct-booking/signed-quote
                  </code>{" "}
                  before{" "}
                  <code className="rounded bg-white px-1.5 py-0.5 text-xs text-slate-700">
                    /book
                  </code>{" "}
                  creates the hold.
                </p>
                {sovereignCheckout.sovereign_quote_signing_required ? (
                  <p className="text-xs font-medium uppercase tracking-[0.16em] text-emerald-700">
                    HMAC-sealed quote required for this environment
                  </p>
                ) : null}
              </div>

              <div className="mt-6 space-y-3 rounded-[1.5rem] border border-slate-200 bg-white p-5">
                {checkoutFlowBusy ? (
                  <p className="text-sm text-slate-600">Syncing ledger quote{sovereignCheckout.sovereign_quote_signing_required ? " and seal" : ""}…</p>
                ) : checkoutLedgerError ? (
                  <p className="text-sm text-rose-700">{checkoutLedgerError}</p>
                ) : sovereignCheckout.quoteState?.quote ? (
                  <>
                    {sovereignCheckout.quoteState.quote.line_items.map((item) => (
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
                      <span>
                        {formatCurrency(sovereignCheckout.quoteState.quote.total_amount)}
                      </span>
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
                    {pets > 0 ? ` · ${pets} pet${pets === 1 ? "" : "s"}` : ""}
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
              {!stripePublishableKey && bookingConfig.isLoading ? (
                <p className="text-sm text-slate-600">Loading payment form...</p>
              ) : (
                <DirectBookingPayPanel
                  publishableKey={stripePublishableKey}
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
