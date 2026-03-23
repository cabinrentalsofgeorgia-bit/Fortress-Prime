"use server";

export type QuoteRequestType = {
  propertyId: string;
  checkIn: string;
  checkOut: string;
  adults: number;
  children: number;
  pets: number;
};

export type QuoteLineItemType = {
  description: string;
  amount: number;
  type: "rent" | "fee" | "tax" | "discount";
};

export type QuoteResponseType = {
  property_id: string;
  currency: string;
  line_items: QuoteLineItemType[];
  total_amount: number;
  is_bookable: boolean;
};

export type QuoteActionState =
  | {
      ok: true;
      quote: QuoteResponseType;
      error: null;
    }
  | {
      ok: false;
      quote: QuoteResponseType | null;
      error: string;
    };

const FGP_BACKEND_URL = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";

function buildUrl(path: string): string {
  return `${FGP_BACKEND_URL.replace(/\/$/, "")}${path}`;
}

type DirectBookingQuoteResponse = {
  property_id: string;
  property_name: string;
  nights: number;
  guests: number;
  pricing_source: string;
  breakdown: {
    nightly_rate: number;
    subtotal: number;
    cleaning_fee: number;
    pet_fee: number;
    service_fee: number;
    tax: number;
    total: number;
    nightly_breakdown: Array<{ date: string; rate: number }>;
  };
};

function diffNights(checkIn: string, checkOut: string): number {
  const start = new Date(`${checkIn}T00:00:00Z`);
  const end = new Date(`${checkOut}T00:00:00Z`);
  const diffMs = end.getTime() - start.getTime();
  if (!Number.isFinite(diffMs) || diffMs <= 0) {
    return 1;
  }
  return Math.max(1, Math.round(diffMs / 86_400_000));
}

function mapQuoteResponse(response: DirectBookingQuoteResponse): QuoteResponseType {
  const lineItems: QuoteLineItemType[] = [
    {
      description: `${response.nights} night stay @ $${response.breakdown.nightly_rate.toFixed(2)} / night`,
      amount: response.breakdown.subtotal,
      type: "rent",
    },
  ];

  if (response.breakdown.cleaning_fee > 0) {
    lineItems.push({
      description: "Cleaning Fee",
      amount: response.breakdown.cleaning_fee,
      type: "fee",
    });
  }

  if (response.breakdown.service_fee > 0) {
    lineItems.push({
      description: "Service Fee",
      amount: response.breakdown.service_fee,
      type: "fee",
    });
  }

  if (response.breakdown.pet_fee > 0) {
    lineItems.push({
      description: "Pet Fee",
      amount: response.breakdown.pet_fee,
      type: "fee",
    });
  }

  if (response.breakdown.tax > 0) {
    lineItems.push({
      description: "Tax",
      amount: response.breakdown.tax,
      type: "tax",
    });
  }

  return {
    property_id: response.property_id,
    currency: "USD",
    line_items: lineItems,
    total_amount: response.breakdown.total,
    is_bookable: true,
  };
}

export async function getFastQuote(payload: QuoteRequestType): Promise<QuoteActionState> {
  if (process.env.CI) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const nights = diffNights(payload.checkIn, payload.checkOut);
    const nightlyRate = 250;
    const subtotal = nights * nightlyRate;
    const cleaningFee = 150;
    const tax = Math.round(subtotal * 0.13 * 100) / 100;

    return {
      ok: true,
      quote: {
        property_id: payload.propertyId,
        currency: "USD",
        line_items: [
          {
            description: `${nights} night stay @ $${nightlyRate.toFixed(2)} / night`,
            amount: subtotal,
            type: "rent",
          },
          {
            description: "Cleaning Fee",
            amount: cleaningFee,
            type: "fee",
          },
          {
            description: "Tax",
            amount: tax,
            type: "tax",
          },
        ],
        total_amount: subtotal + cleaningFee + tax,
        is_bookable: true,
      },
      error: null,
    };
  }

  const response = await fetch(buildUrl(`/api/direct-booking/quote?property_id=${encodeURIComponent(payload.propertyId)}`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    cache: "no-store",
    body: JSON.stringify({
      check_in: payload.checkIn,
      check_out: payload.checkOut,
      guests: payload.adults + payload.children,
      pets: payload.pets > 0,
    }),
  });

  const data = (await response.json().catch(() => null)) as
    | DirectBookingQuoteResponse
    | { detail?: string }
    | null;

  if (!response.ok) {
    return {
      ok: false,
      quote: null,
      error: data && typeof data === "object" && "detail" in data && data.detail
        ? String(data.detail)
        : "Unable to calculate quote right now.",
    };
  }

  const quote = mapQuoteResponse(data as DirectBookingQuoteResponse);

  return {
    ok: true,
    quote,
    error: null,
  };
}
