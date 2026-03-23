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
const INTERNAL_API_KEY =
  process.env.INTERNAL_API_KEY || process.env.SWARM_API_KEY || "";

function buildUrl(path: string): string {
  return `${FGP_BACKEND_URL.replace(/\/$/, "")}${path}`;
}

export async function getFastQuote(payload: QuoteRequestType): Promise<QuoteActionState> {
  if (!INTERNAL_API_KEY) {
    return {
      ok: false,
      quote: null,
      error: "Internal quote auth is not configured.",
    };
  }

  const response = await fetch(buildUrl("/api/quote"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${INTERNAL_API_KEY}`,
      "X-Swarm-Token": INTERNAL_API_KEY,
    },
    cache: "no-store",
    body: JSON.stringify({
      property_id: payload.propertyId,
      check_in: payload.checkIn,
      check_out: payload.checkOut,
      adults: payload.adults,
      children: payload.children,
      pets: payload.pets,
    }),
  });

  const data = (await response.json().catch(() => null)) as
    | QuoteResponseType
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

  const quote = data as QuoteResponseType;
  if (!quote.is_bookable) {
    return {
      ok: false,
      quote,
      error: "Selected party exceeds the cabin occupancy limit.",
    };
  }

  return {
    ok: true,
    quote,
    error: null,
  };
}
