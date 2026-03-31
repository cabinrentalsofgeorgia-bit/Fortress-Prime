"use client";

import { useMutation } from "@tanstack/react-query";

import { api, ApiError } from "./api";
import type {
  AiAskRequest,
  AiAskResponse,
  AiForecastRequest,
  AiForecastResponse,
  AiOptimizeListingRequest,
  AiOptimizeListingResponse,
  AiPredictMaintenanceRequest,
  AiPredictMaintenanceResponse,
  ConversationThread,
  Property,
  Reservation,
  WorkOrder,
} from "./types";

export const DEFAULT_AI_INSIGHTS_FORECAST_REQUEST: AiForecastRequest = {
  historical_data: [
    { month: "2025-12", revenue: 84250, occupancy: 0.74 },
    { month: "2026-01", revenue: 91780, occupancy: 0.79 },
    { month: "2026-02", revenue: 88410, occupancy: 0.76 },
  ],
  forecast_months: 3,
};

export const DEFAULT_AI_INSIGHTS_MAINTENANCE_REQUEST: AiPredictMaintenanceRequest = {
  work_orders: [],
  messages: [],
};

export const DEFAULT_AI_INSIGHTS_LISTING_REQUEST: AiOptimizeListingRequest = {
  property_name: "Fortress Prime Portfolio",
  bedrooms: 4,
  bathrooms: 3.5,
  max_guests: 10,
  amenities: ["hot tub", "mountain views", "fireplace", "fast wifi"],
  location: "Blue Ridge, GA",
};

const MAINTENANCE_SIGNAL_KEYWORDS = [
  "hvac",
  "heat",
  "ac",
  "air",
  "plumbing",
  "leak",
  "water",
  "hot tub",
  "wifi",
  "internet",
  "door",
  "lock",
  "power",
  "electrical",
  "smoke",
  "septic",
];

function formatMonthKey(dateLike?: string): string | null {
  if (!dateLike) return null;
  const parsed = new Date(dateLike);
  if (Number.isNaN(parsed.getTime())) {
    return /^\d{4}-\d{2}/.test(dateLike) ? dateLike.slice(0, 7) : null;
  }
  return parsed.toISOString().slice(0, 7);
}

function deriveNights(reservation: Reservation): number {
  if (typeof reservation.nights_count === "number" && reservation.nights_count > 0) {
    return reservation.nights_count;
  }
  if (typeof reservation.nights === "number" && reservation.nights > 0) {
    return reservation.nights;
  }
  if (reservation.check_in_date && reservation.check_out_date) {
    const checkIn = new Date(reservation.check_in_date);
    const checkOut = new Date(reservation.check_out_date);
    const diffMs = checkOut.getTime() - checkIn.getTime();
    if (Number.isFinite(diffMs) && diffMs > 0) {
      return Math.round(diffMs / 86_400_000);
    }
  }
  return 0;
}

function deriveIssueKeywords(textParts: Array<string | undefined>): string[] {
  const haystack = textParts
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return MAINTENANCE_SIGNAL_KEYWORDS.filter((keyword) => {
    const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`(^|[^a-z])${escaped}($|[^a-z])`, "i");
    return pattern.test(haystack);
  });
}

function deriveListingAmenities(property: Property): string[] {
  const amenities = new Set<string>();

  if (property.wifi_ssid) amenities.add("fast wifi");
  if (property.access_code_type || property.access_code_location) amenities.add("self check-in");
  if (property.parking_instructions) amenities.add("dedicated parking");
  if (property.max_guests >= 8) amenities.add("large-group friendly");
  if (property.property_type) amenities.add(String(property.property_type).replace(/_/g, " "));

  return Array.from(amenities).slice(0, 6);
}

export function buildAiForecastRequest(reservations?: Reservation[]): AiForecastRequest {
  const rows = Array.isArray(reservations) ? reservations : [];
  const grouped = new Map<
    string,
    {
      month: string;
      revenue: number;
      reservation_count: number;
      occupied_nights: number;
      guest_count: number;
    }
  >();

  for (const reservation of rows) {
    if (reservation.status === "cancelled") continue;
    const month = formatMonthKey(reservation.check_in_date || reservation.created_at);
    if (!month) continue;
    const revenue = Number(reservation.total_amount ?? 0);
    const current = grouped.get(month) ?? {
      month,
      revenue: 0,
      reservation_count: 0,
      occupied_nights: 0,
      guest_count: 0,
    };
    current.revenue += Number.isFinite(revenue) ? revenue : 0;
    current.reservation_count += 1;
    current.occupied_nights += deriveNights(reservation);
    current.guest_count += Math.max(0, Number(reservation.num_guests ?? 0));
    grouped.set(month, current);
  }

  const historicalData = Array.from(grouped.values())
    .sort((a, b) => a.month.localeCompare(b.month))
    .slice(-6)
    .map((entry) => ({
      ...entry,
      average_booking_value:
        entry.reservation_count > 0 ? Number((entry.revenue / entry.reservation_count).toFixed(2)) : 0,
      average_length_of_stay:
        entry.reservation_count > 0 ? Number((entry.occupied_nights / entry.reservation_count).toFixed(2)) : 0,
      average_party_size:
        entry.reservation_count > 0 ? Number((entry.guest_count / entry.reservation_count).toFixed(2)) : 0,
    }));

  if (historicalData.length === 0) {
    return DEFAULT_AI_INSIGHTS_FORECAST_REQUEST;
  }

  return {
    historical_data: historicalData,
    forecast_months: 3,
  };
}

