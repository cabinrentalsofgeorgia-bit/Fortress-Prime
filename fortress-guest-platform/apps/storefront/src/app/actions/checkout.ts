"use server";

import { buildBackendUrl } from "@/lib/server/backend-url";

export type DirectBookingConfig = {
  stripe_publishable_key: string;
  min_nights: number;
  max_nights: number;
  max_advance_days: number;
  cancellation_policy: string;
  service_fee_pct: number;
  tax_rate_pct: number;
  sovereign_quote_signing_required: boolean;
};

export type SignedSovereignQuotePayload = Record<string, unknown>;

export type SignedQuoteActionState =
  | { ok: true; quote: SignedSovereignQuotePayload; error: null }
  | { ok: false; quote: null; error: string };

export async function getDirectBookingConfig(): Promise<DirectBookingConfig | null> {
  if (process.env.CI) {
    return {
      stripe_publishable_key: "",
      min_nights: 1,
      max_nights: 30,
      max_advance_days: 365,
      cancellation_policy: "flexible",
      service_fee_pct: 3,
      tax_rate_pct: 8,
      sovereign_quote_signing_required: false,
    };
  }

  const response = await fetch(buildBackendUrl("/api/direct-booking/config"), {
    method: "GET",
    cache: "no-store",
  });

  const data = (await response.json().catch(() => null)) as DirectBookingConfig | null;
  if (!response.ok || !data) {
    return null;
  }
  return {
    ...data,
    sovereign_quote_signing_required: Boolean(data.sovereign_quote_signing_required),
  };
}

export type SignedQuoteRequest = {
  propertyId: string;
  checkIn: string;
  checkOut: string;
  guests: number;
  adults: number | null;
  children: number | null;
  pets: number;
};

export async function getSignedSovereignQuote(
  payload: SignedQuoteRequest,
): Promise<SignedQuoteActionState> {
  if (process.env.CI) {
    return {
      ok: true,
      quote: {
        v: 1,
        property_id: payload.propertyId,
        check_in: payload.checkIn,
        check_out: payload.checkOut,
        guests: payload.guests,
        total: "1.00",
        line_items: [],
        signature: "ci-mock",
      },
      error: null,
    };
  }

  const body: Record<string, string | number> = {
    check_in: payload.checkIn,
    check_out: payload.checkOut,
    guests: payload.guests,
    pets: payload.pets,
  };
  if (payload.adults !== null) {
    body.adults = payload.adults;
  }
  if (payload.children !== null) {
    body.children = payload.children;
  }

  const response = await fetch(
    buildBackendUrl(
      `/api/direct-booking/signed-quote?property_id=${encodeURIComponent(payload.propertyId)}`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(body),
    },
  );

  const data = (await response.json().catch(() => null)) as
    | SignedSovereignQuotePayload
    | { detail?: string }
    | null;

  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data && data.detail
        ? String(data.detail)
        : "Unable to seal quote.";
    return { ok: false, quote: null, error: detail };
  }

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { ok: false, quote: null, error: "Invalid signed quote response." };
  }

  return { ok: true, quote: data as SignedSovereignQuotePayload, error: null };
}
