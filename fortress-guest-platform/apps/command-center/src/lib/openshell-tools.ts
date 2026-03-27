import { api } from "@/lib/api";
import type {
  CreateRedirectRequest,
  CreateRedirectResponse,
  GetAvailabilityResponse,
} from "@/lib/contracts/tools-v1";

export async function getPropertiesAvailability(params: {
  check_in: string;
  check_out: string;
  guests?: number;
}): Promise<GetAvailabilityResponse> {
  return api.get<GetAvailabilityResponse>("/api/v1/properties/availability", {
    check_in: params.check_in,
    check_out: params.check_out,
    guests: params.guests ?? 1,
  });
}

export async function createSeoRedirect(
  payload: CreateRedirectRequest,
): Promise<CreateRedirectResponse> {
  return api.post<CreateRedirectResponse>("/api/v1/seo/redirects", payload);
}