export function buildAiMaintenanceRequest(
  workOrders?: WorkOrder[],
  conversations?: ConversationThread[],
): AiPredictMaintenanceRequest {
  const rows = Array.isArray(workOrders) ? workOrders : [];
  const categoryBreakdown = rows.reduce<Record<string, number>>((acc, workOrder) => {
    const key = workOrder.category || "uncategorized";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  const priorityBreakdown = rows.reduce<Record<string, number>>((acc, workOrder) => {
    const key = workOrder.priority || "unknown";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  const mappedWorkOrders = Array.isArray(workOrders)
    ? [
        {
          kind: "summary",
          total_work_orders: rows.length,
          open_work_orders: rows.filter((workOrder) => workOrder.status !== "completed").length,
          urgent_work_orders: rows.filter((workOrder) => workOrder.priority === "urgent").length,
          category_breakdown: categoryBreakdown,
          priority_breakdown: priorityBreakdown,
        },
        ...workOrders.slice(0, 20).map((workOrder) => ({
        id: workOrder.id,
        ticket_number: workOrder.ticket_number,
        property_id: workOrder.property_id,
        property_name: workOrder.property?.name,
        title: workOrder.title,
        description: workOrder.description,
        category: workOrder.category,
        priority: workOrder.priority,
        status: workOrder.status,
        created_at: workOrder.created_at,
          issue_keywords: deriveIssueKeywords([workOrder.title, workOrder.description]),
        })),
      ]
    : [];

  const relevantConversations = Array.isArray(conversations)
    ? conversations.filter((conversation) =>
        deriveIssueKeywords([conversation.last_message, conversation.property_name]).length > 0,
      )
    : [];

  const mappedMessages = Array.isArray(conversations)
    ? [
        {
          kind: "summary",
          total_threads_reviewed: conversations.length,
          maintenance_signal_threads: relevantConversations.length,
        },
        ...relevantConversations.slice(0, 20).map((conversation) => ({
        guest_id: conversation.guest_id,
        guest_name: conversation.guest_name,
        guest_phone: conversation.guest_phone,
        property_name: conversation.property_name,
        last_message: conversation.last_message,
        last_message_at: conversation.last_message_at,
        unread_count: conversation.unread_count,
          issue_keywords: deriveIssueKeywords([conversation.last_message, conversation.property_name]),
        })),
      ]
    : [];

  if (rows.length === 0 && relevantConversations.length === 0) {
    return DEFAULT_AI_INSIGHTS_MAINTENANCE_REQUEST;
  }

  return {
    work_orders: mappedWorkOrders,
    messages: mappedMessages,
  };
}

export function buildAiListingRequest(properties?: Property[]): AiOptimizeListingRequest {
  const activeProperties = Array.isArray(properties) ? properties.filter((property) => property.is_active) : [];
  const selectedProperty =
    activeProperties.sort((a, b) => (b.max_guests || 0) - (a.max_guests || 0))[0] ?? null;

  if (!selectedProperty) {
    return DEFAULT_AI_INSIGHTS_LISTING_REQUEST;
  }

  return {
    property_name: selectedProperty.name,
    bedrooms: selectedProperty.bedrooms,
    bathrooms: selectedProperty.bathrooms,
    max_guests: selectedProperty.max_guests,
    amenities: deriveListingAmenities(selectedProperty),
    location: selectedProperty.address || "Blue Ridge, GA",
  };
}

export function useAiAsk() {
  return useMutation<AiAskResponse, ApiError, AiAskRequest>({
    mutationFn: (body) => api.post("/api/ai/ask", body),
  });
}

export function useAiForecast() {
  return useMutation<AiForecastResponse, ApiError, AiForecastRequest>({
    mutationFn: (body) => api.post("/api/ai/forecast", body),
  });
}

export function useAiPredictMaintenance() {
  return useMutation<AiPredictMaintenanceResponse, ApiError, AiPredictMaintenanceRequest>({
    mutationFn: (body) => api.post("/api/ai/predict-maintenance", body),
  });
}

export function useAiOptimizeListing() {
  return useMutation<AiOptimizeListingResponse, ApiError, AiOptimizeListingRequest>({
    mutationFn: (body) => api.post("/api/ai/optimize-listing", body),
  });
}
