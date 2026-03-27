export type AvailabilityPricing = {
  nights: number;
  subtotal: string;
  los_discount: string;
  extra_guest_fee: string;
  total: string;
  nightly_breakdown: Array<{
    date: string;
    rate: number;
    season: string;
    multiplier: number;
  }>;
};

export type PropertyAvailability = {
  property_id: string;
  property_name: string;
  slug: string;
  available: boolean;
  pricing?: AvailabilityPricing;
};

export type GetAvailabilityResponse = {
  check_in: string;
  check_out: string;
  guests: number;
  results: PropertyAvailability[];
};

export type CreateRedirectRequest = {
  source_path: string;
  destination_path: string;
  is_permanent?: boolean;
  reason?: string;
};

export type CreateRedirectResponse = {
  id: string;
  source_path: string;
  destination_path: string;
  status_code: 301 | 302;
  reason?: string | null;
  is_active: boolean;
};
