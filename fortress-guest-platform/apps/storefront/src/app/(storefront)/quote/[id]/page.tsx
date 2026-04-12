import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  Bath,
  BedDouble,
  CalendarDays,
  Moon,
  PawPrint,
  Users,
} from "lucide-react";

import { buildBackendUrl } from "@/lib/server/backend-url";
import { QuoteCountdown } from "./_components/quote-countdown";
import { QuotePricingBreakdown } from "./_components/quote-pricing-breakdown";
import { QuoteBookButton } from "./_components/quote-book-button";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GuestQuotePublic {
  id: string;
  status: "pending" | "accepted" | "rejected" | "expired";
  target_property_id: string;
  property_name: string;
  property_slug: string | null;
  property_type: string | null;
  property_bedrooms: number | null;
  property_bathrooms: number | null;
  property_max_guests: number | null;
  property_hero_image: string | null;
  check_in: string | null;
  check_out: string | null;
  nights: number | null;
  adults: number;
  children: number;
  pets: number;
  currency: string;
  base_rent: number;
  taxes: number;
  fees: number;
  total_amount: number;
  sovereign_narrative: string;
  quote_breakdown: Record<string, unknown>;
  stripe_payment_link_url: string | null;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

type PageParams = { id: string };

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchGuestQuote(id: string): Promise<GuestQuotePublic | null> {
  try {
    const res = await fetch(buildBackendUrl(`/api/quotes/${encodeURIComponent(id)}`), {
      cache: "no-store",
    });
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return (await res.json()) as GuestQuotePublic;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export async function generateMetadata({
  params,
}: {
  params: Promise<PageParams> | PageParams;
}): Promise<Metadata> {
  const { id } = await Promise.resolve(params);
  const quote = await fetchGuestQuote(id);

  if (!quote) {
    return { title: "Quote Not Found | Cabin Rentals of Georgia" };
  }

  return {
    title: `Your Quote — ${quote.property_name} | Cabin Rentals of Georgia`,
    description: `View your custom cabin quote for ${quote.property_name}. Total: $${quote.total_amount.toFixed(2)}.`,
    robots: { index: false, follow: false },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DATE_FMT = new Intl.DateTimeFormat("en-US", {
  month: "long",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

function fmtDate(iso: string): string {
  return DATE_FMT.format(new Date(iso));
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

function isQuoteActive(quote: GuestQuotePublic): boolean {
  return quote.status === "pending" && new Date(quote.expires_at) > new Date();
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function GuestQuotePage({
  params,
}: {
  params: Promise<PageParams> | PageParams;
}) {
  const { id } = await Promise.resolve(params);
  const quote = await fetchGuestQuote(id);

  if (!quote) notFound();

  const active = isQuoteActive(quote);
  const accepted = quote.status === "accepted";
  const expired =
    quote.status === "expired" ||
    (quote.status === "pending" && new Date(quote.expires_at) <= new Date());

  const guestSummaryParts: string[] = [];
  if (quote.adults) guestSummaryParts.push(`${quote.adults} adult${quote.adults !== 1 ? "s" : ""}`);
  if (quote.children) guestSummaryParts.push(`${quote.children} child${quote.children !== 1 ? "ren" : ""}`);
  if (quote.pets) guestSummaryParts.push(`${quote.pets} pet${quote.pets !== 1 ? "s" : ""}`);
  const guestSummary = guestSummaryParts.join(", ");

  const refId = quote.id.slice(0, 8).toUpperCase();

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">

      {/* ── Breadcrumb ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <Link
          href={quote.property_slug ? `/cabins/${quote.property_slug}` : "/"}
          className="inline-flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-slate-900"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {quote.property_slug ? "Back to cabin" : "Home"}
        </Link>

        <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-500">
          Quote · GQ-{refId}
        </div>
      </div>

      {/* ── Expired banner ─────────────────────────────────────────────── */}
      {expired && (
        <div className="mt-6 rounded-[2rem] border border-amber-200 bg-amber-50 px-8 py-6">
          <p className="text-sm font-semibold text-amber-800">This quote has expired.</p>
          <p className="mt-1 text-sm text-amber-700">
            Quotes are valid for 24 hours. Please request a fresh quote to continue.
          </p>
          {quote.property_slug && (
            <Link
              href={`/cabins/${quote.property_slug}`}
              className="mt-4 inline-flex items-center gap-1.5 rounded-sm bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-black"
            >
              View cabin &amp; get a new quote
            </Link>
          )}
        </div>
      )}

      {/* ── Accepted banner ────────────────────────────────────────────── */}
      {accepted && (
        <div className="mt-6 rounded-[2rem] border border-emerald-200 bg-emerald-50 px-8 py-6">
          <p className="text-sm font-semibold text-emerald-800">This quote has been accepted.</p>
          <p className="mt-1 text-sm text-emerald-700">
            Your reservation is confirmed. Check your email for full details and your rental agreement.
          </p>
        </div>
      )}

      {/* ── Main grid ──────────────────────────────────────────────────── */}
      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_380px]">

        {/* ── LEFT: property card + pricing ──────────────────────────── */}
        <div className="flex flex-col gap-6">

          {/* Property hero image */}
          {quote.property_hero_image && (
            <div className="relative aspect-[16/9] overflow-hidden rounded-[2rem] border border-slate-200 bg-slate-100 shadow-sm">
              <Image
                src={quote.property_hero_image}
                alt={quote.property_name}
                fill
                className="object-cover"
                priority
                sizes="(max-width: 1024px) 100vw, 60vw"
              />
            </div>
          )}

          {/* Property identity card */}
          <div className="rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">

            {quote.property_type && (
              <div className="mb-3 inline-flex items-center rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-600">
                {quote.property_type}
              </div>
            )}

            <h1 className="text-3xl font-light tracking-tight text-slate-900">
              {quote.property_name}
            </h1>

            {/* Amenity chips */}
            {(quote.property_bedrooms !== null ||
              quote.property_bathrooms !== null ||
              quote.property_max_guests !== null) && (
              <div className="mt-5 flex flex-wrap gap-3">
                {quote.property_bedrooms !== null && (
                  <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-700">
                    <BedDouble className="h-4 w-4 text-slate-400" />
                    {quote.property_bedrooms} bedroom{quote.property_bedrooms !== 1 ? "s" : ""}
                  </div>
                )}
                {quote.property_bathrooms !== null && (
                  <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-700">
                    <Bath className="h-4 w-4 text-slate-400" />
                    {quote.property_bathrooms} bath{quote.property_bathrooms !== 1 ? "s" : ""}
                  </div>
                )}
                {quote.property_max_guests !== null && (
                  <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-700">
                    <Users className="h-4 w-4 text-slate-400" />
                    Up to {quote.property_max_guests} guests
                  </div>
                )}
              </div>
            )}

            {/* Stay dates */}
            {(quote.check_in || quote.check_out) && (
              <div className="mt-6 grid gap-3 sm:grid-cols-2">
                {quote.check_in && (
                  <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 px-5 py-4">
                    <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
                      <CalendarDays className="h-3.5 w-3.5" />
                      Check-in
                    </div>
                    <p className="mt-1.5 text-base font-semibold text-slate-900">
                      {fmtDate(quote.check_in)}
                    </p>
                  </div>
                )}
                {quote.check_out && (
                  <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 px-5 py-4">
                    <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
                      <CalendarDays className="h-3.5 w-3.5" />
                      Check-out
                    </div>
                    <p className="mt-1.5 text-base font-semibold text-slate-900">
                      {fmtDate(quote.check_out)}
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Stay summary chips */}
            <div className="mt-4 flex flex-wrap gap-2">
              {quote.nights !== null && (
                <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
                  <Moon className="h-3 w-3" />
                  {quote.nights} night{quote.nights !== 1 ? "s" : ""}
                </div>
              )}
              {guestSummary && (
                <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
                  <Users className="h-3 w-3" />
                  {guestSummary}
                </div>
              )}
              {quote.pets > 0 && (
                <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
                  <PawPrint className="h-3 w-3" />
                  Pet-friendly stay
                </div>
              )}
            </div>
          </div>

          {/* Pricing breakdown card */}
          <div className="rounded-[2rem] border border-slate-200 bg-white p-8 shadow-sm">
            <div className="mb-2 text-xs font-medium uppercase tracking-[0.22em] text-slate-500">
              Price breakdown
            </div>
            <h2 className="mb-6 text-2xl font-semibold tracking-tight text-slate-900">
              {formatCurrency(quote.total_amount)}
            </h2>
            <QuotePricingBreakdown
              baseRent={quote.base_rent}
              taxes={quote.taxes}
              fees={quote.fees}
              totalAmount={quote.total_amount}
              nights={quote.nights}
            />
          </div>
        </div>

        {/* ── RIGHT: quote summary + CTA ─────────────────────────────── */}
        <div className="flex flex-col gap-4">
          <div className="sticky top-6 flex flex-col gap-4">

            {/* Summary card */}
            <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm">

              {/* Status / countdown */}
              <div className="mb-4">
                {active && <QuoteCountdown expiresAt={quote.expires_at} />}
                {accepted && (
                  <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-emerald-700">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    Accepted
                  </div>
                )}
                {expired && (
                  <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                    Expired
                  </div>
                )}
              </div>

              <p className="text-xs font-medium uppercase tracking-[0.22em] text-slate-500">
                Your quote
              </p>
              <p className="mt-1 text-3xl font-light tracking-tight text-slate-900">
                {formatCurrency(quote.total_amount)}
              </p>

              {quote.nights !== null && (
                <p className="mt-0.5 text-sm text-slate-500">
                  {quote.nights} night{quote.nights !== 1 ? "s" : ""} ·{" "}
                  {formatCurrency(quote.total_amount / quote.nights)} avg / night
                </p>
              )}

              {/* AI narrative */}
              {quote.sovereign_narrative &&
                quote.sovereign_narrative !== "Autogenerated checkout quote" && (
                  <p className="mt-4 text-sm leading-6 text-slate-600">
                    {quote.sovereign_narrative}
                  </p>
                )}

              {/* CTA */}
              {active && (
                <div className="mt-6">
                  <QuoteBookButton
                    stripePaymentLinkUrl={quote.stripe_payment_link_url}
                    propertyId={quote.target_property_id}
                    checkIn={quote.check_in}
                    checkOut={quote.check_out}
                    adults={quote.adults}
                    children={quote.children}
                    pets={quote.pets}
                    quoteId={quote.id}
                  />
                </div>
              )}

              {/* Accepted state CTA */}
              {accepted && quote.property_slug && (
                <div className="mt-6">
                  <Link
                    href={`/cabins/${quote.property_slug}`}
                    className="flex w-full items-center justify-center gap-2 rounded-sm border border-slate-200 bg-slate-50 px-6 py-4 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-100"
                  >
                    View cabin details
                  </Link>
                </div>
              )}
            </div>

            {/* Policy card */}
            <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 px-6 py-5">
              <ul className="space-y-2 text-xs leading-5 text-slate-500">
                <li>
                  <span className="font-medium text-slate-700">Valid for 24 hours</span> from the
                  time of issue.
                </li>
                <li>Prices reflect the current rate calendar and may change after expiry.</li>
                <li>
                  Questions?{" "}
                  <a
                    href="tel:+17064555555"
                    className="font-medium text-slate-700 underline-offset-2 hover:underline"
                  >
                    (706) 455-5555
                  </a>
                </li>
              </ul>
            </div>

          </div>
        </div>
      </div>

      {/* ── Footer attribution ─────────────────────────────────────────── */}
      <div className="mt-12 border-t border-slate-100 pt-6 text-center text-xs text-slate-400">
        Cabin Rentals of Georgia · Blue Ridge &amp; North Georgia Mountains
      </div>
    </div>
  );
}
