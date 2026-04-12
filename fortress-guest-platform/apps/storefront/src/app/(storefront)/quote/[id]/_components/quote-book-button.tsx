"use client";

import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";

interface QuoteBookButtonProps {
  stripePaymentLinkUrl: string | null;
  propertyId: string;
  checkIn: string | null;
  checkOut: string | null;
  adults: number;
  children: number;
  pets: number;
  quoteId: string;
}

export function QuoteBookButton({
  stripePaymentLinkUrl,
  propertyId,
  checkIn,
  checkOut,
  adults,
  children,
  pets,
  quoteId,
}: QuoteBookButtonProps) {
  const router = useRouter();

  function handleBook() {
    if (stripePaymentLinkUrl) {
      window.location.href = stripePaymentLinkUrl;
      return;
    }

    const guests = adults + children;
    const params = new URLSearchParams({ propertyId, guests: String(guests) });
    if (checkIn) params.set("checkIn", checkIn);
    if (checkOut) params.set("checkOut", checkOut);
    params.set("adults", String(adults));
    params.set("children", String(children));
    params.set("pets", String(pets));
    params.set("quote_ref", quoteId);

    router.push(`/book?${params.toString()}`);
  }

  return (
    <button
      type="button"
      onClick={handleBook}
      className="flex w-full items-center justify-center gap-2 rounded-sm bg-slate-900 px-6 py-4 text-sm font-semibold text-white transition-colors hover:bg-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2"
    >
      Book This Cabin
      <ArrowRight className="h-4 w-4" />
    </button>
  );
}
